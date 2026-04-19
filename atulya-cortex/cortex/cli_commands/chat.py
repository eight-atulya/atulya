"""chat — interactive TUI session (default subcommand).

Starts the rich `prompt_toolkit` + Rich TUI defined in `cortex/tui_app.py`
on top of the standard cortex pipeline:

    keyboard -> Stimulus -> Router (reflexes) -> Cortex.reflect -> reply

The reply lands back in the TUI as a markdown-rendered "atulya >" line.

The legacy `--lm-studio` flag is preserved as a one-shot override; for
day-to-day use the model section of `config.toml` controls everything.
"""

from __future__ import annotations

import argparse
import asyncio

NAME = "chat"
HELP = "Open an interactive TUI session with the cortex (default)."


def register(subparsers, common_parents) -> None:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=common_parents,
        description="Open an interactive terminal chat with the cortex.",
    )
    parser.add_argument(
        "--lm-studio",
        action="store_true",
        help="Force use of local LM Studio (overrides config). Equivalent to setting model.provider=lm_studio.",
    )
    parser.add_argument(
        "--peer",
        default=None,
        help="Identifier for the local peer; becomes the suffix of the tui channel. Default: config.general.peer.",
    )
    parser.add_argument(
        "--simple",
        action="store_true",
        help="Use the legacy line-by-line stdin sensor instead of the rich TUI (useful in pipes / dumb terminals).",
    )
    parser.set_defaults(_run=run)


def run(args: argparse.Namespace, *, home) -> int:
    from cortex import config as config_module

    try:
        cfg = config_module.load(home)
    except config_module.ConfigError as exc:
        print(f"error: {exc}\nrun `atulya-cortex setup` to fix.")
        return 2

    peer = args.peer or cfg.general.peer
    use_lm_studio = bool(args.lm_studio) or cfg.model.provider == "lm_studio"

    try:
        if args.simple:
            asyncio.run(_chat_simple(home=home, cfg=cfg, peer=peer, use_lm_studio=use_lm_studio))
        else:
            asyncio.run(_chat_rich(home=home, cfg=cfg, peer=peer, use_lm_studio=use_lm_studio))
    except KeyboardInterrupt:
        return 130
    return 0


# ---------------------------------------------------------------------------
# Rich TUI path (default)
# ---------------------------------------------------------------------------


async def _chat_rich(*, home, cfg, peer: str, use_lm_studio: bool) -> None:
    # Deferred imports so `--help` stays fast.
    from brainstem import Allowlist, ReflexChain, Router  # noqa: F401
    from cortex._runtime import build_cortex_from_config, build_language_from_config
    from cortex.tui_app import TuiContext, run_tui
    from motors import Reply

    if use_lm_studio:
        # Surgical override: build via shared helper but force the provider so
        # `--lm-studio` keeps working when `config.toml` has a different default.
        from copy import deepcopy

        cfg = deepcopy(cfg)
        cfg.model.provider = "lm_studio"

    language = build_language_from_config(cfg)
    cortex = build_cortex_from_config(home, cfg, language=language)

    # The Reply motor knows how to dispatch by channel prefix; for the rich
    # TUI we let `cortex_call` return the Intent and render it ourselves so
    # we get markdown formatting + spinner control. We still register a
    # no-op Reply so future cross-channel relays (`reply tui:* whatsapp:...`)
    # have a hook.
    Reply({"tui": _tui_noop_egress})
    reflexes = ReflexChain([Allowlist(allow=["tui:*"], default_decision="deny")])

    persona_summary = _persona_summary(home)
    ctx = TuiContext(
        home_root=home.root,
        profile_name=home.profile_name,
        provider=cfg.model.provider or "lm_studio",
        model=cfg.model.model or "(default)",
        base_url=cfg.model.base_url or "(provider default)",
        persona_summary=persona_summary,
        skills_dir=home.skills_dir,
        pairing_store=home.state_dir / "pairings.json",
        # Working-memory wiring: matches the (channel, peer) tuple
        # `Cortex.reflect` writes to, so /history and /forget point at
        # the same JSONL the LLM is actually reading from.
        conversations_dir=home.conversations_dir,
        active_channel="tui",
        active_peer=peer,
        # Snapshot the deliberation surface so the TUI's `/tools` command
        # shows what the brain may actually do without re-deriving it from
        # config (and accidentally diverging from what Cortex was wired
        # with). `None` = tools off, `()` = enabled but empty (a config
        # mismatch worth surfacing), tuple of names = active surface.
        tool_names=(
            None
            if not cfg.tools.enabled
            else tuple(s.name for s in cortex._tool_specs)
        ),
        tool_max_actions=cortex._max_actions if cortex._tool_specs else 0,
        # Long-term memory introspection: /facts and /episodes read these
        # paths directly so the TUI always shows the on-disk truth, even
        # if a future background consolidator wrote facts since boot.
        episodes_dir=home.episodes_dir,
        facts_dir=home.facts_dir,
        # /sleep needs a Language to do the distillation. We build the
        # Sleep engine lazily here (one per session) so its consolidation
        # cursor and stats persist for the whole TUI lifetime.
        sleep_now=_make_sleep_callable(home, cfg, language=language, channel="tui", peer=peer),
    )

    async def cortex_call(stim):
        # Mirror the Router's reflex pass so deny / pair behaviour stays
        # identical across channels. We don't dispatch through Reply because
        # the TUI renders the Intent itself for nicer formatting.
        decision = await reflexes.evaluate(stim)
        # `peer_key=peer` opts the TUI into per-peer working memory so
        # successive turns share context (model actually remembers what
        # you said two messages ago instead of restarting cold).
        return await cortex.reflect(stim, reflex=decision, peer_key=peer)

    history_path = home.state_dir / "tui_history.txt"

    try:
        await run_tui(cortex_call=cortex_call, ctx=ctx, history_path=history_path, peer=peer)
    finally:
        if language is not None:
            await language.aclose()


def _make_sleep_callable(home, cfg, *, language, channel: str, peer: str):
    """Build the `sleep_now` callable the TUI's `/sleep` command invokes.

    Built once per session so the underlying `Sleep` engine reuses its
    in-memory cursor + stats across multiple `/sleep` invocations. The
    closure binds the active (channel, peer) so the TUI doesn't have to
    pass them in — `/sleep` is always "consolidate THIS conversation".
    """

    if language is None:
        return None
    from cortex._runtime import build_sleep_from_config

    sleep = build_sleep_from_config(home, cfg, language=language)

    async def _sleep_now(*, force: bool = False):
        return await sleep.consolidate(channel=channel, peer=peer, force=force)

    return _sleep_now


async def _tui_noop_egress(channel: str, target: str, text: str) -> None:
    # Intentional no-op: the rich TUI renders the assistant turn itself.
    return None


def _persona_summary(home) -> str:
    if not home.persona_file.exists():
        return "(no persona.md — using defaults)"
    try:
        from cortex.personality import Personality

        p = Personality.load(home.persona_file)
        bio = (p.bio or "").strip().splitlines()
        head = bio[0] if bio else "(no bio)"
        traits = ", ".join(p.traits) if p.traits else "(no traits)"
        return f"voice: {p.voice}\ntraits: {traits}\nbio: {head}"
    except Exception as exc:
        return f"(failed to load persona: {exc})"


# ---------------------------------------------------------------------------
# Simple stdin path (legacy / pipe-friendly)
# ---------------------------------------------------------------------------


async def _chat_simple(*, home, cfg, peer: str, use_lm_studio: bool) -> None:
    from brainstem import Allowlist, ReflexChain, Router
    from cortex._runtime import build_cortex_from_config, build_language_from_config
    from motors import Reply
    from sensors import Terminal

    if use_lm_studio:
        from copy import deepcopy

        cfg = deepcopy(cfg)
        cfg.model.provider = "lm_studio"

    terminal = Terminal(peer=peer)
    language = build_language_from_config(cfg)
    cortex = build_cortex_from_config(home, cfg, language=language)

    async def egress(channel: str, target: str, text: str) -> None:
        terminal.print_reply(text)

    reply = Reply({"tui": egress})
    reflexes = ReflexChain([Allowlist(allow=["tui:*"], default_decision="deny")])

    async def cortex_call(stim, reflex):
        # Same working-memory wiring as the rich TUI: keep continuity per
        # local peer so the simple stdin path doesn't regress versus
        # `chat` proper.
        return await cortex.reflect(stim, reflex=reflex, peer_key=peer)

    async def reply_motor(intent):
        return await reply.act(intent)

    router = Router(reflexes=reflexes, cortex=cortex_call, reply_motor=reply_motor)

    await terminal.awaken()
    try:
        async for stim in terminal.perceive():
            await router.route(stim)
    finally:
        await terminal.rest()
        if language is not None:
            await language.aclose()


__all__ = ["NAME", "HELP", "register", "run"]
