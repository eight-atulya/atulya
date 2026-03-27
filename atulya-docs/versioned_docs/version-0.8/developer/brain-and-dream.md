---
sidebar_position: 6
---

# Brain and Dream

Atulya `0.8` adds a new layer on top of normal memory retrieval.

The simplest way to think about it:

- **Memory** stores what happened.
- **Brain** watches patterns in that memory.
- **Remote brain learning** lets one bank learn from another bank.
- **Dream** turns a pile of memory into higher-level takeaways in the background.

None of this is required to use Atulya. Your app can still just `retain`, `recall`, and `reflect`.
These features are for teams that want Atulya to become more adaptive over time.

## The Big Picture

```mermaid
graph LR
    A["Your app writes memories"] --> B["Atulya memory bank"]
    B --> C["Brain runtime learns activity and influence patterns"]
    B --> D["Dream runs create summaries and synthesized takeaways"]
    E["Remote Atulya bank"] --> F["Brain learn pulls selected knowledge"]
    F --> B
    C --> G["Control plane analytics"]
    D --> G
```

## What Each Part Does

### Brain

The **brain runtime** is Atulya's background learning layer for a bank.

It does things like:

- refresh a bank-specific brain cache
- learn which hours a bank is usually active
- calculate which memories, chunks, or mental models are currently most influential

This is useful when you want Atulya to do more than simple retrieval. It helps the system understand which knowledge is "hot", which patterns are recurring, and when a bank is likely to be active again.

### Remote Brain Learning

**Remote brain learning** lets one Atulya bank learn from another Atulya bank.

In plain terms:

- Bank A connects to Bank B
- Atulya reads Bank B's learned knowledge
- Atulya distills the useful parts into Bank A

This is helpful when you want a new bank to start with lessons from an older bank, or when you want one environment to absorb knowledge from another without copying everything manually.

### Dream

**Dream** is a background synthesis job.

It takes what the bank already knows and produces a higher-level artifact. Instead of just listing raw memories, Dream tries to answer:

- what themes keep repeating?
- what assumptions seem true?
- what changed recently?
- what might matter next?

Dream runs do not block your app's normal retain, recall, or reflect requests.

## How They Work Together

```mermaid
flowchart LR
    R["retain creates memories"] --> O["consolidation updates observations"]
    O --> S["sub-routine refreshes brain cache"]
    O --> D["dream can be triggered by events or schedule"]
    X["remote bank"] --> L["brain learn imports distilled knowledge"]
    L --> S
    S --> I["brain influence analytics"]
    D --> A["dream artifacts"]
```

## Automatic vs Manual

| Feature | Automatic? | Typical use |
|---|---|---|
| **sub-routine** | Can run on startup or be triggered manually | Refresh brain cache and activity predictions |
| **brain learn** | Manual | Learn from a remote Atulya bank |
| **dream generation** | Manual or scheduled | Produce synthesized artifacts from the bank's knowledge |
| **brain influence** | Query-time analytics | Show what knowledge is most active or important |

## Why This Matters

Without these features, Atulya is already a strong memory system.

With them, Atulya becomes more like a living system that can:

- notice usage patterns
- build analytics for the control plane
- transfer learning between banks
- generate richer, more human-friendly summaries in the background

## Useful Endpoints

### Brain runtime and analytics

- `POST /v1/default/banks/{bank_id}/sub-routine`
- `GET /v1/default/banks/{bank_id}/sub-routine/predictions`
- `GET /v1/default/banks/{bank_id}/sub-routine/histogram`
- `GET /v1/default/banks/{bank_id}/brain/status`
- `GET /v1/default/banks/{bank_id}/brain/influence`

### Remote brain learning

- `POST /v1/default/banks/{bank_id}/brain/learn`

### Dream

- `POST /v1/default/banks/{bank_id}/dreams/trigger`
- `GET /v1/default/banks/{bank_id}/dreams`
- `GET /v1/default/banks/{bank_id}/dreams/stats`

## Minimal Mental Model

If you only remember one thing, remember this:

- **Brain** helps Atulya learn patterns from a bank.
- **Remote brain learning** helps one bank absorb lessons from another bank.
- **Dream** helps Atulya turn many memories into a smaller set of useful takeaways.

## Configuration Pointers

Most Dream settings live under the bank's `dream` config object.

Important knobs include:

- whether Dream is enabled
- whether it runs on events, on a schedule, or both
- how often it can run
- how much input and output it is allowed to use
- whether output should stay extra plain-language with `enforce_layman`

For the raw settings list, see [Configuration](./configuration#dreamtrance-bank-config).

## Where To Look Next

- [**Operations**](./api/operations) for background job behavior
- [**Services**](./services) for where these jobs run
- [**Configuration**](./configuration#dreamtrance-bank-config) for Dream settings

