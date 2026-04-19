# Skill: Diagnose A Broken Cortex

**When to use.** The cortex replies with nonsense, echoes input instead
of thinking, pretends not to remember a fact you know it learnt, or
silently fails to reply on WhatsApp / Telegram. You want a systematic,
shortest-path triage that does not require editing Python.

**Inputs.** A shell on the machine running cortex, the user-visible
symptom, and the timestamps around which it started.

**Procedure.**
1. **Start with doctor.** `atulya-cortex doctor`. It checks the home
   dirs, config schema, provider reachability, skills sync state, and
   pairings. Any red line is the first thing to fix; use `--fix` where
   offered.
2. **Classify the failure.** Pick ONE:
   - *Echo instead of thought* → LLM driver unreachable. Check the
     startup banner for `llm=ok`; `curl` the provider base URL.
   - *Thinks but doesn't remember* → memory wiring. Verify
     `~/.atulya/cortex/episodes/` has JSONL under the expected peer;
     if empty, the cortex was built without `peer_key` in the reflect
     call (regression check: `rg peer_key= cortex/cli_commands/`).
   - *Remembers TUI but not WhatsApp* → per-peer isolation working
     as designed. Each peer has its own fact file; teach again in
     that peer.
   - *Replies on WhatsApp are bland / dumb* → `[tools]
     allowed_channels` likely excludes whatsapp, AND / OR facts for
     that peer are empty. Fix one or both.
   - *Slash commands crash* → check `~/.atulya/cortex/logs/` tail;
     most crashes are a stale config field after an upgrade — re-run
     `atulya-cortex config check` and `config migrate` if prompted.
3. **Pull the last 200 log lines.**
   `tail -n 200 ~/.atulya/cortex/logs/cortex.log`. Look for
   `ERROR` or `WARNING` lines close to the symptom's timestamp;
   attach those to any bug report or paste back into a chat session
   with the cortex itself and ask it to diagnose.
4. **Reproduce with a minimal prompt.** In a fresh TUI session, send
   a one-sentence test that exercises the broken path. Keep the
   reproducer small so the fix's blast radius stays clear.
5. **If memory is wrong, dump the stores.**
   `ls -la ~/.atulya/cortex/{episodes,facts,state,conversations}/`.
   Sizes > 0 on the relevant peer confirm the writes happened; sizes
   == 0 means the upstream pipeline (reflect → append) broke.
6. **If the LLM is wrong, swap models.** `atulya-cortex model list`
   then `atulya-cortex model select <id>`. A different model ruling
   out a provider-specific failure is cheaper than three log-diving
   rounds.

**Output shape.** A one-paragraph root cause tied to a specific file
path, config key, or provider, plus the smallest command sequence
that fixes it. Optionally a minimal reproducer for future
regression tests.

**Anti-pattern.** Do not delete `~/.atulya/cortex/` as a
troubleshooting step — you will also erase the semantic memory the
brain has spent turns accumulating. Do not "fix" by silencing errors
without understanding them; a suppressed log today is a mystery bug
next week.
