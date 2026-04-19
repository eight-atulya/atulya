# Skill: Run Cortex End-to-End (First Run)

**When to use.** Someone — human or agent — has a fresh clone of
`atulya-cortex` or a just-installed `uv tool` and wants the brain alive
and thinking on their machine, from zero to a working `/chat` TUI that
remembers them across sessions.

**Inputs.** A shell, Python 3.11+, and one LLM backend running locally
(LM Studio at `:1234` or Ollama at `:11434`) or a cloud key
(`OPENAI_API_KEY`). Optional: WhatsApp / Telegram credentials for later
skills.

**Procedure.**
1. **Verify prerequisites.** Run `python --version` (>= 3.11) and
   confirm one of:
   - `curl -sS http://127.0.0.1:1234/v1/models` returns JSON (LM Studio).
   - `curl -sS http://127.0.0.1:11434/api/tags` returns JSON (Ollama).
   - `$OPENAI_API_KEY` is set.
2. **Install the tool.** From the repo:
   `uv sync --package atulya-cortex` then `uv run --package atulya-cortex atulya-cortex --help`
   should print the CLI. If using `uv tool install .` the binary is
   `atulya-cortex` on `$PATH`.
3. **Run the setup wizard.** `atulya-cortex setup`. It auto-detects the
   local provider, writes `~/.atulya/cortex/config.toml`, seeds a
   `persona.md`, and syncs bundled skills into `~/.atulya/cortex/skills/`.
4. **Run the doctor.** `atulya-cortex doctor`. Green = ready. Any red
   line tells you the exact file, env var, or daemon to fix; re-run
   with `--fix` where supported.
5. **Start a session.** `atulya-cortex chat`. Type `/help` to see all
   slash commands, `/model` to confirm which LLM is wired.
6. **Prove it thinks.** Ask something grounded like "summarise my
   config in one line". A sensible reply confirms the path is live.
7. **Prove it remembers.** Tell it one durable thing about yourself
   ("my daughter's name is Kuhi"). Run `/sleep`. Run `/facts`. You
   should see the fact. Quit, restart `chat`, ask "what's my
   daughter's name?" — it should answer from the prompt-injected
   facts, not a cold model.

**Output shape.** A living TUI with a working `/doctor` = all green,
`/tools` = non-empty, `/sleep` = `status=ok` on demand, and `/facts`
carrying at least one durable fact about the operator.

**Anti-pattern.** Do not edit `config.toml` by hand for the first run
— always use `setup` so every required path (episodes dir, facts dir,
cache roots) is bootstrapped consistently. Do not skip the doctor; the
quickest bugs to miss are the ones doctor catches in two seconds.
