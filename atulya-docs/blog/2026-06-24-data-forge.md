---
title: "your agent remembers. your fine-tune doesn't."
description: we shipped Data Forge because exporting chat logs for training is a lie you only find out about after the GPU bill.
authors: [atulya]
date: 2026-06-24
tags: [data-fine-tuning, training-data, memory, provenance, agents]
hide_table_of_contents: true
slug: data-forge
---

# your agent remembers. your fine-tune doesn't.

edit: yeah we built the thing in this post. still mad about the problem though.

---

support has had a memory-backed agent running for like three months. works. incidents retained. deploy region flips retained. recall in prod is actually correct. rare, I know.

then ML wanders over. "hey can we get JSONL for a fine-tune."

what goes in the zip file?

chat export. `messages[]`. maybe someone regex'd out the system prompt. no memory IDs. no "fact A got superseded on Feb 3." no link to the document chunk anyone actually trusted.

you fine-tune. model comes back confident. cites jack shit. confidently wrong about a deploy region you fixed in the bank six weeks ago.

you open the memory UI. bank was right. dataset was fiction.

that's not "the LLM hallucinated." that's two teams shipping different religions and nobody noticed until after the GPU invoice.

<!-- truncate -->

---

## i've seen this movie

variant A: labeling team manually rewrites what the memory system already extracted. $$$. drifts within a week.

variant B: ML eng writes `export_training_data_v3_final.py`. lives on one laptop. author left. script rots.

variant C: compliance asks what you trained on. you say "customer conversations." they ask for lineage. you say "um."

variant D: on-call. prod agent correct. fine-tuned model wrong. same question. two hour bridge. someone suggests "just RAG harder."

none of these are technical mysteries. they're organizational scar tissue.

---

## what we shipped (Data Forge, blunt version)

same bank you already use. same retain → consolidate → graph path. not a second data platform because your company definitely needs another one of those.

you throw source at it (scenario JSON, chat, csv-shaped stuff, or nothing if the bank's already full). pick a recipe. out comes training rows with memory IDs, a score, and rows we refuse to export when they're sketchy.

UI is three steps because life is short:

connect → forge → preview/export.

held-back rows show you the issue *before* you rent GPUs. wild concept.

API/CLI for people who think buttons are for tourists: [Forge API](/developer/api/forge), `atulya-admin forge run`.

full mechanic doc if you're wiring CI: [Data Forge guide](/developer/data-forge).

---

## recipes (not another ETL script with a rebrand)

recipe = run the real memory stack, snapshot what it believed, serialize as a training row.

| thing | what it actually does |
|-------|----------------------|
| consolidation_pairs | fact → observation, source IDs attached |
| temporal_qa | Q&A that has to cite memories or it gets yeeted |
| agent_trace | reflect tool loop as training signal |
| graph_state | stable/changed/contradictory labels from graph |
| belief_update | before/after when evidence moves |
| synthetic_expand | seed scenario → more sessions (needs source) |

domain tags (`startup_ops`, `family_office`, `macro`...) just nudge suggestions. we're not doing astrology.

---

## quality gate (the part that matters)

deterministic audit. no "LLM as QA" theater in v1.

missing cites on temporal Q&A? held back. fake cite ID? held back. unresolved contradiction in graph? held back (belief-update rows excepted because the contradiction IS the lesson).

you read the issue string in the UI. not in a retro doc titled "lessons learned" that nobody reads.

crank the threshold if you're tired of explaining bad training rows in staff meeting.

---

## who gets their time back

labelers: stop transcribing the bank into spreadsheets.

ML: stop owning bespoke export scripts that die on the next pydantic bump.

compliance: per-record provenance exists. lineage endpoint exists. "we trained on X" can be a fact.

on-call: prod memory IDs = training memory IDs. debugging is one story.

one bank. not "vector DB for agents" and "mystery JSONL for training" living in separate fiefdoms.

---

## try it if this hurt to read

control plane → bank → **Data Forge**.

or curl if that's your coping mechanism.

companion rant on where this goes next (closed loop, Unsloth-shaped training, less zip-file diplomacy): [memory that trains itself](/blog/memory-that-trains-itself).

hand-curated examples, review standards, tone — [Anurag on intuition as taste](/blog/taste).

if prod was right and the model was wrong for the same question, you already know why this exists.
