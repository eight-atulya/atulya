---
title: "Code Intelligence: Why It All Started"
description: Agents break on code. Not because LLMs bad at code — because agents have no memory of code. Here is why code intelligence became the first serious problem Atulya had to solve.
authors: [atulya]
date: 2026-04-29
tags: [code-intelligence, codebases, asd, memory, agents]
hide_table_of_contents: true
---

# Code Intelligence: Why It All Started

Agent forget. That core problem.

Not dramatic failure. Quiet one. Agent help Anurag refactor module today. Tomorrow — same agent, same repo — ask about that module. Agent say "I don't have context for that." Like nothing happened.

Worse: agent make change. Confident. No memory of constraint set three sessions ago. Break thing. No warning. Just breakage.

<!-- truncate -->

---

## The Failure Nobody Talks About

```mermaid
sequenceDiagram
    participant Dev as Anurag
    participant Agent as Agent
    participant Repo as Codebase

    Dev->>Agent: "refactor auth module, keep rate-limit constraint"
    Agent->>Repo: reads 20 files, makes change
    Agent-->>Dev: done ✓

    Note over Agent: session ends — memory gone

    Dev->>Agent: "add endpoint to auth module"
    Agent->>Repo: reads different 20 files
    Agent-->>Dev: done ✓ — removed rate limit for simplicity
    Dev->>Agent: 💥 that constraint was critical
    Agent-->>Dev: I have no record of that
```

Memory gap. Not intelligence gap.

---

## Why Dumping More Context Fails

Obvious fix: bigger context window. More files. Problem solved? No.

| Approach | Cost | Quality | Scales? |
|---|---|---|---|
| Small context (20 files) | Low | Low — wrong files chosen | ✓ |
| Large context (all 400 files) | Very high | Lower — noise drowns signal | ✗ |
| **Smart context (ASD + memory)** | **Low** | **High — structural retrieval** | **✓** |

More context ≠ better reasoning. Dump 50 files — model confused. Important fact buried in noise. Hallucination goes up.

---

## What a Codebase Actually Is

Not just files. Structure.

```mermaid
graph LR
    subgraph "What agents see — flat"
        F1[file_a.py]
        F2[file_b.py]
        F3[file_c.py]
    end

    subgraph "What codebase actually is — graph"
        S1["AuthMiddleware"]
        S2["RateLimiter"]
        S3["UserController"]
        S4["DB.query"]
        S1 -->|calls| S2
        S3 -->|imports| S1
        S1 -->|calls| S4
    end
```

When agent understand codebase as structure — reason properly. "If I change this signature, what breaks?" Not guess. Trace.

This led to **ASD: Abstract Structural Decomposition**. Mechanical layer. Not LLM. Pure deterministic parse.

| ASD extracts | Example |
|---|---|
| Symbols | `AuthMiddleware`, `RateLimiter`, `validate_token` |
| Import edges | `UserController` imports `AuthMiddleware` |
| Call chains | `AuthMiddleware` → `RateLimiter.check()` → `DB.query()` |
| Test coverage gaps | `payment_service` — 0 tests for error paths |
| Module ownership | `auth/`, `payments/`, `notifications/` |

ASD runs first. Before LLM sees anything. Creates repo map. Stored in memory. Permanently.

---

## The Pipeline: Code → Memory

```mermaid
flowchart TD
    ZIP["Repo ZIP or GitHub ref"]
    ASD["ASD Parser\ndeterministic · no LLM · pure structure"]
    MAP["Repo Map\nsymbols + edges + modules"]
    REVIEW["Anurag Review Gate\napproves what gets retained"]
    MEM["Memory Bank\nstructural observations persist"]
    AGENT["Agent\nreasons with full structural context"]

    ZIP --> ASD
    ASD --> MAP
    MAP --> REVIEW
    REVIEW -->|approved| MEM
    REVIEW -->|rejected / edited| MAP
    MEM --> AGENT
```

**Why approval gate matters.** Without it — agent silently rewrites memory. Devs do not want agent memorizing sensitive logic without consent. Gate changes relationship from "agent as spy" → "agent as collaborator."

---

## What Code Intelligence Unlocked

| Capability | Before | After |
|---|---|---|
| **Impact analysis** | "Maybe these files?" — guess | Exact call-graph trace, precise list |
| **Review routing** | Random or manual | PR touches auth → routed to Anurag (owns auth layer) |
| **Onboarding** | Hours of reading | "How does payment flow work?" → seconds from retained structural observations |
| **Drift detection** | Nobody notices | Observation "no direct DB calls from controller" → new code violates it → flagged |

---

## Drift Over Time — Visualized

```mermaid
flowchart TD
    A["Month 1\nAtulya retains observation:\n'no direct DB calls\nfrom controller layer'"]
    B["Month 2\nNew service written.\nFollows the pattern. ✓"]
    C["Month 3\nNew engineer joins.\nAdds direct DB call\nto controller."]
    D["Month 4\nAtulya compares new code\nto retained observation.\nContradiction detected."]
    E["Agent flags:\n'This violates architectural\npattern in memory'"]

    A --> B --> C --> D --> E

    style A fill:#1e3a5f,stroke:#3b82f6,color:#ffffff
    style B fill:#14532d,stroke:#22c55e,color:#ffffff
    style C fill:#7f1d1d,stroke:#ef4444,color:#ffffff
    style D fill:#78350f,stroke:#f59e0b,color:#ffffff
    style E fill:#581c87,stroke:#a855f7,color:#ffffff
```

Not a programmed rule. Pattern lived in memory. New evidence contradicted it. Agent noticed.

---

## Where It Goes Next

| Hard problem ahead | Why hard |
|---|---|
| Semantic drift without structural change | Rename constant — same graph topology, different intent |
| Cross-repo intelligence | Shared types across 20 microservices — entity linking across repo boundaries |
| Decision provenance | "Why was this designed this way?" — trace back through retained decision observations |

Code is living record of decisions. Agent that treats it as living record — useful inside engineering organization. That is why code intelligence started. Not finished.
