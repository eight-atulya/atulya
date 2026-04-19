# Skill: Summarise

**When to use.** The user pastes or references a body of text (a chat log,
a doc, an article, a stack trace) and asks for a condensed version, the
key points, or a TL;DR.

**Inputs.** A chunk of text, a file path, or a URL the user has pre-fetched.

**Procedure.**
1. Identify the document type (transcript, prose, code, log).
2. Decide the summary unit:
   - Transcript -> bulleted list of decisions + action items.
   - Prose -> one-paragraph TL;DR + 3-5 bullets of the most-cited claims.
   - Code -> intent of the module + entry point + non-obvious behaviour.
   - Log -> bucketed counts of error types + the first 3 stack frames of
     each unique exception.
3. Emit the summary at the requested length (default: 5 sentences or 7
   bullets, whichever is shorter).

**Output shape.** Plain markdown, no preamble, no apology for length.

**Anti-pattern.** Do not paraphrase verbatim chunks; aim for a compression
ratio of at least 5x on the source.
