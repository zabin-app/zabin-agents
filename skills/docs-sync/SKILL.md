---
name: docs-sync
description: Reconstruct the core project docs (ARCHITECTURE.md, CODE_STANDARDS.md, DEVELOPMENT.md, root agent-instructions file) compactly from the current codebase. Fans out parallel explorers following the docs-explore runbook, then drives doc_maintainer to rewrite each doc under its size budget. Use when docs have drifted or bloated past their caps. Triggers on "sync docs", "rebuild docs", "compact docs", "regenerate docs".
---

# Docs Sync

You rebuild a project's core docs **compactly from ground truth in the code**, rather than editing them incrementally. This is the remedy when a doc has bloated past its hard cap (see `~/.agents/skills/doc-validate/schemas.md` → *Size Budgets & Compaction*), accumulated "Phase N" changelog narrative, dropped to function/field-level altitude, or duplicated content across docs and the root agent-instructions file.

The heavy, parallel exploration follows the **`docs-explore.md` runbook** (background subagents, returns only compact maps). The gated writing — deciding flat vs hub-and-spoke, overwriting large files, pausing for approval, committing — stays here in the main loop, driven through `doc_maintainer` (the only agent allowed to edit core docs).

## Before starting (mandatory)

Read `~/.agents/skills/doc-validate/schemas.md` (size budgets, content boundaries, altitude/duplication rules). Read the existing `docs/` and the root agent-instructions file to see current state and sizes (`wc -l`).

## Workflow

### 1. Discover subsystems

Identify the units to explore in parallel:
- Read the manifest(s) — `Cargo.toml` (workspace members), `package.json`/workspaces, `pubspec.yaml`, `go.mod`, etc.
- Map top-level source dirs / workspace crates / packages to subsystems.
- A single-package repo → one "subsystem" (the whole `src/`).

Build a `subsystems: [{ label, path }]` list.

### 2. Explore (runbook)

Follow `~/.agents/skills/conductor/workflows/docs-explore.md` with `subsystems: [{ label, path }, ...]`.

It returns `{ maps: [...compact per-subsystem maps...], recommendedStructure: "flat"|"hub-and-spoke", rationale }`. The maps are already altitude-trimmed (low-level detail and history stripped). Nothing was written. Since one subagent cannot recursively delegate further, issue the per-subsystem `delegate` calls for this runbook directly from the main loop (parallel), then `load` each result.

### 3. Decide structure and present the plan

- Take `recommendedStructure` as the default; sanity-check it against the budgets (one flat `ARCHITECTURE.md` must end up ≤ 500 lines — split to `docs/<SUBSYSTEM>_ARCHITECTURE.md` spokes + a ≤120-line linked index otherwise).
- **Present the rebuild plan and PAUSE for approval** before overwriting anything: which docs will be (re)written, flat vs hub-and-spoke, and the rough target size of each. Rebuilding overwrites substantial existing docs — confirm first. Recommend the user has a clean working tree (the rebuild is one reviewable commit).

### 4. Rebuild each doc (main loop, via doc_maintainer)

Dispatch `doc_maintainer` (it enforces the budgets, content boundaries, altitude, present-tense, and no-duplication rules). Give it the maps as the source material, not the old doc text:

```
delegate(source: "doc_maintainer", provider: "github_copilot", model: "claude-sonnet-5",
  instructions: "Rebuild <docs/ARCHITECTURE.md | the hub-and-spoke set> from these verified subsystem maps:
<paste the relevant docs-explore maps>

Write at architecture altitude, present tense, no 'Phase N' history. Keep ARCHITECTURE.md (or each spoke) ≤ 350 lines, hard cap 500; index ≤ 120. State each fact once and cross-reference. Follow ~/.agents/skills/doc-validate/schemas.md. Commit when done.",
  working_dir: "<repo path>", async: true)
```
Then `load(source: "<task_id>")` to retrieve completion.

- **ARCHITECTURE.md** (or spokes + index) from the maps' responsibility / keyModules / dependencies / keyPublicTypes / dataFlows.
- **DEVELOPMENT.md** and **CODE_STANDARDS.md** only if the maps' `devSignals` (build/run/test commands, observed conventions) reveal drift — otherwise leave them. Keep each within budget.
- **REVIEW_FOCUS.md** is curated judgment (hot spots, severity calibration), not derivable from code — never rewrite it from the maps. Only dispatch `doc_maintainer` to fix references the rebuild broke (renamed/moved/deleted modules it points at). Keep ≤ 150 lines, hard cap 200.
- **Root agent-instructions file** as a lean ≤80-line index: one-paragraph description + a link table into the core docs + must-know commands (or a pointer to DEVELOPMENT.md) + repo-specific agent guardrails. **No content copied from the core docs.**

Process docs sequentially (they share the working tree); do not parallelize core-doc writes.

### 5. Validate

Load and run the `doc_validate` skill to confirm the rebuild is under cap and clean:

```
load_skill(name: "doc_validate", args: "validate the rebuilt docs")
```

Address any Error-level findings (over cap, duplicate section, boundary violation) before reporting. Warnings can be noted as deferred.

### 6. Report

Summarize: structure chosen (flat / hub-and-spoke), per-doc line count before → after, and the validator verdict.

## Boundaries

- **DO** ground the rebuild in the `docs-explore` maps (current code), not the stale doc text.
- **DO** pause for approval before overwriting substantial docs.
- **DO** keep every doc under its hard cap; split to hub-and-spoke rather than letting one doc absorb everything.
- **DO** route all core-doc writes through `doc_maintainer`.
- **DO NOT** edit source code.
- **DO NOT** duplicate content across docs or copy doc content into the root agent-instructions file — link instead.
- **DO NOT** parallelize core-doc writes (shared working tree).
