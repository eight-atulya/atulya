# Skill: Bring The Brain Onto WhatsApp

**When to use.** The cortex works in the TUI and you want it to respond
on your personal WhatsApp number — real phone, real contacts, real
conversations — with its memory, tools, and persona intact.

**Inputs.** A working cortex (see the first-run skill), Node.js 18+ on
`PATH` for the Baileys bridge, a phone with WhatsApp installed, and
shell access to the machine running cortex. Optional: a list of
trusted contact ids to allowlist upfront.

**Procedure.**
1. **Pair the device.** Run `atulya-cortex whatsapp pair`. The Baileys
   bridge spawns and prints a QR in the terminal. In the phone's
   WhatsApp: Settings → Linked Devices → Link a Device → scan. Wait
   for `event=open`. Close the pair command (Ctrl-C); the session is
   persisted under `~/.atulya/cortex/whatsapp/session/`.
2. **Start the brain.** Run
   `atulya-cortex whatsapp start --default-allow` in one terminal.
   `--default-allow` lets unknown contacts trigger the cortex — drop
   it and preload `pairings.json` when you need a strict allowlist.
3. **Confirm the LLM wire.** Look for the startup banner's LLM probe:
   it should say `llm=ok` with the provider and model. A `llm=degraded`
   means you'll get an echo fallback, not intelligence — fix the
   provider before continuing.
4. **Smoke test from another number.** Message the linked number from
   a second phone. Expect: the cortex sends a typed reply back through
   WhatsApp within a few seconds on local gemma, tens of seconds on
   slower hardware. Watch the terminal for the `[send]` preview line.
5. **Prove memory isolation.** Tell your remote peer one durable
   fact about themselves. Run `atulya-cortex memory facts --peer
   <their-jid>` on the server. Verify the fact landed under their peer
   key and NOT under your operator key — a key privacy invariant.
6. **Optional: enable tools for remote channels.** Only if you fully
   trust every paired peer: edit `config.toml` `[tools]
   allowed_channels = ["tui", "whatsapp"]`. Otherwise leave remote
   channels tool-less — social engineering through WhatsApp is the
   most likely abuse vector.

**Output shape.** A live `atulya-cortex whatsapp start` process that
replies intelligently to at least one remote peer, with per-peer
episodes and facts accumulating on disk.

**Anti-pattern.** Do not scan the QR with your *primary* WhatsApp
device and then immediately log out of Linked Devices — you'll
invalidate the session and have to re-pair. Do not enable tools on
WhatsApp until you've audited `fine_motor_skills.py`'s safety
constraints for your own machine.
