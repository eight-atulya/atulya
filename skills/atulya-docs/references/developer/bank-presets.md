
# Bank presets (memory starter kits)

When you **create or update** a bank, you can pass **`bank_preset`** on the same request body as other **CreateBankRequest** fields (OpenAPI: `PUT` / `PATCH` `/v1/default/banks/{bank_id}`; see also [Memory banks](/developer/api/memory-banks)).

Presets are **curated defaults** that:

1. **Merge into bank config** before any explicit fields you send (explicit fields override the preset).
2. **Optionally seed** operator-facing content (pinned mental models and one directive) for specific presets.

They exist so teams do not have to hand-copy retain/reflect/observation tuning for common workflows (for example **repository + Codebases**).

## Supported values

| `bank_preset` | Behavior |
|---------------|----------|
| *(unset)* | No preset merge; only fields you send apply. |
| `codebase` | Applies repository-oriented retain/reflect/observation settings and idempotently seeds developer guides. |

Unknown strings are ignored (no error), so clients can safely forward user-selected labels.

## `codebase` preset

### Configuration merged

The preset sets (unless overridden by your request):

- **`retain_extraction_mode`** → `custom`, with **`retain_custom_instructions`** focused on technical facts from code chunks (paths, symbols, contracts, risk).
- **`retain_mission`, `reflect_mission`, `observations_mission`** — short missions aligned with evidence-backed engineering memory.
- **`enable_observations`** → `true` so cross-file themes can consolidate after retain.

Implementation lives in `atulya_api/bank_presets.py` (`BANK_PRESET_CONFIG`).

### Seeded content (idempotent)

On **`PUT` or `PATCH`** when `bank_preset` is `codebase`, the API runs **seed** logic once per logical artifact:

- **One directive** — evidence-first answering (path/line provenance; no inventing structure when memory is thin). Skipped if a directive with the same **name** already exists for the bank.
- **Three pinned mental models** — short Markdown guides: review → memory workflow, how to read code-backed memories, operating tips. Each uses a **stable id** per guide; if that id already exists for the bank, the insert is skipped (concurrent-safe).

Tags include `preset:codebase` so you can filter or delete starter content later.

Seeding failures are **non-fatal** (bank creation still succeeds); check server logs if guides are missing.

### Control Plane

On the **Dashboard** quick-start flow, **Memory starter kit** lets you choose **Code repository** (sends `bank_preset: "codebase"` on bank create). The Control Plane `POST /api/banks` forwards the JSON body to the API (including `bank_preset`).

## API example

```bash
curl -X PUT "http://localhost:8000/v1/default/banks/my-codebase-bank" \
  -H "Content-Type: application/json" \
  -d '{"bank_preset": "codebase"}'
```

Combine with explicit overrides in the same body; explicit keys win over the preset.

## When *not* to use a preset

- You already maintain bank config in code or Terraform and want full control — omit `bank_preset` and set fields explicitly.
- You need a minimal bank for tests — use default creation without a preset.

---

## Roadmap (future improvements)

This area is intentionally small and data-driven. Likely next steps:

- **More presets** — e.g. docs-first, incident response, or “customer CRM” kits with different retain/reflect defaults.
- **Preset versioning** — pin `bank_preset` to a version string when behavior changes so existing banks stay reproducible.
- **Control Plane editing** — pick a preset, then tweak fields in UI before save, with a diff preview against the preset base.
- **CLI parity** — `atulya bank create` flags mirroring `bank_preset`.
- **Optional LLM refresh** — after the first successful codebase import, **optionally** refresh a guide mental model via reflect (today seeds are static Markdown + embeddings only, no async reflect jobs at signup).

If you extend presets in code, keep the **single source of truth** in `bank_presets.py`, regenerate OpenAPI + clients, and update this page.
