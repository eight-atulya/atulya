# Skill: Force Sleep And Inspect What The Brain Learned

**When to use.** A conversation just happened and you want to know —
right now, deterministically — which durable facts the cortex will
carry forward from it. Also useful as the "show me it's actually
learning" demo for a skeptical observer.

**Inputs.** A live cortex session with at least 3–4 recent turns in
any one peer's history. Either the TUI (use the slash commands) or a
shell on the server (use the `memory` subcommand family).

**Procedure.**
1. **See what raw material is there.** In the TUI run `/episodes`. You
   want at least a few rows with a non-zero `s=` (salience) marker; if
   everything is `s=0.02` the consolidation will skip with
   `low_salience` and nothing will get learned. Rephrase a few turns
   with stronger first-person content if needed.
2. **Peek at the affect scorer.** `/affect I'm furious about this
   bug!` — confirms the amygdala is live. Valence should be clearly
   negative, arousal > 0.3, salience above the consolidation floor
   (default 0.6 aggregate across a batch).
3. **Force consolidation.** `/sleep force`. The `force` flag bypasses
   the cooldown, the min-episode count, and the min-salience gate —
   useful for on-demand inspection. Expect `status=ok` and a
   `facts_upserted` count; `episodes_consumed` shows how many episodes
   the cursor advanced past.
4. **Inspect the result.** `/facts`. Each row is one durable belief
   with its confidence, tags, and last-updated date. Rows at 1.00
   confidence are the freshest extractions; lower-confidence rows are
   older or less-reinforced.
5. **Trace facts back to evidence.** Shell-side (outside the TUI):
   `ls ~/.atulya/cortex/facts/` → one JSONL per peer. Each fact
   carries `source_episodes` — a list of episode ids you can grep
   out of `~/.atulya/cortex/episodes/<channel>/<peer>.jsonl`. This
   is the audit trail: every fact points back to the exact turns
   that produced it.
6. **Observe the cursor.** `cat ~/.atulya/cortex/state/consolidation.json`.
   You'll see one entry per `(channel, peer)` with the last-consumed
   timestamp. The next `/sleep` will start strictly after this point,
   so episodes already learned don't cost tokens again.

**Output shape.** A `/facts` block with at least one high-confidence
durable fact, and a clear audit trail from fact → source episodes →
raw conversation.

**Anti-pattern.** Do not run `/sleep force` in a loop expecting the
fact count to climb — once episodes are marked `consolidated=True`
they are skipped on the next pass. Do not delete
`state/consolidation.json` to "force a re-learn"; instead call
`FactStore.forget(...)` on the specific fact you want re-derived so
you don't accidentally reintroduce contradictions.
