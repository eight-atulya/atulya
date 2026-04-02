# Mental Model UI Needs Wrap-Safe Detail Panels And Multiline Query Inputs

Date: 2026-04-02
Repo: atulya
Area: control plane, mental models, UI resilience, local-model output handling

## Trigger

The mental model UI broke when a source query became long and underscore-heavy. In the detail panel, the text pushed the layout sideways instead of staying inside the panel. In the create and update dialogs, the source query field was a single-line input, which made longer queries hard to inspect and edit.

## Root Cause

The underlying issue was not just "too much text." The mental model surfaces assumed normal wrap points:

- the side detail header used a flex child without `min-w-0`
- long query and content strings did not force wrapping for unbroken tokens
- the query editor used a single-line input even though mental model prompts are often sentence- or paragraph-like

This became especially visible when local-model output or prompt text included long underscore-delimited spans with few natural break opportunities.

## Applied Fix

The control plane fix used two small, targeted UI rules:

1. make the mental model detail containers shrinkable and hide horizontal overflow
2. apply wrap-safe text styles to long query, content, and evidence fields
3. replace the source query single-line input with a compact 3-line textarea in create/update dialogs

## Practical Rule

For Atulya control-plane surfaces that show model-generated or user-authored prompt text:

- assume long unbroken tokens can appear
- add `min-w-0` anywhere long text lives inside flex layouts
- prefer `break-words` plus `overflow-wrap:anywhere` for detail panes and diff views
- use a textarea, not a one-line input, for editable prompt/query fields that may exceed a short sentence

## Validation Rule

For this class of UI change:

- run the repo lint hook
- manually sanity-check the panel and dialog behavior in the affected workflow when possible
- treat horizontal overflow in split panes as a layout bug, not as acceptable content overflow

## Expected Benefits

- long mental model queries stay inside the right-side detail panel
- copied or generated content with unusual tokenization no longer breaks the layout
- operators can read and edit source queries without fighting a one-line field
