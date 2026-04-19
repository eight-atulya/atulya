# Skill: Teach The Brain About You

**When to use.** The cortex is running but treats the operator like a
stranger every session. You want to bootstrap its semantic memory so
it remembers durable facts — preferences, identity, constraints —
across restarts without waiting for dozens of passive consolidations.

**Inputs.** An open `atulya-cortex chat` session (or any wired channel)
and a short list of durable truths about the operator: role, location,
family, preferences, constraints, recurring goals.

**Procedure.**
1. **Pick durable, not ephemeral.** Durable = still true next week
   ("I'm a Python engineer in Bangalore", "my daughter is Kuhi",
   "never message me before 9am IST"). Ephemeral = today's state
   ("I'm tired", "I had coffee"). Only the first kind is worth a
   consolidation pass.
2. **Feed in 5–10 durable statements**, one per message. Prefer plain
   first-person declaratives; the consolidation prompt is tuned to
   extract from them cleanly. Interleave context so each statement
   lands as its own episode (avoid dumping a paragraph — it becomes
   one fuzzy episode).
3. **Force a sleep.** Type `/sleep force`. Expected:
   `status=ok  facts_upserted=N  episodes_consumed=M`. If you see
   `skipped_low_salience`, your statements were too bland — rephrase
   with stronger first-person framing ("I prefer X", "never Y").
4. **Verify with /facts.** Every durable statement should show up as
   a short proposition with a confidence near 1.0 and a tag
   (`preference`, `identity`, `constraint`, etc).
5. **Re-check with /episodes.** Consolidated episodes will carry a
   `✓` marker in the TUI; that's your proof the consolidation cursor
   advanced and those turns won't be re-processed next sleep.
6. **Cold-start test.** Quit the TUI. Relaunch `atulya-cortex chat`.
   Ask "what do you know about me?". The brain should answer from the
   system-prompt-injected facts block, not hallucinate from its base
   weights.

**Output shape.** `/facts` shows N high-confidence, tagged facts about
the active peer, and a cold-restarted session reflects them back
without being told again.

**Anti-pattern.** Do not feed facts about *other people* in a TUI
session owned by the operator — they will be attached to the operator's
peer key. Use a per-peer channel (WhatsApp sender, Telegram user id)
for that. Do not spam-force `/sleep` after every message; the cooldown
exists so token cost stays bounded on small local models.
