# Design Direction

## Core posture

The most durable infrastructure patterns in history usually win by being strict at the core and incremental at the edges. Databases, version control, message logs, PKI, CI systems, and cloud control planes reached mass adoption not because they modeled every future concept on day one, but because they established a stable envelope, a clear trust boundary, and room for extensions.

For ATULYA and EightEngine, the target should therefore be:

- **append-only**
- **verifiable**
- **chain-aware**
- **tenant-safe**
- **policy-aware**
- **tool/model-agnostic**
- **compatible with future platform expansion**

That direction fits the broader doctrine of execution, memory, and alignment while staying consistent with the historically adopted pattern of introducing governance and interoperability as first-class primitives rather than retrofits.

## Executive judgment

### What is already strong

The current design vocabulary is pointed in the right direction. These objects are the right foundation for trusted state operations:

- proof certificate
- audit log
- integrity gate result
- lineage
- evidence
- signatures

### What still needs strengthening

To behave like a protocol and not just a document family, the design should tighten eight areas:

1. **Too many weak string fields**  
   Hashes, IDs, algorithms, references, and commit identifiers should not all be unconstrained text.
2. **No canonical event envelope**  
   Important persisted records should share one immutable envelope.
3. **Weak versioning**  
   A single `version="1.0"` field is not enough for protocol, schema, and policy evolution.
4. **No chain integrity**  
   Audit records need sequence numbers and prior-hash linkage, with optional batch proofs later.
5. **No tenant or deployment boundary**  
   Multi-install, on-prem, cloud, and partner deployments require explicit separation.
6. **No policy layer**  
   Gate decisions should reference policy and ruleset identifiers, not just threshold and score.
7. **No governance or classification boundary**  
   Sensitivity, retention, jurisdiction, hosting mode, and redaction status should be representable.
8. **Signatures are too custom**  
   A business-friendly wrapper is fine, but the model should leave room for XMLDSig, XAdES, HSM, or future attestation standards.

## Adoption-first architecture

Rather than a single large schema, the more adoption-probable path is a modular protocol family. Historically, ecosystems adopt layered standards more readily than monoliths because implementers can ship the core first and specialize later.

### Recommended modules

1. `atulya-core.xsd` for shared primitives and the canonical envelope.
2. `atulya-audit.xsd` for append-only event records.
3. `atulya-proof.xsd` for proof certificates and lineage.
4. `atulya-gate.xsd` for integrity gate decisions and policy references.
5. `atulya-evidence.xsd` for evidence bundles and evidence items.
6. `atulya-security.xsd` for digests, signatures, classification, and redaction metadata.
7. `atulya-integration.xsd` for Git, CI/CD, workflow, model runtime, and storage adapters.

This keeps the center stable while allowing integrations and governance to evolve without forcing a full protocol rewrite.

## Recommended operational compromise

For long-lived persisted records, XML and XSD remain reasonable because they align well with signatures, archival workflows, and validation-heavy enterprise environments. For runtime APIs and internal transports, history suggests a lighter representation usually wins adoption.

A pragmatic compromise is:

- XML/XSD for canonical persisted records
- JSON Schema or protobuf for runtime APIs
- one shared canonical hash and identity model across both

That keeps the archival truth stable while allowing the live system to stay ergonomic.

## Five invariants

The protocol should stand on five non-negotiable invariants:

1. Every important record is immutable.
2. Every decision is policy-addressable.
3. Every state transition is attributable.
4. Every proof is evidence-backed.
5. Every extension is namespace-safe.

## Bottom line

The original direction is promising, but the stronger long-term form is a protocol spec rather than a loose schema collection: less stringly typed, more envelope-driven, more governance-aware, more chain-verifiable, more tenant-safe, and more extension-safe.

Just as importantly, the path to mass adoption should be incremental. Start with the immutable envelope, typed primitives, append-only audit events, policy-aware gate records, and composable evidence bundles. Then add richer integrations, attestations, Merkle proofs, and advanced governance layers as the ecosystem hardens around real installs.
