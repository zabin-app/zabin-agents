---
name: conductor
description: Portable development-pipeline state machine backed by Zabin MCP. Researches, plans, obtains approval, verifies task scopes, dispatches workers, gates merges, reviews changes, and drives a bounded follow-up ratchet through host capabilities rather than host-specific commands. Use for multi-step feature, bug, refactor, implementation, or review work.
---

# Conductor

Run the development pipeline from the main loop. Zabin MCP is the durable control plane; the host supplies execution capabilities. Persist research, plans, tasks, waves, verdicts, gates, review rounds, action items, summaries, and commit mappings in Zabin as soon as they exist.

Do not create `PLAN.md`, `TASKS.md`, `REVIEW.md`, `ACTION_ITEMS.md`, per-task Markdown, or a Markdown review-round ledger as pipeline state. Ordinary source and project documentation remain normal repository files.

Read these references before acting:

- [MCP lifecycle](references/mcp-lifecycle.md) — public surfaces, strict vocabularies, leases, and ownership.
- [Host capabilities](references/host-capabilities.md) — portable operations used for dispatch, waiting, filesystem access, verification, and git.
- [Recovery](references/recovery.md) — Zabin-first reconciliation with the minimal Phase 1 checkpoint.
- [Payload examples](references/payload-examples.md) — concrete MCP argument objects.
- [Planning payloads](templates.md), [review payloads](review-templates.md), and [action-item payloads](ACTION_ITEMS_TEMPLATE.md).

## Invariants

1. Require an explicit `project_id` before any project-scoped call. `resolve_project` may discover it from an absolute repository path, but surface the returned id and pin it for the run. Never infer project identity from a session, branch, worktree, or child id.
2. Discover the MCP surface with `get_server_info` before mutation. Compare the required operations for the chosen path with the returned public tool names. Stop if a required capability is missing.
3. Invoke tools by their public names. Qualification is an adapter concern; pipeline instructions never contain transport- or host-qualified names.
4. Read authoritative state before deciding: `get_pickup_context`, `get_pipeline_state`, paged `list_tasks`, and paged `list_workspaces`. Retrieval search is supporting context, not a lifecycle ledger.
5. Preserve every human gate. Plan approval is performed by a human in a Zabin interface; no tool or agent approves its own plan.
6. Refuse dispatch until each card has a verified self-contained description, non-empty `write_files`, satisfied dependencies, and a fresh server-computed overlap report.
7. A dispatched worker owns its lease and the walk through `in_review`. The conductor owns verdicts, `validated`, merges, integration gates, `completed`, and release.
8. Git topology and mutations stay in the main loop. No worker, reviewer, validator, or workflow creates, merges, rebases, removes, or cleans a worktree.
9. The latest Zabin review round is the follow-up counter. Round 1 and round 2 are the only follow-up rounds; round 3 does not exist.
10. Recover from Zabin first. A local checkpoint is redacted, minimal, non-authoritative evidence for gaps in the read model, never a second ledger.

## State 0 — Orient and recover

Inputs are the absolute repository path and explicit `project_id` (or permission to resolve that path to an id).

1. Call `get_server_info {}` and require the operations used by this run. The canonical policy currently declares 52 conductor tools and a strict 17-tool worker subset; use the names returned at runtime and fail closed on missing requirements.
2. If identity must be resolved, call `resolve_project` with the absolute path. If not found, ask before `register_project`; registration is a durable human-gated mutation.
3. Call `get_pickup_context`, `get_pipeline_state`, `list_tasks`, and `list_workspaces` with the pinned `project_id`, paging until complete.
4. If resuming, follow [Recovery](references/recovery.md). Never invent `PHASE_BASE`, a review round, task ownership, or a merge mapping.
5. Inspect the project documentation policy and available architecture, development, standards, and review-focus documents. Missing project docs are reported; do not hallucinate them.

Classify the request as feature, bug, refactor, or research-only. A truly bounded change may run inline, but an existing task still receives its normal verdict and gates.

## State 1 — Research

Enumerate concrete questions and choose registered roles by capability, such as codebase research, external research, or history research. Use the host's `agent.dispatch` and `agent.wait` operations for independent bounded assignments. Agents return evidence; they do not persist pipeline state.

For three or more questions, an unknown affected area, or load-bearing assumptions, run the research-sweep program. For a large or risky plan, run the plan-verification program against each factual assumption and proposed write scope.

Immediately persist the synthesis with `record_research_artifact`. Store claim status (`verified`, `contested`, or `refuted`) and evidence in `body`; the tool has no separate claims field. Attach supporting files with `attach_file` when useful. Refuted, contested, and unverifiable claims belong in plan risks, not as facts in the plan body.

## State 2 — Plan and approval

Build plans incrementally using `create_plan_draft`, `set_plan_section`, `add_phase`, and `add_phase_tasks`; then call `finalize_plan`. Use [Planning payloads](templates.md).

Every task draft must contain:

- a self-contained objective and acceptance criteria;
- exact `write_files` and separate read-only dependencies;
- architecture and mutation constraints;
- verification commands grounded in the repository;
- a Zabin complexity value: `trivial`, `simple`, `moderate`, `complex`, or `epic`;
- phase-local dependency indices where required.

Refuse to finalize if any task lacks a non-empty write scope or usable contract. The card description is the only implementation specification the worker will receive.

After `finalize_plan` returns the ready state, present the plan id, revision, risks, phases, and task scopes, then pause for human approval. Wait using a host event capability when available; event delivery is only a wake-up signal. Always confirm approval with `get_plan` and require `approved_by` and `approved_at`. If unavailable, use an explicit human wait followed by low-frequency authoritative reads, never a busy loop.

Once approved, call `create_board` with the verified revision as `expected_revision`. A revision conflict requires a re-read and re-approval check. Re-read pipeline state to obtain durable plan, phase, board, and task ids.

## State 3 — Verify specifications and schedule

Join plan drafts to board cards by phase, sequence, and title. Page all reads. Before dispatching each card:

1. Call `get_task` and verify that `description` is complete and `write_files` is non-empty.
2. Verify relationships and unfinished blockers. Only `ready` cards are dispatchable.
3. Check active workspaces and claimed tasks for collisions.
4. Call `get_overlap_report` for exactly the candidate wave.
5. If `unscoped` is non-empty, repair the task contract or schedule it sequentially; never treat it as disjoint.
6. If `overlaps` contains a pair, split the pair across waves or run it sequentially. Only `parallel_safe:true` authorizes parallel worktrees.

Record each wave with `record_wave` using a one-based sequence, exact `task_ids`, and the current `WAVE_BASE` as `base_sha`, then mark it `running`.

## State 4 — Build and validate

Record `PHASE_BASE` once before the phase's first implementation and `WAVE_BASE` before each wave. These are main-loop git reads and recovery-critical values.

Select a host model tier by the portable registry, not a concrete identifier: `trivial`/`simple` normally use `fast`, `moderate` uses `balanced`, and `complex`/`epic` use `deep`. Raise a tier after a failed validation; never hardcode a vendor model.

Use the host capability contract in [Host capabilities](references/host-capabilities.md):

- a parallel-safe set uses `git.create_worktree`, then one `agent.dispatch` per card and `agent.wait` for results;
- overlapping or single-card work runs sequentially and must not race the working branch;
- dispatch only the identity stub: `project_id`, `task_id`, exact `agent_name`, worktree path, branch, base branch/SHA, lease TTL, and verification/doc-routing context. Do not paste a second copy of the spec.

Size worker TTL by task complexity: `simple` 1800, `moderate` 3600, `complex` 7200, `epic` 14400 seconds; choose a bounded TTL for `trivial`. The worker verifies the granted TTL and renews immediately before long checks.

### Worker-owned segment

Each implementor uses only the worker surface and performs, in order:

1. `claim_task` under its exact `agent_name` and sized `lease_ttl_secs`.
2. `get_task`; stop if the returned spec or scope differs from dispatch identity.
3. `register_worktree` with task, agent, branch, base branch, and base SHA.
4. `update_task_status` to `queued`, then `executing`.
5. Implement only `write_files`; narrate stages with `post_progress_message` and renew before long verification.
6. Verify, commit, and call `record_commits`.
7. Mark the worktree `idle` with its current SHA when supported.
8. `update_task_status` to `in_review`, then `record_task_summary`.
9. Retain the lease. Do not write `validated`/`completed` and do not release.

### Conductor-owned segment

For each returned worker:

1. Reconcile card status, lease name, workspace row, commits, summary, and containment. Missing durable bookkeeping is a gap to repair explicitly, not a reason to guess.
2. Run a registered task validator over the exact base-to-branch diff and acceptance criteria.
3. Persist every task check with `record_gate_result` and the validator result with `record_task_verdict`.
4. On `pass`, write `validated` under the worker's `agent_name` before merging. On `concern` or `fail`, leave it unmerged, move it to `needs_rework`, mark the wave blocked, preserve its branch, and pause.
5. Merge passing branches in task order using main-loop git capabilities. Stop on conflict, record workspace conflict state, and preserve evidence.
6. Replay commit mappings with the merged SHA and update workspace state through `merged` and `removed` as the git operations complete.
7. Run the integration verifier over `WAVE_BASE..HEAD`. Persist task- or phase-scoped gate results under unique stable names.
8. After all required integration gates pass, write `completed` under the worker's `agent_name`, inspect `blocking_task_ids`, then `release_task`. Mark the wave `merged`.

An integration failure after merge moves `validated` to `needs_rework`, marks the wave blocked, preserves integrated commits, and fixes forward. Never silently roll back and never merge a branch with a failed task verdict.

## State 5 — Documentation routing

Documentation work is a task, not an incidental edit.

1. Collect `doc_updates_needed` from implementation summaries and review findings.
2. Resolve targets from the project's documentation policy and actual structure. Under a split structure, edit the unit doc and touch a root index only for cross-unit dependencies, new units, or changed links.
3. Create dedicated tasks with exact doc `write_files`, evidence, complexity, and dependencies. Link review-driven tasks to their action item.
4. Route core architecture, code-standards, development, and review-focus documents to the registered documentation-maintainer role. Ordinary implementors must not edit them.
5. Run doc tasks sequentially relative to the next wave, validate them, and persist the same verdict/gate lifecycle. If a role has no worker surface, the conductor holds and walks that card explicitly.

## State 6 — Review

After the final wave and documentation tasks pass, require a clean primary checkout apart from expected user changes. Dispatch registered review roles over `<PHASE_BASE>..HEAD`: architecture, quality, logic, risk/tradeoffs, security, and bug-fix correctness for bugs. Adversarially verify Critical and Major findings before accepting them.

Persist the synthesized result in the same turn:

1. `record_review_round` at round `0`, scoped to the phase or plan, with normalized verdict, reviewed SHA, and summary.
2. `add_action_item` once per confirmed finding, including Minor findings, linked to the review round and task when known.
3. Do not write a local review ledger. `get_pipeline_state` and the latest review round are authoritative.

Use [Review payloads](review-templates.md) and [Action-item payloads](ACTION_ITEMS_TEMPLATE.md).

## State 7 — Exact two-round follow-up ratchet

Call `get_pipeline_state` before every decision and read the latest round for the exact scope.

| Latest verdict | Action |
|---|---|
| `approved` | Report. |
| `approved_with_concerns` | Mark remaining Minor items `deferred`; report. This is passing and terminal. |
| `needs_work` / `rejected`, latest round 0 | Round 1 targets confirmed Critical and Major findings. |
| `needs_work` / `rejected`, latest round 1 | Round 2 targets only unresolved or newly introduced Critical findings. Defer Major and Minor items. |
| Any non-passing verdict at round 2 | Stop and escalate. Round 3 is forbidden. |

For each eligible round:

1. Dispatch follow-up investigation for only the in-scope findings.
2. Persist contested and not-reproduced diagnoses with `record_research_artifact`. If no taskable diagnoses remain, stop and escalate.
3. Create fix cards on the same board with exact `write_files`, complexity, and `action_item_id`. There is no new plan approval gate.
4. Re-enter State 3 and State 4 for those cards only, including a fresh overlap report and wave. Never recursively review the fix wave as a new phase.
5. Re-review the original `<PHASE_BASE>..HEAD` in convergence mode using the previous review as context. Record round `1` or `2`.
6. Update existing action items to `resolved`, `deferred`, `wont_fix`, or back to `open`; never re-file the same finding.

Stop early if the same blocking finding survives two consecutive reviews, the verdict does not improve, no taskable fix exists, a fix changes an approved design decision, or any required task specification/base cannot be recovered unambiguously.

## State 8 — Report

Read final state from Zabin and git. Report the pinned project id, plan/board/phase ids, task counts and blockers, waves, source and merged commits, gates, latest review verdict/round, follow-up count, deferred or `wont_fix` findings, documentation routing, and capability limitations.

Never reconstruct the report from conversation memory or local Markdown.
