# Record Model

## Canonical record envelope

Every persisted protocol record should inherit from one immutable envelope, including:

- `AuditEvent`
- `ProofCertificate`
- `IntegrityGateRecord`
- `EvidenceBundle`
- `StatePropagationRecord`
- `DriftRecord`
- `RepairRequestRecord`
- `AttestationRecord`

### Core envelope fields

- `protocolVersion`
- `schemaVersion`
- `recordId`
- `recordType`
- `tenantId`
- `installationId`
- `environment`
- `issuedAt`
- `sequenceNumber`
- `previousRecordHash`
- `payloadHash`
- `canonicalizationMethod`
- `retentionClass`
- `classification`
- `producer`
- `correlationId`
- `causationId`

A representative shape:

```xml
<xs:complexType name="RecordEnvelopeType">
  <xs:sequence>
    <xs:element name="protocolVersion" type="core:SemVerType"/>
    <xs:element name="schemaVersion" type="core:SemVerType"/>
    <xs:element name="recordType" type="core:RecordTypeEnum"/>
    <xs:element name="recordId" type="core:UuidType"/>
    <xs:element name="tenantId" type="core:IdentifierType"/>
    <xs:element name="installationId" type="core:IdentifierType"/>
    <xs:element name="environment" type="core:EnvironmentEnum"/>
    <xs:element name="issuedAt" type="xs:dateTime"/>
    <xs:element name="sequenceNumber" type="xs:positiveInteger"/>
    <xs:element name="correlationId" type="core:IdentifierType" minOccurs="0"/>
    <xs:element name="causationId" type="core:IdentifierType" minOccurs="0"/>
    <xs:element name="previousRecordHash" type="core:DigestValueType" minOccurs="0"/>
    <xs:element name="payloadHash" type="core:DigestValueType"/>
    <xs:element name="canonicalizationMethod" type="core:CanonicalizationMethodEnum"/>
    <xs:element name="classification" type="core:ClassificationType"/>
    <xs:element name="retention" type="core:RetentionType"/>
    <xs:element name="producer" type="core:ProducerType"/>
  </xs:sequence>
</xs:complexType>
```

## Strong primitive types

Historically durable protocols reduce ambiguity early. Replace generic strings with typed primitives for UUIDs, digests, URIs, semantic versions, and algorithm declarations.

```xml
<xs:simpleType name="UuidType">
  <xs:restriction base="xs:string">
    <xs:pattern value="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"/>
  </xs:restriction>
</xs:simpleType>

<xs:simpleType name="SemVerType">
  <xs:restriction base="xs:string">
    <xs:pattern value="[0-9]+\.[0-9]+\.[0-9]+"/>
  </xs:restriction>
</xs:simpleType>

<xs:complexType name="DigestValueType">
  <xs:simpleContent>
    <xs:extension base="xs:string">
      <xs:attribute name="algorithm" type="core:DigestAlgorithmEnum" use="required"/>
      <xs:attribute name="encoding" type="core:EncodingEnum" use="required"/>
    </xs:extension>
  </xs:simpleContent>
</xs:complexType>
```

## First-class actor model

Attribution should cover humans, services, workflows, and AI systems without collapsing them into a single string field.

```xml
<xs:complexType name="ActorType">
  <xs:sequence>
    <xs:element name="actorId" type="core:IdentifierType"/>
    <xs:element name="actorKind" type="core:ActorKindEnum"/>
    <xs:element name="displayName" type="xs:string" minOccurs="0"/>
    <xs:element name="organizationId" type="core:IdentifierType" minOccurs="0"/>
    <xs:element name="serviceAccount" type="xs:boolean" minOccurs="0"/>
    <xs:element name="modelInfo" type="core:ModelInfoType" minOccurs="0"/>
    <xs:element name="humanReview" type="core:HumanReviewType" minOccurs="0"/>
  </xs:sequence>
</xs:complexType>
```

Recommended `ActorKindEnum` values:

- `human`
- `ai_agent`
- `system`
- `service_account`
- `workflow`
- `hybrid_council`

## Policy-aware integrity gates

Historically adopted control systems separate execution from policy. Gate results should therefore reference policy state directly.

```xml
<xs:complexType name="IntegrityGateResultType">
  <xs:sequence>
    <xs:element name="decision" type="gate:GateDecisionEnum"/>
    <xs:element name="decisionMode" type="gate:DecisionModeEnum"/>
    <xs:element name="evaluatedAt" type="xs:dateTime"/>
    <xs:element name="policyRef" type="gate:PolicyRefType"/>
    <xs:element name="scorecard" type="gate:ScorecardType"/>
    <xs:element name="failedControls" type="gate:FailedControlsType" minOccurs="0"/>
    <xs:element name="quarantine" type="gate:QuarantineType" minOccurs="0"/>
    <xs:element name="remediation" type="gate:RemediationType" minOccurs="0"/>
    <xs:element name="reviewRequirement" type="gate:ReviewRequirementType" minOccurs="0"/>
    <xs:element name="reason" type="xs:string" minOccurs="0"/>
  </xs:sequence>
</xs:complexType>
```

The essential fields are:

- `policyId`
- `policyVersion`
- `ruleSetId`
- `decisionMode`
- `evaluatedControls`
- `failedControls`
- `reviewRequirement`
- `quarantineScope`
- `remediationHint`

## Append-only, chain-linked audit events

Logs become trustworthy when each event can be independently verified and linked to its predecessor.

```xml
<xs:complexType name="AuditEventType">
  <xs:sequence>
    <xs:element name="envelope" type="core:RecordEnvelopeType"/>
    <xs:element name="eventName" type="audit:EventNameEnum"/>
    <xs:element name="eventCategory" type="audit:EventCategoryEnum"/>
    <xs:element name="actor" type="core:ActorType"/>
    <xs:element name="target" type="audit:TargetRefType"/>
    <xs:element name="action" type="audit:ActionType"/>
    <xs:element name="result" type="audit:ResultType"/>
    <xs:element name="policyContext" type="audit:PolicyContextType" minOccurs="0"/>
    <xs:element name="evidenceRefs" type="audit:EvidenceRefsType" minOccurs="0"/>
    <xs:element name="certificateRef" type="core:IdentifierType" minOccurs="0"/>
    <xs:element name="extensions" type="core:ExtensionsType" minOccurs="0"/>
  </xs:sequence>
</xs:complexType>
```

A pragmatic mass-adoption path is to require sequence number plus previous-hash first, while leaving Merkle batching and transparency-log publication as optional higher-order capabilities.

## Record families worth standardizing

The following records materially improve operational completeness without overdesign:

- `StatePropagationRecord`
- `DriftRecord`
- `RepairRequestRecord`
- `PolicyDecisionRecord`
- `RedactionRecord`
- `AttestationRecord`

These map closely to how production systems actually mature: propagation, detection, repair, governance, privacy, and acceptance.

## Composable evidence bundles

Instead of hardcoding a fixed evidence checklist, use a bundle plus typed evidence items.

```xml
<xs:complexType name="EvidenceBundleType">
  <xs:sequence>
    <xs:element name="summary" type="evidence:EvidenceSummaryType"/>
    <xs:element name="items" type="evidence:EvidenceItemsType"/>
  </xs:sequence>
</xs:complexType>

<xs:complexType name="EvidenceItemType">
  <xs:sequence>
    <xs:element name="kind" type="evidence:EvidenceKindEnum"/>
    <xs:element name="source" type="evidence:EvidenceSourceType"/>
    <xs:element name="generatedAt" type="xs:dateTime"/>
    <xs:element name="digest" type="core:DigestValueType"/>
    <xs:element name="location" type="core:UriType" minOccurs="0"/>
    <xs:element name="payload" type="xs:anyType" minOccurs="0"/>
  </xs:sequence>
  <xs:attribute name="id" type="core:UuidType" use="required"/>
</xs:complexType>
```

Recommended `EvidenceKindEnum` values:

- `unit_test`
- `integration_test`
- `regression_test`
- `lint`
- `typecheck`
- `semantic_analysis`
- `risk_assessment`
- `benchmark`
- `diff_analysis`
- `human_review_note`
- `runtime_trace`
- `policy_evaluation`
- `external_attestation`

## Signature model with standards headroom

Custom business wrappers are useful, but the structure should not block future standards adoption.

```xml
<xs:complexType name="SignatureContainerType">
  <xs:sequence>
    <xs:element name="signerRef" type="core:IdentifierType"/>
    <xs:element name="role" type="security:SignatureRoleEnum"/>
    <xs:element name="algorithm" type="security:SignatureMethodEnum"/>
    <xs:element name="signedAt" type="xs:dateTime"/>
    <xs:element name="keyRef" type="core:IdentifierType" minOccurs="0"/>
    <xs:element name="certificateRef" type="core:IdentifierType" minOccurs="0"/>
    <xs:element name="signatureValue" type="xs:base64Binary"/>
    <xs:element name="detachedObjectDigest" type="core:DigestValueType"/>
    <xs:any namespace="##other" minOccurs="0" maxOccurs="unbounded" processContents="lax"/>
  </xs:sequence>
</xs:complexType>
```

That wildcard is important because interoperability usually arrives through extensions before it arrives through full consolidation.

## Extension and integration strategy

The best long-lived standards allow simple metadata and structured foreign namespaces at the same time.

```xml
<xs:complexType name="ExtensionsType">
  <xs:sequence>
    <xs:element name="property" type="core:PropertyType" minOccurs="0" maxOccurs="unbounded"/>
    <xs:any namespace="##other" minOccurs="0" maxOccurs="unbounded" processContents="lax"/>
  </xs:sequence>
</xs:complexType>
```

For external systems, normalize adapters around a generic integration reference:

```xml
<xs:complexType name="IntegrationRefType">
  <xs:sequence>
    <xs:element name="system" type="integration:SystemEnum"/>
    <xs:element name="objectType" type="xs:string"/>
    <xs:element name="objectId" type="xs:string"/>
    <xs:element name="uri" type="core:UriType" minOccurs="0"/>
    <xs:element name="digest" type="core:DigestValueType" minOccurs="0"/>
    <xs:element name="snapshot" type="xs:anyType" minOccurs="0"/>
  </xs:sequence>
</xs:complexType>
```

That pattern is more likely to survive market shifts than bespoke one-off connector schemas.

## Governance fields to standardize early

Enterprise systems that last generally standardize governance fields before customer edge cases force them in. Recommended baseline fields include:

- classification: `public`, `internal`, `confidential`, `restricted`, `secret`
- retention: `ephemeral`, `standard`, `regulated`, `legal_hold`, `permanent`
- jurisdiction metadata for residency and legal domain
- deployment mode: `cloud_shared`, `cloud_dedicated`, `on_prem`, `air_gapped`, `hybrid`
- redaction status: `none`, `partial`, `tokenized`, `sealed`

## Event taxonomy

Splitting event names by operating category usually improves both analytics and interoperability.

### Lifecycle

- `intent_received`
- `scope_resolved`
- `state_loaded`
- `change_proposed`
- `verification_started`
- `verification_completed`
- `gate_evaluated`
- `certificate_issued`
- `propagation_started`
- `propagation_completed`

### Risk and anomaly

- `drift_detected`
- `conflict_detected`
- `quarantine_triggered`
- `policy_violation`
- `evidence_missing`
- `tamper_suspected`

### Repair and recovery

- `repair_requested`
- `rollback_started`
- `rollback_completed`
- `replay_started`
- `replay_completed`
- `human_review_requested`
- `human_review_completed`

### Governance

- `retention_applied`
- `redaction_applied`
- `policy_updated`
- `delegation_changed`
- `attestation_recorded`

## Versioning strategy

A durable protocol should separate three kinds of versioning:

1. **Protocol version** for the meaning of the record family.
2. **Schema version** for the exact XSD contract.
3. **Policy version** for the governance logic applied during evaluation.

This avoids forcing schema breaks when only policy changes, and avoids forcing protocol resets when only schema syntax evolves.

## Canonical root records

A clean canonical set of XML roots would be:

```xml
<AuditEvent/>
<ProofCertificate/>
<IntegrityGateRecord/>
<EvidenceBundle/>
<StatePropagationRecord/>
<DriftRecord/>
<RepairRequestRecord/>
<AttestationRecord/>
```

That distinction matters because logs are a storage or presentation concept, while events are the protocol concept.

## Proof certificate direction

A stronger proof certificate shape would look like this:

```xml
<xs:complexType name="ProofCertificateType">
  <xs:sequence>
    <xs:element name="envelope" type="core:RecordEnvelopeType"/>
    <xs:element name="intent" type="proof:IntentType"/>
    <xs:element name="scope" type="proof:ScopeType"/>
    <xs:element name="verification" type="proof:VerificationType"/>
    <xs:element name="lineage" type="proof:LineageType"/>
    <xs:element name="evidence" type="evidence:EvidenceBundleType"/>
    <xs:element name="attestations" type="proof:AttestationsType" minOccurs="0"/>
    <xs:element name="signatures" type="security:SignaturesType"/>
    <xs:element name="extensions" type="core:ExtensionsType" minOccurs="0"/>
  </xs:sequence>
</xs:complexType>
```

Additional semantic upgrades worth standardizing:

- lineage should support `parentRecordId`, `rootRecordId`, `branchId`, `generation`, `replayOf`, `supersedes`, and `supersededBy`
- scope should support logical and physical boundaries such as tenant, workspace, repository, service, component, runtime, and data partition
- confidence should be structured with score, scale, method, and calibration state rather than a naked decimal
