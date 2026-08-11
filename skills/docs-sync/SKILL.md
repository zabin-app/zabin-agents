---
name: docs-sync
description: Reconstruct the managed project docs and canonical root instructions compactly from current repository evidence. Uses portable registered roles and routes every managed-doc write through the MCP-free doc_maintainer role. Triggers on "sync docs", "rebuild docs", "compact docs", "regenerate docs".
---

# Docs Sync

Rebuild managed documentation from current repository evidence rather than incrementally extending stale prose. Use this when docs exceed policy budgets, contain historical or low-altitude detail, or duplicate instructions across documents.

The host main loop owns discovery, approval, dispatch, waiting, validation, and commits. Exploration follows the conductor's `docs-explore` runbook. All managed-document writes go through the registered `doc_maintainer` role, sequentially, with no MCP surface or credentials.

## Before starting

1. Resolve this skill's bundled [validator policy](../doc-validate/schemas.md) through the host's skill/resource loader; do not assume a home directory or installation path.
2. Read the repository's existing `docs/`, root `AGENTS.md`, and root `CLAUDE.md`, recording missing files and line counts.
3. Read the [portable role registry](../../config/agents.json) and conductor [host-capability contract](../conductor/references/host-capabilities.md). Require safe mappings for `filesystem.read`, `filesystem.search`, `git.inspect`, `agent.dispatch`, `agent.wait`, `human.prompt`, and the main-loop commit operation.
4. Require a clean or explicitly understood working tree before proposing overwrites.

`AGENTS.md` is the canonical repository instruction file. `CLAUDE.md` is only a compatibility wrapper whose sole nonblank line is `@AGENTS.md`. Commands live in `docs/DEVELOPMENT.md`; repository-specific agent guardrails live in `AGENTS.md`. Neither is repeated in the wrapper or another managed doc.

## Workflow

### 1. Discover subsystems

Read repository manifests and top-level source layout. Map workspace members or independently built packages to `subsystems: [{label, path}]`. A single-package repository normally has one subsystem rooted at its primary source directory.

### 2. Explore

Run the bundled [docs-explore](../conductor/workflows/docs-explore.md) program through the host's skill/runbook mechanism. It uses registered `codebase_researcher` assignments through semantic `agent.dispatch`/`agent.wait` operations and returns compact evidence-grounded maps. Do not use client-specific spawn/load verbs, provider namespaces, or concrete model names.

If required maps are missing or caveated such that the current architecture cannot be established, stop before proposing an overwrite.

### 3. Propose structure and pause

Use the runbook recommendation as the default. A flat document targets 350 lines and must remain below the 500-line hard cap. If it cannot, propose subsystem spokes plus an index targeting 120 lines and remaining below 150.

Present the files to rebuild, flat or hub-and-spoke structure, rough target sizes, files that will remain unchanged, and the expected root-file normalization. Obtain explicit approval with `human.prompt` before any substantial overwrite.

### 4. Dispatch managed writes sequentially

The managed set is:

- `docs/ARCHITECTURE.md`, `docs/CODE_STANDARDS.md`, `docs/DEVELOPMENT.md`, and `docs/REVIEW_FOCUS.md`;
- their `docs/<SUBSYSTEM>_<DOCTYPE>.md` variants;
- root `AGENTS.md` and root `CLAUDE.md`.

No other role may write these files. Do not send source files, ordinary docs, task ledgers, or pipeline state to `doc_maintainer`.

For each non-overlapping sequential write assignment, validate the exact registered `doc_maintainer` input:

```json
{
  "objective": "Rebuild the declared managed documents from verified evidence under the bundled validator policy. Keep AGENTS.md canonical and CLAUDE.md as the import-only wrapper.",
  "write_files": ["<exact repository-relative managed paths>"],
  "evidence": ["<docs-explore maps or repository-relative evidence references>"]
}
```

Call the host's semantic `agent.dispatch` with role `doc_maintainer`, its registered tier, the repository/worktree binding, and no MCP capability or credential. The host resolves the tier to an available model. Collect with `agent.wait` and validate the untouched result against the registered output schema.

The maintainer receives the validator policy as a host-resolved resource. It must not call Zabin, claim or update a task, write a task ledger, approve the plan, dispatch another role, choose a model, or commit through an undeclared capability. The main loop validates the diff and performs the repository commit after all writes pass.

Rebuild rules:

- Architecture comes from map responsibilities, key modules, dependencies, public types, and flows.
- Development and code-standards docs change only when verified `devSignals` establish drift.
- `REVIEW_FOCUS.md` is curated judgment, not derivable from architecture maps. Change only broken references or separately supplied project-specific review evidence.
- `AGENTS.md` is a lean index and the single home for repository-specific agent guardrails. It links to the managed docs and points to `DEVELOPMENT.md` for commands.
- `CLAUDE.md` contains only `@AGENTS.md`; it contains no commands, guardrails, links table, or copied prose.
- Process shared-working-tree writes sequentially.

### 5. Validate and commit

Invoke the bundled `doc_validate` skill through the host's skill mechanism. Require it to audit all four managed doc types, every subsystem variant, both root files, precedence, duplication, sizes, content boundaries, and links.

Resolve every Error before commit. Re-run the audit and a repository-relative link check, inspect the exact diff, and require all changed paths to be in the approved managed write set. The main loop then commits through its mapped git capability. Warnings may be deferred only when reported with a concrete rationale.

### 6. Report

Report the chosen structure, per-file line count before and after, validator verdict, changed paths, commit id, and any deferred warnings.

## Boundaries

- Ground all rebuilt content in current repository evidence.
- Pause for approval before substantial overwrites.
- Route every managed-doc mutation only through the MCP-free `doc_maintainer` role.
- Keep facts in their owning document and link across boundaries.
- Keep commands only in `DEVELOPMENT.md`, guardrails only in `AGENTS.md`, and the wrapper import-only.
- Do not edit source code, use client-specific dispatch syntax, name a provider/concrete model, or parallelize shared-tree writes.
