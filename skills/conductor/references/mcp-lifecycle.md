# Zabin MCP Lifecycle

This reference defines the portable public-tool contract used by the conductor. Invoke public names through the host's MCP call capability; any qualification or transport binding belongs to the host adapter.

## Capability discovery

Begin with `get_server_info {}`. It returns the live tool inventory for both surfaces, and typically a fingerprint over that inventory. Treat both as this session's authoritative snapshot — cache it, require the operations needed for the selected path against it, and stop if the live inventory is incompatible. Do not hardcode a tool count or fingerprint value in instructions: the served surface changes as tools are added, split into batched forms, or retired, independently of this document, so a number written here goes stale the moment the surface moves. A fingerprint mismatch against a previously recorded value is evidence worth investigating, not proof of a break — re-run discovery and compare names, not digests.

## Conductor surface — full tool set

| Group | Public names |
|---|---|
| Project | `get_server_info`, `register_project`, `resolve_project`, `get_pickup_context` |
| Plan | `create_plan_draft`, `set_plan_section`, `add_phase`, `add_phase_tasks`, `finalize_plan`, `import_plan_document`, `get_plan`, `update_plan_document`, `create_board` |
| Task ledger | `list_tasks`, `get_task`, `claim_next_task`, `claim_task`, `release_task`, `renew_task_lease`, `update_task_status`, `update_task_statuses`, `record_task_summary`, `record_task_verdict`, `record_task_verdicts`, `record_gate_result`, `record_gate_results`, `record_review_round`, `add_action_item`, `add_action_items`, `update_action_item`, `create_tasks`, `record_wave`, `update_wave_status`, `get_overlap_report`, `record_research_artifact`, `get_pipeline_state`, `search_context` |
| Git ledger | `register_worktree`, `update_worktree_status`, `record_commits`, `list_workspaces` |
| Human interaction | `post_progress_message`, `ask_user_questions`, `get_question_answers` |
| Attachments | `attach_file`, `list_attachments`, `get_attachment`, `delete_attachment` |
| Graph/analysis | `start_analysis_run`, `upsert_graph_nodes`, `upsert_graph_edges`, `upsert_graph_layer`, `set_layer_tour`, `complete_analysis_run`, `get_graph_summary`, `query_graph` |

Graph/analysis tools belong to graph ingestion and are not part of the development pipeline state machine. The `s`-suffixed task-ledger names (`update_task_statuses`, `record_task_verdicts`, `record_gate_results`, `add_action_items`) are batched forms: up to 50 entries per call, each entry's outcome reported independently by index in the response, deliberately minimal on success (`id`/`status`/`updated_at` only — no `column_move_skipped` or `blocking_task_ids`, unlike the singular `update_task_status`) — see [Payload examples](payload-examples.md) and Gate ordering below for the per-entry-check discipline. `start_task` and `finish_task` are worker-surface composites (below); the conductor never calls them.

## Worker surface — strict subset

| Group | Public names |
|---|---|
| Task and lease | `get_task`, `claim_task`, `release_task`, `renew_task_lease`, `update_task_status`, `record_task_summary`, `list_tasks`, `search_context`, `start_task`, `finish_task` |
| Plan read | `get_plan` |
| Progress | `post_progress_message` |
| Git ledger | `register_worktree`, `update_worktree_status`, `record_commits`, `list_workspaces` |
| Attachments | `attach_file`, `list_attachments`, `get_attachment` |

`start_task` composes `claim_task` + `get_task` + `register_worktree` + `update_task_status(executing)`; `finish_task` composes `record_commits` + `record_task_summary` + `update_worktree_status(idle)` + `update_task_status(in_review)`. They are the instructed default call pattern for a worker's own walk (see SKILL.md's worker-owned segment); the atomic tools they wrap remain individually callable for narration, mid-task renewal, and recovering from a partial composite failure.

The subset excludes plan mutation, verdicts, gates, review rounds, action items, waves, overlap computation, project registration, and deletion — including their batched forms. A worker must be granted only this surface and task-scoped filesystem/git authority.

## Explicit identity

Every project-scoped call includes the same pinned `project_id`. `resolve_project` is a discovery operation, not ambient project selection. Every child id must be read from a response belonging to that project.

Project startup reads:

1. `get_server_info {}`;
2. optional `resolve_project {path}`;
3. `get_pickup_context {project_id}`;
4. `get_pipeline_state {project_id, detail:"summary"}` — routine reads stay at `summary`; use `detail:"full"` only at phase boundaries and review synthesis;
5. `list_tasks {project_id, status:...}` filtered to the live statuses the run needs (`ready`, `executing`, `in_review`, `needs_rework`, `validated`), paged within that filter — never an unfiltered page walk through completed history — and `list_workspaces {project_id, status:...}` filtered to `active`/`idle` unless reconciling a specific gap.

## Strict vocabularies

- Task complexity: `trivial`, `simple`, `moderate`, `complex`, `epic`.
- Task verdict: `pass`, `concern`, `fail`.
- Gate status: `pending`, `passed`, `failed`, `skipped`.
- Review verdict: `approved`, `approved_with_concerns`, `needs_work`, `rejected`.
- Severity: `critical`, `major`, `minor`.
- Action item: `open`, `deferred`, `resolved`, `wont_fix`.
- Wave: `pending`, `running`, `merged`, `blocked`, `abandoned`.
- Worktree: `active`, `idle`, `merged`, `conflict`, `removed`.
- Merge status: `pending`, `merged`, `conflict`, `skipped`.

Normalize external program output before MCP persistence. An off-list value is rejected, not stored.

## Plan lifecycle

The operational lifecycle is:

```text
draft --finalize_plan--> ready --human approval + create_board--> confirmed
```

The wire representation may expose `draft`, `active` (ready), and `completed` (confirmed). Approval is human-only and is verified with `get_plan.approved_by` and `approved_at`. A plan edit clears approval. `create_board` must use the revision just verified as `expected_revision`.

## Task status machine and ownership

```text
ready --worker claim--> queued --worker--> executing --worker--> in_review
in_review --conductor pass verdict--> validated
validated --conductor merge + gates--> completed --conductor release

in_review --validation concern/fail--> needs_rework --re-entry--> queued
validated --post-merge integration fail--> needs_rework --re-entry--> queued
```

`in_review -> completed` remains compatible when no discrete validation hop exists, but the conductor uses `validated` for the guarded merge window. `executing -> needs_rework` is illegal.

Workers pass through `queued`, `executing`, and `in_review`, and retain the lease at handoff. The instructed worker call pattern is `start_task` (which reaches `executing`, folding the `queued` hop into the claim rather than writing it as a separate status call) then `finish_task` (which reaches `in_review`); the individual `update_task_status` transitions these composites wrap remain legal calls in their own right. The conductor presents that exact worker `agent_name` for `validated`, `needs_rework`, `completed`, and release.

`update_task_status` may report `column_move_skipped` and `blocking_task_ids`, serialized only when meaningful — check for their presence rather than assuming they are always there. A skip indicates unfinished dependencies and must be investigated. `completed` always moves to the terminal column; a non-empty blocker list on a completed response signals out-of-order completion. The batched `update_task_statuses` does not carry either field per entry — its per-entry ack is `id`/`status`/`updated_at` only — so when a blocker signal matters, use the singular call or a follow-up read.

Existing boards may not have a column corresponding to every status. Absence of a mapped column is different from dependency-driven `column_move_skipped`; do not infer status from board column names.

## Lease model

`claim_task` accepts only a `ready` card. Its default TTL is crash recovery, not a normal work budget. Use explicit `lease_ttl_secs` and verify the returned `lease_ttl_seconds`.

- Implicit renewal from status writes or a bare `renew_task_lease` never shortens an existing longer deadline and guarantees at least the service floor.
- An explicit TTL resizes the deadline; use it immediately before long verification.
- `post_progress_message` and `record_task_summary` do not renew.
- `release_task` refuses a mid-walk card. Release is valid for an untouched `ready` claim or after terminal completion.
- Expired `queued`/`executing` leases are reaped and returned to `ready`.
- `in_review` and `validated` are not reaped. Their lease is the durable handoff handle through validation, merge, and integration.
- A lease conflict means another actor owns the card. Stop; never steal, release, or overwrite it.

## Gate ordering

The conductor closes a worker task in this order:

1. verify worker bookkeeping and containment;
2. persist task checks — `record_gate_results` for a wave's set, `record_gate_result` for a one-off;
3. persist verdicts — `record_task_verdicts` for a wave's set, `record_task_verdict` for a one-off;
4. on pass, write `validated` under the worker name — `update_task_statuses` when multiple cards move together, `update_task_status` for one;
5. merge in task order using host git capabilities;
6. record source-to-merged commit mappings and workspace transitions;
7. run and persist wave integration gates;
8. write `completed` (batched the same way when several cards complete together), inspect blockers, then release;
9. mark the wave `merged`.

Every batched call above reports one outcome per entry, by index, in its response — read each one before treating the batch as done; a batch response is not a single success. No branch with a `concern` or `fail` verdict is merged.

## Server-side boundaries

The MCP surface does not create, merge, rebase, remove, or clean worktrees; approve plans; create chat sessions; revoke another actor's lease; or make an unscoped task parallel-safe. Those responsibilities remain with the main loop or a human gate.
