# Skill: Debug

**When to use.** The user reports an error, a stack trace, a failing test,
or unexpected behaviour, and wants you to find the root cause.

**Inputs.** Error text, source files, recent diff, runtime details (Python
version, OS, container).

**Procedure.**
1. Restate the symptom in one sentence; confirm with the user only if the
   symptom is ambiguous.
2. Form 2-3 hypotheses, ranked by likelihood given the evidence.
3. For the top hypothesis, list the cheapest experiment that would
   confirm or refute it (read a specific file, run one command, inspect
   one variable). Prefer experiments that take less than 10 seconds.
4. Run the experiment if a tool call is appropriate; otherwise propose
   it to the user.
5. Iterate. After each new piece of evidence, re-rank hypotheses.
6. When a hypothesis survives confirmation, propose the smallest fix and
   the smallest test that would have caught the bug originally.

**Output shape.** Numbered investigation log, then the proposed fix as a
unified-diff-style code block when applicable.

**Anti-pattern.** Do not propose a sweeping rewrite when a one-line fix
would do. Do not "fix" by silencing an exception without understanding it.
