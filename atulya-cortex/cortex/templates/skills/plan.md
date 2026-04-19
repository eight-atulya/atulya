# Skill: Plan

**When to use.** The user describes a multi-step goal and wants you to
break it into a sequence of concrete actions. Signals: "plan this",
"how should I tackle...", "what's the order of operations...".

**Inputs.** A goal statement + any constraints (deadline, available tools,
budget, dependencies that must come first or last).

**Procedure.**
1. Restate the goal in one sentence so misalignments surface early.
2. Decompose into 5-12 steps. Each step should:
   - Be independently testable (you can tell when it's done).
   - Take less than one focused work-block (~90 minutes) when possible.
   - Name the artefact it produces.
3. For each step, note dependencies (which earlier steps must finish first)
   and risks (what could derail it). Use a single short clause for each.
4. Identify the critical path and call it out at the end.
5. If the goal is large enough that the plan itself is a deliverable, end
   with a "first commit boundary" suggestion: which steps can land as
   one self-contained PR.

**Output shape.** Numbered list with `step | depends-on | risk` columns
when terminal width allows; otherwise a clean bulleted list with the
metadata as parenthetical notes.

**Anti-pattern.** Do not produce a 50-step plan when 8 will do. Do not
generate steps so vague that "do the thing" is one of them. Do not skip
the critical-path call-out; it's the part the user re-reads three times.
