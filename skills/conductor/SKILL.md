---
name: conductor
description: Portable development-pipeline state machine backed by Zabin MCP. Researches, plans, obtains approval, verifies task scopes, dispatches workers, gates merges, reviews changes, and drives a bounded follow-up ratchet through host capabilities rather than host-specific commands. Use for multi-step feature, bug, refactor, implementation, or review work.
---

# Conductor

Run the development pipeline from the main loop. Zabin MCP is the durable control plane; the host supplies execution capabilities. Persist research, plans, tasks, waves, verdicts, gates, review rounds, action items, summaries, and commit mappings in Zabin as soon as they exist.

Do not create `PLAN.md`, `TASKS.md`, `REVIEW.md`, `ACTION_ITEMS.md`, per-task Markdown, or a Markdown review-round ledger as pipeline state. Ordinary source and project documentation remain normal repository files.

Read these references before acting:

- [MCP lifecycle](references/mcp-lifecycle.md) — public surfaces, strict vocabularies, leases, and ownership.
- [Backlog triage](references/backlog-triage.md) — the research-phase sweep of open and deferred action items, the aging rule, and batch-citation hygiene.
- [Host capabilities](references/host-capabilities.md) — portable operations used for dispatch, waiting, filesystem access, verification, and git.
- [Recovery](references/recovery.md) — Zabin-first reconciliation with the minimal Phase 1 checkpoint.
- [Payload examples](references/payload-examples.md) — concrete MCP argument objects.
- [Planning payloads](templates.md), [review payloads](review-templates.md), and [action-item payloads](ACTION_ITEMS_TEMPLATE.md).
- Host adapter notes, when the running host has one: [Claude Code](references/claude.md). An adapter note translates the portable operations below into one host's concrete surface; nothing in it is a portable requirement, and no other state in this skill depends on it.

## Invariants

1. Require an explicit `project_id` before any project-scoped call. `resolve_project` may discover it from an absolute repository path, but surface the returned id and pin it for the run. Never infer project identity from a session, branch, worktree, or child id.
2. Discover the MCP surface with `get_server_info` once per session — cache the returned tool list and re-check only after a call fails in a way that suggests the surface drifted, never on a fixed schedule — before mutation. Compare the required operations for the chosen path against the cached names. Stop if a required capability is missing.
3. Invoke tools by their public names. Qualification is an adapter concern; pipeline instructions never contain transport- or host-qualified names.
4. Read authoritative state before deciding: `get_pickup_context`, `get_pipeline_state`, paged `list_tasks`, and paged `list_workspaces`. Retrieval search is supporting context, not a lifecycle ledger.
5. Preserve every human gate. Plan approval is performed by a human in a Zabin interface; no tool or agent approves its own plan.
6. Refuse dispatch until each card has a verified self-contained description, non-empty `write_files`, satisfied dependencies, and a fresh server-computed overlap report.
7. A dispatched worker owns its lease and the walk through `in_review`. The conductor owns verdicts, `validated`, merges, integration gates, `completed`, and release.
8. Git topology and mutations stay in the main loop. No worker, reviewer, validator, or workflow creates, merges, rebases, removes, or cleans a worktree.
9. The latest Zabin review round is the follow-up counter. Round 1 and round 2 are the only follow-up rounds; round 3 does not exist.
10. Recover from Zabin first. A local checkpoint is redacted, minimal, non-authoritative evidence for gaps in the read model, never a second ledger.
11. Conductor and worker surfaces carry separate credentials, and a dispatched implementor is given only the worker surface. The split binds a *separate client*; it does not by itself bind a role dispatched inside the running session, where both surfaces may already be reachable. There, the enforcement is the dispatched role's declared tool grant: a role allowed the conductor surface bypasses lease discipline entirely, from inside its own worktree. Naming the worker surface in the dispatch is necessary and not sufficient.
12. Persist only strict-vocabulary values. External programs return their own verdict and status spellings; translate them to the MCP enums before writing. An off-list value is rejected, not stored — a mistranslated verdict is a lost result, not a stored approximation.

## State 0 — Orient and recover

Inputs are the absolute repository path and explicit `project_id` (or permission to resolve that path to an id).

1. Call `get_server_info {}` once per session and cache its tool list; require the operations used by this run against that cached list and fail closed on missing requirements. Do not hardcode a tool count in instructions — the served surface grows and shrinks independently of this document, so the runtime list from `get_server_info` is the only authoritative inventory. Re-check only after an error suggests the cached list has drifted, never on a fixed schedule.
2. If identity must be resolved, call `resolve_project` with the absolute path. If not found, ask before `register_project`; registration is a durable human-gated mutation.
3. Call `get_pickup_context` and `get_pipeline_state {project_id, detail:"summary"}` with the pinned `project_id`; reserve `detail:"full"` for phase boundaries and review synthesis (State 6), where the full gate and review detail is load-bearing. Call `list_tasks` filtered to the live statuses this run needs — `ready`, `executing`, `in_review`, `needs_rework`, `validated`, as applicable — never an unfiltered page walk through completed history. Call `list_workspaces` filtered to `active`/`idle` unless reconciling a specific gap, in which case widen the filter only as far as the gap requires.
4. If resuming, follow [Recovery](references/recovery.md). Never invent `PHASE_BASE`, a review round, task ownership, or a merge mapping.
5. Inspect the project documentation policy and available architecture, development, standards, and review-focus documents. Missing project docs are reported; do not hallucinate them.

Classify the request as feature, bug, refactor, or research-only. A truly bounded change may run inline, but an existing task still receives its normal verdict and gates.

## State 1 — Research

Enumerate concrete questions and choose registered roles by capability, such as codebase research, external research, or history research. Use the host's `agent.dispatch` and `agent.wait` operations for independent bounded assignments. Agents return evidence; they do not persist pipeline state.

For three or more questions, an unknown affected area, or load-bearing assumptions, run the research-sweep program. For a large or risky plan, run the plan-verification program against each factual assumption and proposed write scope.

For orientation, deduplication, and prior-art questions — has this already been discussed, does a research artifact or action item already cover it — start with `search_context` rather than paging the ledger tools directly: it is a two-stage read, a snippet first and a full fetch only for the artifact you are about to act on. This narrows the field; it does not replace the authoritative reads in Invariant 4, and once a specific card or document is the thing being implemented against, read it in full rather than from a snippet.

Immediately persist the synthesis with `record_research_artifact`. Store claim status (`verified`, `contested`, or `refuted`) and evidence in `body`; the tool has no separate claims field. Attach supporting files with `attach_file` when useful. Refuted, contested, and unverifiable claims belong in plan risks, not as facts in the plan body. State 1 research predates the plan and is recorded without `plan_id`; keep every returned `rsa_…` id, because State 2 is the only step that attaches it to the plan.

## State 2 — Plan and approval

Build plans incrementally using `create_plan_draft`, `set_plan_section`, `add_phase`, and `add_phase_tasks`; then call `finalize_plan`. Use [Planning payloads](templates.md).

Pass every State 1 artifact id to `create_plan_draft` as `research_artifact_ids`. A plan's research — what its Docs view shows the operator — is exactly the artifacts linked there, recorded with its `plan_id`, or attached later with `link_research_artifacts`. `finalize_plan` refuses a plan with none. `no_research_reason` exists for a plan that genuinely had no research; it is recorded and shown to the operator, so it is never a way around linking research that exists.

Every task draft must contain:

- a self-contained objective and acceptance criteria;
- exact `write_files` and separate read-only dependencies;
- architecture and mutation constraints;
- verification commands grounded in the repository;
- a Zabin complexity value: `trivial`, `simple`, `moderate`, `complex`, or `epic`;
- phase-local dependency indices where required.

Refuse to finalize if any task lacks a non-empty write scope or usable contract. The card description is the only implementation specification the worker will receive, and it is deliberately the **single copy** of that contract: a thin description now produces a thin implementation, because the dispatch carries no spec text to compensate with. A second copy pasted into a prompt is worse than none — it drifts from the card, and the worker cannot tell which one is current.

After `finalize_plan` returns the ready state, present the plan id, revision, risks, phases, and task scopes, then pause for human approval. Wait using a host event capability when available; event delivery is only a wake-up signal. Always confirm approval with the minimal approval-check read — `get_plan {plan_id, sections: [], include_task_drafts: false}`, which returns `approved_by`, `approved_at`, and the current revision without the full document — and require both fields set. If unavailable, use an explicit human wait followed by low-frequency authoritative reads, never a busy loop.

Once approved, call `create_board` with the verified revision as `expected_revision`. A revision conflict requires a re-read and re-approval check. Re-read pipeline state to obtain durable plan, phase, board, and task ids.

## State 3 — Verify specifications and schedule

Join plan drafts to board cards by phase, sequence, and title. Page all reads. Before dispatching each card:

1. Call `get_task` and verify that `description` is complete and `write_files` is non-empty. When the description is not self-contained, or the declared scope does not match the work the card actually needs (a file a downstream card depends on, a stub module, a test file), call `update_task` to correct the card — it is accepted only while the card is `pending`/`ready` with no live lease — then continue. Never carry the correction in the dispatch stub: the card is the single copy of the contract (State 2).
2. Verify relationships and unfinished blockers. Only `ready` cards are dispatchable.
3. Check active workspaces and claimed tasks for collisions.
4. Call `get_overlap_report` for exactly the candidate wave, freshly, before every dispatch without exception. The report is server-computed from the cards' own `write_files`; an earlier wave's report, a report for a different task set, or your own reading of the file lists authorizes nothing. Refuse to dispatch a wave you have not run this report for — it is the structural replacement for a hand-written overlap analysis, so you no longer write one and no longer get to skip one. A report computed before an amendment is stale: re-run it after any `update_task`.
5. If `unscoped` is non-empty the report is never `parallel_safe`. Declare that card's `write_files` or schedule it sequentially; an undeclared write scope is not a disjoint one.
6. If `overlaps` contains a pair, split the pair across waves or run it sequentially. Only `parallel_safe:true` authorizes parallel worktrees.

Record each wave with `record_wave` using a one-based sequence, exact `task_ids`, and the current `WAVE_BASE` as `base_sha`, then mark it `running`.

## State 4 — Build and validate

Record `PHASE_BASE` once before the phase's first implementation and `WAVE_BASE` before each wave. These are main-loop git reads and recovery-critical values.

Select a host model tier by the portable registry, not a concrete identifier: `trivial`/`simple` normally use `fast`, `moderate` uses `balanced`, and `complex`/`epic` use `deep`. Raise a tier after a failed validation; never hardcode a vendor model.

Use the host capability contract in [Host capabilities](references/host-capabilities.md):

- a parallel-safe set uses `git.create_worktree`, then one `agent.dispatch` per card and `agent.wait` for results;
- overlapping or single-card work runs sequentially and must not race the working branch;
- dispatch only the identity stub: `project_id`, `task_id`, exact `agent_name`, the worker surface to call, worktree path, branch, base branch/SHA, lease TTL, the lifecycle steps, and verification/doc-routing context. Do not paste a second copy of the spec — the card is the contract (State 2), and the stub carries only what the card cannot know.
- the wave dispatch additionally carries each card's objective, acceptance criteria, and authoritative write scope for the program's **validator stage** — the task validator is forbidden the MCP surface and fails closed without explicit criteria, so the conductor, who verified the card in State 3, supplies them. This is validator input taken from the card at dispatch time, not a second spec copy: it never reaches the implementor, whose single spec remains the card fetched via `start_task`.

Dispatch the stub as a role whose declared tool grant is the worker surface and nothing more (Invariant 11). Naming the worker surface in the stub text is an instruction; the grant is the boundary.

Size worker TTL by task complexity: `simple` 1800, `moderate` 3600, `complex` 7200, `epic` 14400 seconds; choose a bounded TTL for `trivial`. The service default (900 seconds) is a crash-recovery guarantee, not a work budget — an implementor running a full build and test cycle outlives it and is reaped mid-task.

### Worker-owned segment

Each implementor uses only the worker surface and performs, in order:

1. `start_task` under its exact `agent_name` and sized `lease_ttl_secs`, with task, worktree path, branch, base branch, and base SHA — the composite of `claim_task` + `get_task` + `register_worktree` + `update_task_status(executing)`, folding the `queued` hop into the claim so the walk no longer writes it as a separate step. Verify the response's granted lease TTL and each embedded step's own outcome: stop if the returned spec or scope differs from dispatch identity, and if the granted TTL is lower than instructed, call `renew_task_lease` immediately **with** `lease_ttl_secs` — an explicit TTL is what resizes a lease, and this sizing and non-shrinking-renewal rule carries over verbatim from a bare `claim_task` into `start_task`'s TTL argument.
2. Implement only `write_files`; narrate stages with `post_progress_message`, and renew immediately before every long verification stretch, not once it is overdue.
3. Verify and commit, then call `finish_task` — the composite of `record_commits` + `record_task_summary` + `update_worktree_status(idle)` + `update_task_status(in_review)`.
4. Retain the lease. Do not write `validated`/`completed` and do not release.

The individual atomic tools (`claim_task`, `get_task`, `register_worktree`, `update_task_status`, `record_commits`, `update_worktree_status`, `renew_task_lease`) remain available for narration, mid-task renewal, and recovering from a partial composite failure — the composites are the instructed default call pattern, not a removal of the underlying tools.

The walk ends at `in_review` with the lease still held, because a lease — never a release — is what carries a mid-walk card between actors: a card is claimable only while `ready`, the server refuses a mid-walk release, and `in_review`/`validated` are carved out of lease reaping so the handoff handle survives however long validation, merge, and gates take. Status writes and a bare `renew_task_lease` renew non-shrinkingly: they keep a longer deadline and otherwise guarantee only the service floor, so do the arithmetic before a long stage and resize explicitly when the stretch may outlive the remaining lease. Progress narration and the summary write do not renew at all.

### Conductor-owned segment

For each returned worker:

1. Reconcile card status, lease name, workspace row, commits, summary, and containment. Missing durable bookkeeping is a gap to repair explicitly, not a reason to guess. A worker's own containment report is a claim, not evidence: inspect the primary checkout's status and its diff against `WAVE_BASE` before merging, and never use cleanup, reset, checkout, or deletion to make an unexpected change disappear — compare it with the task's branch, preserve it, and pause if it diverges.
2. Run a registered task validator over the exact base-to-branch diff and acceptance criteria.
3. Persist a wave's task checks with `record_gate_results` and its validator verdicts with `record_task_verdicts` — batched calls are the instructed default for a wave's worth of writes; check every entry's outcome in the response's `results` individually, by index, before proceeding — a batch response is not a single success. Use the singular `record_gate_result`/`record_task_verdict` only for a one-off write outside a wave.
4. On `pass`, write `validated` under the worker's `agent_name` before merging — `update_task_statuses` when multiple cards move together in the same wave, `update_task_status` for one, again checking each entry's outcome individually. On `concern` or `fail`, leave it unmerged, move it to `needs_rework`, mark the wave blocked, preserve its branch, and pause.
5. Merge passing branches in task order using main-loop git capabilities. Stop on conflict, record workspace conflict state, and preserve evidence.
6. Replay commit mappings with the merged SHA and update workspace state through `merged` and `removed` as the git operations complete.
7. Run the integration verifier over `WAVE_BASE..HEAD`. Persist task- or phase-scoped gate results under unique stable names such as `wave-<n>-integration-build`. Gate writes **upsert by (scope, name)**, so a reused name silently erases the previous wave's verdict: read the existing gate names from `get_pipeline_state` and derive the next ordinal rather than overwriting history.
8. After all required integration gates pass, write `completed` under the worker's `agent_name` — `update_task_statuses` when the wave completes multiple cards together, checking each entry's outcome individually. The batched ack is deliberately minimal (`id`/`status`/`updated_at` per entry only) and never carries `column_move_skipped`/`blocking_task_ids`; inspect that signal with the singular `update_task_status` per task, which reports it when present, or with a follow-up `get_task`/`get_pipeline_state` read. Then `release_task`. Mark the wave `merged`.

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

1. `record_review_round` at round `0`, scoped to the phase or plan, with normalized verdict, reviewed SHA, and summary. Review and implementation programs return their own spellings of verdict and status; map them onto the review-verdict and task-verdict enums before the call (Invariant 12). Round numbers are unique per scope — reusing one is refused, not merged.
2. File a round's confirmed findings with `add_action_items` — the instructed default for a review round's worth of findings, including Minor ones, linked to the review round and task when known; check each entry's outcome in the response's `results` individually, by index. Use the singular `add_action_item` only for a one-off finding filed outside a round. Keep each title short enough to name the finding (120 characters is the system's own truncation point for a title, in `get_pipeline_state`'s summary view) and put every other detail — evidence, file references, remediation notes — in `body`; see [Action-item payloads](ACTION_ITEMS_TEMPLATE.md) for the rule and a worked example.
3. Do not write a local review ledger. `get_pipeline_state` and the latest review round are authoritative.

Use [Review payloads](review-templates.md) and [Action-item payloads](ACTION_ITEMS_TEMPLATE.md).

## State 7 — Exact two-round follow-up ratchet

Call `get_pipeline_state` before every decision and read the latest round for the exact scope.

Before dispatching new follow-up investigation, check `search_context` for prior art on the same finding — snippet first, full fetch only for the diagnosis that matches — so a contested or not-reproduced result from an earlier round is not investigated again from nothing. Once a specific action item or artifact is the thing a follow-up round is acting on, read it in full.

| Latest verdict | Action |
|---|---|
| `approved` | Report. |
| `approved_with_concerns` | Mark remaining Minor items `deferred`; report. This is passing and terminal. |
| `needs_work` / `rejected`, latest round 0 | Round 1 targets confirmed Critical and Major findings. |
| `needs_work` / `rejected`, latest round 1 | Round 2 targets only unresolved or newly introduced Critical findings. Defer Major and Minor items. |
| Any non-passing verdict at round 2 | Stop and escalate. Round 3 is forbidden. |

For each eligible round:

1. Dispatch follow-up investigation for only the in-scope findings.
2. Persist contested and not-reproduced diagnoses with `record_research_artifact`, scoped with the reviewed plan's `plan_id` and `phase_id` so they appear with the plan's research. If no taskable diagnoses remain, stop and escalate.
3. Create fix cards on the same board with exact `write_files`, complexity, and `action_item_id`. There is no new plan approval gate.
4. Re-enter State 3 and State 4 for those cards only, including a fresh overlap report and wave. Never recursively review the fix wave as a new phase.
5. Re-review the original `<PHASE_BASE>..HEAD` in convergence mode using the previous review as context. Record round `1` or `2`.
6. Update existing action items to `resolved`, `deferred`, `wont_fix`, or back to `open`; never re-file the same finding.

Stop early if the same blocking finding survives two consecutive reviews, the verdict does not improve, no taskable fix exists, a fix changes an approved design decision, or any required task specification/base cannot be recovered unambiguously.

### Convergence at the cap

Reaching the cap with findings still open is an expected outcome, not a failure of the ratchet, and it has one documented resolution: **conductor inline remediation**, performed in the main loop rather than as a third round.

1. Report the cap to the human with the surviving findings and their severities, and remediate only what they authorize.
2. Fix each authorized finding inline in the main loop — a bounded, reviewed-by-you edit on the working branch, not a new wave, not a new plan, and never a new review round.
3. Hold inline fixes to the same evidence bar as a wave: run the repository's verification commands, persist each check with `record_gate_result`, and record a task verdict against the card the fix belongs to when one exists.
4. Converge the ledger with `update_action_item` — `resolved` with the landing commit, or `deferred`/`wont_fix` with the reason. Never re-file a finding that already exists.
5. Report the phase as converged with escalation, naming every finding that was remediated inline and every one left open. Converging this way is a weaker result than converging inside the cap — it carries no independent review of the fixes — and the report must say so rather than presenting the two as equivalent.

A fix that is too large to remediate inline is not a cap exception: it is the next plan's first task.

## State 8 — Report

Read final state from Zabin and git. Report the pinned project id, plan/board/phase ids, task counts and blockers, waves, source and merged commits, gates, latest review verdict/round, follow-up count, any inline remediation performed at the cap, deferred or `wont_fix` findings, documentation routing, and capability limitations.

Never reconstruct the report from conversation memory or local Markdown.

### Optional close-out: complete_plan

Plan completion is a distinct, human-gated step, never a routine part of reporting. Only on explicit user request — never automatically — call `complete_plan` with `completed_by` set to the conductor's own identity, after delivering the report. If the latest review verdict is `approved` or `approved_with_concerns` and every task on the plan reached `completed`, no `allow_incomplete` is needed. Using `allow_incomplete` to override the unfinished-task guard requires naming every incomplete task in the report before making the call. A worker never calls `complete_plan`; its walk ends at `in_review` and never touches plans.
