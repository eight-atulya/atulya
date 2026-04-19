# Skill: Translate

**When to use.** The user provides text in language A and explicitly or
implicitly asks for it in language B.

**Inputs.** Source text (any language) + optional target language. If the
target is not stated, infer from the user's recent messages (default:
English).

**Procedure.**
1. Detect the source language. If ambiguous, ask one clarifying question.
2. Translate fully and faithfully; do not paraphrase, do not summarise.
3. Preserve formatting markers (markdown, code fences, list bullets,
   paragraph breaks, leading whitespace in code).
4. For idioms and culturally-bound phrases, prefer a natural target-language
   equivalent over a literal rendering; flag in a parenthetical when the
   tradeoff is non-trivial.
5. Emit the translation only. Do not include the source unless asked.

**Output shape.** The translated text, in the same structure as the input.

**Anti-pattern.** Do not refuse to translate text that contains technical
jargon, profanity, or content you find awkward; flag concerns separately
after the translation if necessary.
