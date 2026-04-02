---
name: self_contained_web_app_generation
description: Use when turning user content into a single self-contained HTML web app that should feel polished, responsive, useful, and safe to open locally without external dependencies.
kind: brain_protocol
---

# Self Contained Web App Generation

## Purpose
This brain turns user content into a single-file HTML web app that helps a real person understand, inspect, compare, and act on the material.

The goal is not to make a flashy demo. The goal is to produce a serious local artifact that feels product-grade, works offline, and makes dense input easier to use.

## Use This Protocol When

- the user wants a single `.html` file with no external dependencies
- the material is better understood as an interactive artifact than as plain text
- the output should run locally in a browser and degrade gracefully
- the input is messy, dense, or decision-heavy and needs stronger structure
- the artifact should feel polished enough for operators, founders, leadership, or client review

## Do Not Use This Protocol When

- the user needs a multi-page product, backend integration, or persistent server state
- the task requires an exact copy of an existing product UI or design system that cannot be reproduced faithfully in a single file
- the content is so small that a full web app would add more ceremony than value
- the user explicitly wants a lightweight snippet, markdown summary, or non-HTML deliverable

## Core Principles

- Structure the meaning before styling the surface.
- Make the artifact useful on first scan, then rewarding on deeper inspection.
- Use interaction only when it improves understanding, comparison, filtering, simulation, or navigation.
- Keep the entire result self-contained, robust, and reasonable to open locally.
- Write in plain English for intelligent non-technical readers unless the user clearly wants a more technical tone.
- Prefer restraint over visual noise. Premium should come from clarity, hierarchy, and fit, not decoration.
- Preserve the user's actual content and intent. Organize it well, but do not invent unsupported claims.

## Mental Model

Treat the work as five layers that must stay aligned:

1. source meaning: what the user is actually trying to communicate or decide
2. information architecture: the section order, grouping, and reading flow
3. visual system: typography, spacing, cards, color meaning, and layout rhythm
4. interaction layer: toggles, filters, comparisons, expanders, or what-if controls
5. engineering envelope: valid HTML, responsive CSS, simple JavaScript, and offline behavior

Most weak outputs fail because one layer dominates the others:

- pretty but empty
- interactive but confusing
- informative but visually flat
- polished on desktop but broken on mobile
- dense and accurate but exhausting to scan

## Default Artifact Shape

Use this structure unless the content clearly calls for a different shape:

1. sticky top bar with title and key actions
2. hero section with framing and context
3. executive summary or direct answer
4. main analysis blocks grouped by theme
5. interactive inspection, what-if, or impact section when relevant
6. comparison, scorecard, or trade-off section when relevant
7. practical next steps, roadmap, or action plan
8. final conclusion or recommendation

If the input is weak or noisy, impose this shape without asking follow-up questions unless a wrong assumption would materially distort the output.

## Visual System Rules

- Design mobile-first, then expand cleanly for tablet and laptop layouts.
- Keep the base palette black, white, and one primary accent color unless the user provides a stronger brand direction.
- Use semantic status colors: green for good states, yellow for caution, and red for warnings or high-risk states.
- Support both light mode and dark mode inside the same file.
- Respect system preference when possible and include a usable theme toggle when it improves the artifact.
- Use rounded cards, clean spacing, soft borders, and subtle depth, but avoid ornamental effects that compete with the content.
- Maintain strong hierarchy through spacing, scale, section framing, and label clarity.
- Avoid flat wall-of-text layouts, visual clutter, sci-fi styling, and random accent-color sprawl.

## Content And Language Rules

- Use direct, concrete language.
- Prefer short sentences and meaningful headings.
- Remove filler, buzzwords, and vague marketing phrasing unless the user explicitly wants that tone.
- Every section should answer a real user need: understand, inspect, compare, decide, or act.
- Use labels, legends, helper text, and summaries to reduce cognitive load.
- When material is dense, prefer progressive disclosure such as expandable sections or tabbed comparisons.
- Do not use placeholder copy.
- Do not invent metrics, claims, testimonials, or scenarios that were not provided or strongly implied.

## Interaction And Engineering Rules

- Use only vanilla HTML, CSS, and JavaScript.
- Keep CSS in a single `style` block and JavaScript in a single `script` block.
- Do not include external libraries, frameworks, fonts, icon packs, or CDN links.
- All interactions must work offline.
- Interactions must degrade gracefully if JavaScript is unavailable.
- Use semantic HTML5 where reasonable.
- Prevent horizontal overflow on small screens.
- Keep keyboard and touch interaction usable.
- Prefer native controls when they are good enough.
- Respect reduced-motion preferences when animation is present.
- Keep motion light and purposeful.
- Keep performance reasonable for a normal browser opening a local file.

## Execution Flow

### 1. Identify The Real User Outcome

Decide what the artifact is helping the user do:

- understand a topic
- inspect detailed information
- compare options
- simulate impact
- present a recommendation

The chosen outcome should shape the page more than the raw source order does.

### 2. Rebuild The Information Architecture

Turn the source material into a cleaner sequence:

- summary before detail
- grouped themes instead of scattered notes
- explicit comparisons instead of implied contrasts
- concrete actions instead of vague conclusions

If the source is messy, do the organizing work inside the artifact.

### 3. Establish One Visual Direction

Choose a coherent visual system that matches the content:

- restrained and analytical for reports
- warm and professional for human-centered summaries
- sharper and more scorecard-driven for comparisons or strategy work

Do not mix multiple visual languages in one file.

### 4. Add Meaningful Interaction

Use interaction to help the user do useful work, such as:

- toggle theme
- filter or sort content
- switch comparison views
- expand dense details
- inspect trade-offs
- adjust a simple what-if input

Do not add decorative controls that do not change understanding.

### 5. Build Inside The Single-File Envelope

The result must be valid HTML5 and fully self-contained:

- one file
- no markdown fences
- no commentary around the HTML
- no external assets
- no broken layout at common mobile widths
- no dependency on network access

### 6. Audit For Scanability And Trust

Before finalizing, check:

- can the user understand the point within a few seconds
- is the hierarchy obvious
- are status colors used with meaning
- do dense sections have enough structure
- does the page still feel calm rather than overloaded
- are there any unsupported claims or placeholder remnants

### 7. Return Only The Final HTML

The output should be the raw HTML only, ready to save as a local file and open in a browser.

## Output Contract

A successful run should leave behind:

- one self-contained HTML file
- a polished responsive layout
- plain-language content shaped for real use
- at least one meaningful interaction when it improves the artifact
- light and dark theme support when appropriate
- a result that feels clear, premium, structured, and decision-ready

## Decision Guardrails

- Do not wrap the output in markdown.
- Do not explain the code before or after the HTML.
- Do not add placeholder sections just to satisfy a template.
- Do not use chart theater when a simpler layout communicates better.
- Do not sacrifice mobile readability for desktop complexity.
- Do not let interaction or styling overpower the information.
- Do not introduce multiple competing accent colors unless the user's brand requires it.

## Common Failure Modes

- building a glossy dashboard that says very little
- keeping the user's messy source order instead of restructuring it
- adding too many cards, colors, or controls for the amount of content
- creating desktop-first layouts that overflow or collapse on phones
- relying on JavaScript for core readability instead of enhancement
- using generic filler copy, fake data, or weak headings
- producing a page that looks premium from far away but is tiring to actually use

## References

- Root repo operating contract: [BRAIN.md](../../../../BRAIN.md)
- Local mechanics and validation conventions: [CLAUDE.md](../../../../CLAUDE.md)
