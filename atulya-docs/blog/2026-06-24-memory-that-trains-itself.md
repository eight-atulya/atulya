---
title: "memory that trains itself"
description: forge exports rows from the bank. the part after that is eval fails, you retain the fix, you forge again, and maybe your model stops arguing with ops.
authors: [atulya]
date: 2026-06-24
tags: [data-forge, unsloth, continual-learning, brain, roadmap]
hide_table_of_contents: true
slug: memory-that-trains-itself
---

# memory that trains itself

edit: roadmap post. not a keynote. if you want the "we shipped it today" thread that's [here](/blog/data-forge).

---

Atulya started as memory infra. retain, recall, reflect, graph, Brain sniffing integrity stuff. fine when the agent is the product.

then every company hired "the fine-tune guy" and bought one A100 and a dream.

now you have two brains:

memory bank updates every time someone retains a ticket. model weights frozen at `training_data_march_v7_REAL_FINAL.jsonl`.

they drift. nobody owns the gap. ML owns the checkpoint. platform owns the bank. they meet quarterly and disagree politely.

someone asks in a review: "why does the model say eu-west when the agent literally has us-east in memory."

awkward silence. someone says "temperature." meeting ends. nothing changes.

[Data Forge](/blog/data-forge) is the export half of fixing that. this post is the other half.

<!-- truncate -->

---

## export is necessary. export is not sufficient.

pattern i keep seeing:

inference team does RAG. model never internalizes structure. just borrows context and hopes.

training team fine-tunes on logs once. dataset ossifies. memory keeps moving.

evals run in a notebook. failures get screenshot'd to Slack. die there.

new weights ship. old bank. two truths. custody battle forever.

smart DB + dumb model. or smart model that doesn't trust the DB. pick your fighter.

---

## the loop (not revolutionary, just adult)

text in → memory structured → forge makes ATR rows → train → eval the stuff that actually matters:

did it cite real memory IDs. did time make sense. did it walk into an unresolved contradiction with confidence?

fail → that's a retain, not a Jira epic. correction goes in the bank. re-forge. train again.

dataset isn't a tombstone. source of truth isn't a CSV on Brad's laptop.

revolutionary part is making that one pipeline instead of three teams and a shared drive.

---

## ATR vs chat JSONL (why we didn't just dump messages)

chat JSONL teaches vibe. sometimes that's all you want.

it does not teach "ground every claim in evidence you can point at."

ATR is boring on purpose: timeline, fact/obs snapshots, cited IDs, quality issues, forge job lineage. attic you keep.

OpenAI exporter? adapter. graph FT exporter? adapter. whatever Unsloth wants when you read this? adapter.

formats are fashion. provenance shouldn't be.

[schema nerd doc](/developer/data-forge) if you care.

---

## Unsloth (yes, specifically)

not cos twitter said so. cos half of you are fine-tuning 7B on a GPU under a desk and your pipeline is currently:

current path: export zip → slack ML → wait → wrong format → export again → cry.

want: forge job finishes → training job starts → same bank before/after. no human router.

not shipped. saying it loud so you don't build the cursed version in a corner and we have to migrate you in 2027.

---

## Brain angle (for people who care about org-level learning)

Brain already watched influence and integrity in the bank.

Forge adds labeled outcomes with evidence IDs attached.

which memories keep showing up in exportable rows. which facts always land held-back. did citation pass rate move after the last fine-tune or did you just burn money.

that's the org getting less wrong. not "wow the agent remembered the session."

---

## rules we're actually trying to follow

1. bad row? you see it before export. not after three epochs.
2. bank changed? re-forge. memory repos help version that. more coming.
3. eval failure → retain. manual first. automate when we're not lying about it.
4. prod recall IDs = training export IDs. if not, something's lying and it's probably process.

memory isn't a sidecar you bolt on after the model ships. it's the path from evidence to weights.

---

## links

[Data Forge guide](/developer/data-forge) — tables, API shapes, all of it.

[Taste Studio guide](/developer/taste-studio) — curate judgment, not just memory.

[release post](/blog/data-forge) — the war story version.

[taste — intuition is taste](/blog/taste) — Anurag Atulya on the founder moat.

[Forge API](/developer/api/forge) — for CI masochists.

Forge is live. closed-loop retain + on-stack training is next. building in public cos the alternative is another black-box dataset pipeline and i've sat in those retros.
