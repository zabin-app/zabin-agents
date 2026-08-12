# Portable Agent Contracts - Architecture

## Overview

This repository defines a host-neutral workflow contract for software-engineering agents backed by Zabin. Versioned role prompts, capability tiers, MCP policy, adapters, recovery checkpoints, and conformance evidence let supported clients execute the same workflow without making a client, provider, or concrete model part of the portable core.

Zabin owns durable workflow state. Filesystem checkpoints retain only the recovery evidence that cannot be reconstructed safely from that state; they never become an alternate authority.

## Component Structure

| Component | Responsibility |
| --- | --- |
| Portable roles (`agents/`, `config/agents.json`) | Define role behavior, closed input/output contracts, semantic capabilities, mutation scope, timeouts, and failure policy. |
| Workflow skills (`skills/`) | Compose roles and semantic host capabilities into research, planning, implementation, review, documentation, and recovery programs. |
| Capability policy (`config/model-tiers.json`) | Selects provider-neutral `fast`, `balanced`, and `deep` capability classes; the host resolves each class to a runtime model. |
| MCP policy (`config/zabin-mcp.json`) | Defines the two Zabin surfaces, canonical tool inventory, identities, transport, credentials, risk classes, and approval requirements. |
| Contract schemas (`schemas/`) | Close and version the role registry, capability tiers, MCP policy, and recovery checkpoint formats. |
| Client adapters (`adapters/`, rendering and installation scripts) | Translate canonical policy into native configuration, conditionally gate client support through compatibility locks, and synchronize prompts and skills without weakening allowlists or approval semantics. |
| Diagnostics and conformance (`scripts/zabin_doctor.py`, `scripts/run_conformance.py`, `tests/conformance/`) | Check static contract coherence and, when explicitly enabled, verify live identity, authorization boundaries, native-host behavior, lifecycle evidence, and pinned protocol conformance. |
| Recovery checkpoints (`scripts/recovery_checkpoint.py`) | Store redacted, closed-schema recovery snapshots atomically and compare them with Zabin state. |

Claude Code and Codex are supported adapter targets. Goose 1.45.0 and PI remain unsupported and fail closed. Their compatibility locks and conformance evidence preserve the audited boundary, while rendering and installation keep active native configuration disabled. See the [Goose compatibility decision](../adapters/goose/COMPATIBILITY.md) and [conformance contract](../tests/conformance/README.md).

## Layer Dependencies

Dependencies point from host-specific and operational layers toward the portable contracts:

```text
agent prompts and workflow skills
              |
              v
role registry + capability tiers + MCP policy
              |
              v
       versioned JSON schemas

supported host -> rendered adapter -> Zabin MCP surfaces
                                      |
                                      v
                            authoritative workflow state
                                      |
                                      v
                          recovery comparison/checkpoint
```

- Prompts name registered semantic capabilities and role contracts, not host-specific dispatch APIs.
- Adapter rendering depends on canonical policy, schemas, and any conditional client compatibility lock. Policy never depends on rendered client files, and a failed support gate can produce only inert output.
- Installation consumes rendered configuration and portable assets. It does not redefine role, MCP, or approval policy.
- Diagnostics and conformance observe the same canonical contracts; they do not create a competing runtime policy.
- Recovery code may read authoritative Zabin state and local checkpoints, but it never promotes a checkpoint over Zabin or mutates authoritative state during reconciliation.

## MCP Surfaces and Authority

| Surface | Purpose | Mutation boundary |
| --- | --- | --- |
| Conductor | Project, plan, task-ledger, review, graph, attachment, and human-decision coordination. | Read operations can be automatic; durable changes prompt; destructive and selected human-interaction operations require a human gate. |
| Worker | A leased task's reads, attachments, progress, commits, worktree state, status, summary, and release operations. | Read operations can be automatic and task-scoped writes require granted scope; durable, destructive, and human-interaction operations are absent or denied. |

Canonical public tool names belong to the policy. Each adapter owns any client-side qualification needed to address a surface, so portable prompts never persist transport-qualified names. Both surfaces use separate bearer credentials and loopback Streamable HTTP endpoints. Exact service, surface, protocol, version, and inventory identity are part of the boundary; loopback location alone is not identity.

Zabin records the authoritative project, plan, phase, wave, task, gate, verdict, action-item, attachment, and commit state. A checkpoint is keyed to the complete workflow identity and source revision and carries content-addressed evidence for gaps such as full research/review payloads, gate snapshots, completion evidence, action-item resolutions, and commit mappings. Reconciliation reads Zabin first. Divergence is a conflict to report, never permission to overwrite either side.

## Trust Boundaries

| Boundary | Architectural rule |
| --- | --- |
| Canonical checkout | Versioned prompts, schemas, policy, templates, and locks are the generation inputs. Rendering and installation reject malformed, incomplete, substituted, or drifting inputs. |
| Adapter installation | Destinations and the canonical checkout must be locally trusted during synchronization. The installer records ownership and separate workspace-trust, server-approval, and activation states; file presence is not proof of any of them. Conditional targets cannot acquire active ownership while their support lock fails. |
| Credentials | Configuration binds credential names or runtime interpolation, never bearer values. Conductor and worker credentials are independent and must not be accepted across surfaces. |
| MCP transport | Clients authenticate before use; diagnostics compare the live surface and inventory with canonical policy. Authentication, identity, filtering, and approval all have to hold. |
| Native clients | Supported clients must prove configuration source, trust/approval, activation, exact enumeration, allowed dispatch, forbidden non-receipt, missing-secret containment, and cleanup through external observation. Goose observations additionally run under an explicit disposable `GOOSE_PATH_ROOT`; that state isolation is neither workspace/recipe trust nor a process sandbox. |
| Recovery storage | Checkpoints contain redacted evidence, use restrictive permissions and atomic replacement, and remain non-authoritative. |
| Third-party adapters | Unsupported clients are not enabled on partial evidence. Goose and PI remain outside the supported boundary. |

## Data Flow

### Contract generation and installation

```text
schemas + canonical policy + templates
                   |
                   v
       validate and render in memory
                   |
                   v
 deterministic client artifacts
                   |
                   v
 merge/synchronize with ownership manifest
                   |
                   v
 supported host loads native configuration
```

Rendering produces deterministic native configuration from the portable policy. Installation preserves unmanaged native configuration and tracks its owned components separately.

### Workflow execution and recovery

```text
workflow skill -> registered role -> semantic host capability
                                      |
                                      v
                     conductor or leased worker surface
                                      |
                                      v
                         authoritative Zabin records
                                      |
                   content-addressed recovery evidence
                                      |
                                      v
                       redacted local checkpoint
```

Diagnostics and conformance are observation paths around this flow; their reports are evidence, not workflow state.

## Key Interfaces

| Interface | Minimal contract |
| --- | --- |
| Agent role | Role id and prompt source plus capability tier, mutation scope, required semantic tools, closed input/output schemas, timeout, failure policy, and adapter requirements. |
| Capability tier | Provider-neutral capabilities, task complexity, context/parallelism limits, mutation support, verification requirement, and selection criteria. |
| MCP server policy | Surface identity and transport, credential binding, approval policy, canonical tools with risk/mutation metadata, and per-client adapter requirements. |
| Recovery checkpoint | Versioned identity key, source revision, payload/evidence references, verdict and gate snapshots, action-item resolutions, commit mappings, and retirement records. |
| Diagnostic report | Mode and aggregate status, credential availability metadata, and named checks; values remain secret-free. |
| Conformance report | Pinned startup evidence plus required static, native-host, lifecycle, and per-surface results; skipped, unscored, stale, or expected-failure evidence cannot yield a full pass. |

Operational commands and credential setup live in [DEVELOPMENT.md](DEVELOPMENT.md). Implementation conventions live in [CODE_STANDARDS.md](CODE_STANDARDS.md).
