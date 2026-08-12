# Portable Agent Contracts

This repository defines host-neutral contracts for software-engineering roles, workflow skills, adapters, Zabin access, recovery, and conformance. Start with the [project README](README.md), use the registered contracts rather than host-specific conventions, and keep implementation detail in its canonical source.

## Documentation

| Topic | Canonical document |
| --- | --- |
| Project overview and support | [README.md](README.md) |
| System architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Coding and testing standards | [docs/CODE_STANDARDS.md](docs/CODE_STANDARDS.md) |
| Setup, commands, verification, and troubleshooting | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| Project-specific review priorities | [docs/REVIEW_FOCUS.md](docs/REVIEW_FOCUS.md) |

All build, test, run, installation, diagnostic, and conformance commands live in [Development](docs/DEVELOPMENT.md); do not copy them into repository instructions.

## Instruction Scope

- Live system, developer, user, and role instructions supplied by the active host remain higher authority; hosts may apply their own instruction precedence. Within the repository layer, the nearest path-scoped `AGENTS.md` governs its subtree, then this root file, then the managed document that owns the topic. Compatibility wrappers add no independent instruction.
- Use registered roles from [`config/agents.json`](config/agents.json) and workflow skills from [`skills/`](skills/). Invoke semantic host capabilities and canonical public operations; let the host resolve implementations and capability tiers. Keep portable instructions independent of any client, provider, concrete model, or transport-qualified tool spelling.
- Bind each Zabin action to an explicitly resolved project identifier and its applicable plan, phase, task, or review identity. Never infer workflow identity from the checkout, branch, ambient state, or a recovery checkpoint.
- Keep conductor and worker surfaces and credentials separate. Workers use only their task-scoped surface; never expose, copy, persist, or cross-wire credential values. The canonical boundary is [`config/zabin-mcp.json`](config/zabin-mcp.json).
- Prefer read-only, offline, and static verification first. Use live or mutating checks only when the assignment authorizes them, the exact target is known, and required scope and approvals are established; follow [Development](docs/DEVELOPMENT.md).
- Edit only the exact declared write paths in the assigned worktree. Inspect the existing status first, preserve unrelated and pre-existing changes, and never reset, overwrite, delete, or clean them away. Stop and report when containment cannot be established.
- Treat Zabin as authoritative workflow state. A local recovery checkpoint is redacted, minimal evidence for an explicit read-model gap, never a second ledger or authority; stop on divergence instead of reconciling by overwrite.
- Route managed-document writes only through the registered `doc_maintainer` role. Keep architecture, standards, development commands, review guidance, and repository guardrails in their owning files, link across boundaries, and keep `CLAUDE.md` as the import-only compatibility wrapper.
