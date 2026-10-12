---
name: studio
description: Creative-production overlay on the conductor pipeline, backed by Zabin MCP. Drives books and manuscripts (chapters, scenes, nonfiction), YouTube videos and scripts (research briefs, hooks, segments, b-roll, descriptions), and films and screenplays (treatments, scenes, breakdowns, shot lists) through research, plan approval, producer waves, assembly gates, multi-dimension creative review, and the bounded follow-up ratchet. Use for any multi-step creative production in a git-backed creative project that selected the studio pack.
---

# Studio

## Purpose

Run creative production — a book, a YouTube video, a film — on the same Zabin control plane and the same state machine as software work. Studio is an **overlay**: it keeps every conductor state, invariant, human gate, lease rule, and ledger rule, and substitutes only roles, program arguments, gates, and domain knowledge. A manuscript or script repository takes the place of a code base, the project bible under `bible/` takes the place of the architecture and standards documents, and an assembled draft takes the place of a build.

The studio pack is project-scoped. This skill and the conductor it overlays are installed into the creative project itself, never into a home directory (see [Starting a creative project](#starting-a-creative-project)).

## Run the conductor

Follow the [conductor skill](../conductor/SKILL.md) entirely — States 0–8, Invariants 1–12, and every reference it requires: [MCP lifecycle](../conductor/references/mcp-lifecycle.md), [backlog triage](../conductor/references/backlog-triage.md), [host capabilities](../conductor/references/host-capabilities.md), [recovery](../conductor/references/recovery.md), [payload examples](../conductor/references/payload-examples.md), [planning payloads](../conductor/templates.md), [review payloads](../conductor/review-templates.md), and [action-item payloads](../conductor/ACTION_ITEMS_TEMPLATE.md). On Claude Code also read the [Claude Code adapter note](../conductor/references/claude.md), which owns program names, argument shapes, tier strings, and vocabulary translation.

This file lists only deltas. Where it is silent, the conductor governs unchanged; where a delta and the conductor appear to disagree on anything other than a role, a program argument, a gate name, or domain knowledge, the conductor wins and the disagreement is a defect in this file. Nothing here relaxes a human gate, the overlap report, the worker/conductor surface split, the two-round ratchet, or strict-vocabulary persistence.

Also read before acting:

- [Domain profiles](references/domain-profiles.md) — phase templates, artifact layouts, parallelism, review dimensions, and assembly gates for each supported medium.
- [Studio payloads](references/payloads.md) — concrete argument objects for the studio-specific calls.

### Role substitution

Registered ids come from [`config/agents.json`](../../config/agents.json). Programs under the Claude Code adapter take the kebab-case agent type rendered from each id.

| Software role | Studio role (registry id) | Agent type (Claude Code) | Used in |
|---|---|---|---|
| `implementor` | `producer` | `producer` | State 4 drafting and fix cards |
| `doc_maintainer` (for project facts) | `bible_keeper` | `bible-keeper` | Bible phase, State 5 bible cards |
| `task_validator` | `artifact_validator` | `artifact-validator` | State 4 validator stage |
| `codebase_researcher` | `project_researcher` | `project-researcher` | State 1, State 7 |
| `external_researcher` | `external_researcher` | `external-researcher` | State 1 world facts, sources, platform data |
| code review dimensions | `structure_reviewer`, `craft_reviewer`, `continuity_checker`, `fact_rights_reviewer`, `audience_reviewer` | `structure-reviewer`, `craft-reviewer`, `continuity-checker`, `fact-rights-reviewer`, `audience-reviewer` | State 6 |
| `integration_verifier` build/test | assembly checks | — | State 4 integration gates |

A dispatched producer or bible keeper is granted the worker surface and nothing more (Invariant 11), exactly as an implementor is.

## Per-state deltas

### State 0 — Orient and recover

1. Require a git-backed creative project. Resolve or register it by its absolute repository path; a directory that is not a git repository is not a studio project — stop and point the human at [Starting a creative project](#starting-a-creative-project).
2. Confirm the pack from the project marker: `.zabin/project.toml` must carry `agent_packs` including `studio`. A missing marker or pack is reported to the human; do not install anything from inside the run.
3. Read `bible/` in full — style guide, story or production bible, audience and platform declarations, sources. It is the project's standards document. When `bible/` is absent or empty, the plan's first phase is a Bible phase (State 2).
4. Determine the domain profile (book fiction, book nonfiction, YouTube video, film) from the bible's format declaration or the request. An undeclared or ambiguous medium is a creative-direction decision for State 1, not a guess.

### State 1 — Research

- Route questions by source: `project_researcher` for the project's own materials (bible, outline, drafts, notes, sources folder, draft history); `external_researcher` for world facts, primary and secondary sources, and platform data. Each research-sweep and plan-verification item carries its `agentType` accordingly — see the [research-sweep example](references/payloads.md#research-sweep-mixed-sources).
- Creative-direction decisions — premise, tone, audience, length, format, medium — go to the human through `ask_user_questions` and are never decided by an agent. Agents may research options and propose them as choices; the human picks. Record the answers in the research artifact and carry them into the plan's `decisions` section, citing the question.
- Claims a producer will state as fact (nonfiction, YouTube, biopic) are load-bearing research: run them through verification, and put contested or unsourced ones in plan risks, never in the bible.

### State 2 — Plan and approval

- Phases follow the chosen profile's phase template in [Domain profiles](references/domain-profiles.md). When State 0 found no usable bible, phase 0 is a Bible phase of `bible_keeper` cards that record the approved creative-direction decisions.
- Every card's `write_files` are artifact paths in the profile's layout (for example `manuscript/ch07.md`, `script/03-segment.md`, `screenplay/scene012.fountain`). A card that writes `bible/` paths is a `bible_keeper` card; a card never mixes bible files with drafting artifacts.
- Acceptance criteria are measurable: word or runtime budgets with tolerance, required beats or sections, format rules, and bible conformance naming the exact `bible/` files (`bible_paths`) the artifact must conform to. "Engaging" or "well written" is not a criterion; a named beat, a budget, or a conformance target is.
- Units that share narrative state (consecutive chapters, scenes with the same characters' unresolved changes, a segment that pays off another) are ordered with `depends_on`. Parallel drafting is allowed only for units whose outline is fixed and which are independent of each other's text.
- Continuity work never runs parallel with drafting: a bible or continuity card never shares a wave with drafting cards that touch the narrative state it records.
- Verification commands are measurement, not builds: word counts, line counts, format checks the profile defines.

### State 3 — Verify specifications and schedule

No delta. The server overlap report, `update_task` amendment, and wave recording apply unchanged.

### State 4 — Build and validate

- Dispatch drafting cards with the wave-implementation program using `tasks[].agentType` `producer` (or `bible-keeper` for bible cards) and top-level `validatorType` `artifact-validator`; see the [implement-wave example](references/payloads.md#implement-wave-producer-and-artifact-validator). Model tiers follow the conductor's complexity mapping.
- Every producer card's implement-wave task carries `biblePaths` (the bible files it must conform to, also named in its `acceptanceCriteria`). The validator then checks conformance; a violation is a `fail`, and an unrecorded new fact is at least a `concern` unless the producer listed it in its returned `docUpdatesNeeded` (its `bible_updates_needed`).
- `validatorType: artifact-validator` is MANDATORY on every studio implement-wave call; never rely on the task-validator default. `validatorModel` defaults to haiku and may be raised (sonnet or opus) for long or bible-heavy artifacts, at higher cost.
- Integration gates are **assembly checks**, not a build: assemble the full manuscript or script in outline order, measure total length against the budget, confirm every outline unit is present and no orphan exists, and run the profile's format lint where it defines one. Persist each as `wave-<n>-assembly-<check>` (for example `wave-2-assembly-length`) through `record_gate_results`, deriving `<n>` from existing gate names as the conductor requires. There is no build toolchain; never install one.
- Assembled output is evidence, not an artifact: write it under the run's artifact root outside the repository, never into the checkout, and never commit it.

### State 5 — Documentation routing

- Bible updates are `bible_keeper` cards on repository files under `bible/`, not managed documents and not `doc_maintainer` work. Collect bible updates from each producer's returned `docUpdatesNeeded` (its `bible_updates_needed`; also in the Zabin task summary) and from continuity and fact findings; each fact cites its merged source.
- Bible cards follow the conductor's documentation-task rules unchanged: exact `write_files`, sequential relative to the next wave, the same verdict and gate lifecycle (validated by `artifact_validator`).
- Managed project documents, if a creative project has any, stay on the conductor's State 5 path unchanged.

### State 6 — Review

- Run the diff-review program over `<PHASE_BASE>..HEAD` with `dimensions` set to the profile's default dimension set (plus any optional dimension the bible or the human enabled), `changeType` `feature`, and the bible files as `docs`. `dimensions` replaces the code dimensions entirely; no software reviewer runs. See the [review-diff example](references/payloads.md#review-diff-youtube-dimension-set).
- A review-diff result with `refused` (verdict `null`) or a non-empty `missingDimensions` blocks approval: re-run it, never read it as a pass.
- Adversarial verification, verdict normalization, round numbering, and action-item filing are unchanged.

### State 7 — Follow-up ratchet

- Run follow-up investigation with top-level `agentType` `project-researcher` (MANDATORY). Route each `fact_rights` finding about a real-world fact per issue with `agentType: external-researcher`; its issue text must be self-contained (quote the artifact `path:line` and the claimed fact from the finding, plus the project's own source statement when one exists), because `external-researcher` cannot read the project. See the [followup-investigate example](references/payloads.md#followup-investigate).
- Capability rule: a `notReproduced` result is authoritative only when the investigator could reach the evidence. If not (for example `project-researcher` on a world fact), re-dispatch that issue once with the capable `agentType`; if it still does not resolve, keep the action item open and escalate. Never resolve or drop it.
- Fix cards are `producer` cards on the affected artifact paths (or `bible_keeper` cards when the finding is a bible error), each with `action_item_id`. The two-round cap and convergence-at-cap rules are unchanged.

### State 8 — Report

In addition to the conductor's report, list:

- the artifact package: every delivered artifact path in assembly order, with the final assembly gate results (length against budget, coverage, format);
- the bible changes: every `bible/` path changed in the plan, with its commits and any recorded conflicts left open.

## Starting a creative project

A one-time operator setup, done outside the pipeline run:

1. Create the repository: `git init` in the project directory. The manuscript, script, bible, and every artifact live in it.
2. Register the project in Zabin by its absolute path (a human-gated `register_project`, or the operator's usual interface) and note the returned project id.
3. Write the marker with the studio pack: `zabctl project init --project-id <id> --agent-packs studio`. It records `agent_packs = "studio"` in `.zabin/project.toml`; commit that file.
4. Install the pack into the project: `zabctl agents install --claude --destination .` (from the project root). With `--destination` naming the project, the marker's `agent_packs` selects the pack; `--pack` and `--prune` exist for changing the selection later.
5. Render the project MCP connections: `zabctl project render-mcp`.

Never install the studio pack without `--destination <project>`: it is project-only, and zabctl refuses a studio install aimed at the home directory.

## Host support

Studio substitutions rely on the parameterized Claude Code programs. The portable runbooks under `skills/conductor/workflows` still name software roles, so studio is supported on Claude Code only for now.

## What stays software-shaped

- Git worktrees, branches, commits, squash merges, and diff ranges remain the versioning model. A draft revision is a commit; a review covers `<PHASE_BASE>..HEAD`; a rejected draft is a preserved branch.
- The TUI and the ledger keep their git and software vocabulary — worktree, branch, merge, gate, build column names. Read "build" as "assembly" and "code" as "artifact"; do not rename anything in Zabin.
- The operator's global software install (the home-directory conductor, software roles, and programs) remains visible inside the creative project alongside the project-scoped studio pack. Select studio roles explicitly by the substitution table above; never fall back to a software role because it is also installed.
