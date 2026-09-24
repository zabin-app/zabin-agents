# Concrete MCP Payload Examples

Each JSON object below is the `arguments` value for the named public MCP tool. Replace example ids and repository data; keep the field names and strict vocabulary. Runtime-discovered schemas take precedence if the service evolves.

## Startup

`get_server_info`

```json
{}
```

`resolve_project`

```json
{
  "path": "/srv/work/refresh-rotation"
}
```

`get_pickup_context`

```json
{
  "project_id": "prj_example"
}
```

`get_pipeline_state`

```json
{
  "project_id": "prj_example",
  "plan_id": "fplan_example",
  "max_phases": 25,
  "detail": "summary"
}
```

`detail` defaults to `full`; pass `"summary"` for routine orientation reads and reserve `"full"` for phase boundaries and review synthesis, where the trimmed fields (gate command/recorded_by/timestamp, review summary text, wave label/base_sha) are load-bearing.

`list_tasks`

```json
{
  "project_id": "prj_example",
  "phase_id": "pph_example",
  "status": "ready",
  "limit": 50,
  "offset": 0
}
```

Filter `status` to the live states this run needs (`ready`, `executing`, `in_review`, `needs_rework`, `validated`); follow `next_offset` within that filter until absent. Do not page an unfiltered `list_tasks` to completion at orient — that walks the project's entire completed history for no decision this state needs.

`list_workspaces`

```json
{
  "project_id": "prj_example",
  "status": "active",
  "limit": 50,
  "offset": 0
}
```

Filter to `active`/`idle` for routine orientation; widen only when reconciling a specific gap. Apply the same filtered-paging discipline to `get_plan` and other paged reads.

## Research

`record_research_artifact` — State 1 research predates the plan, so it is recorded without `plan_id` and its returned `artifact_id` is carried into `create_plan_draft`. Research recorded once the plan exists takes its `plan_id`, as here:

```json
{
  "project_id": "prj_example",
  "plan_id": "fplan_example",
  "kind": "sweep",
  "title": "Refresh-token rotation research",
  "body": "verified: storage transaction owns atomic consumption; contested: compatibility window duration; refuted: HTTP handlers parse tokens directly"
}
```

`attach_file`

```json
{
  "project_id": "prj_example",
  "owner": "plan",
  "owner_id": "fplan_example",
  "filename": "rotation-race-evidence.json",
  "mime_type": "application/json",
  "content_base64": "eyJjb25jdXJyZW50X3JlcXVlc3RzIjoyfQ=="
}
```

## Link research to its plan

`create_plan_draft` — carry every State 1 artifact into the plan shell; the ids are validated before the plan row exists:

```json
{
  "project_id": "prj_example",
  "title": "Rotate refresh tokens safely",
  "description": "Add one-time refresh-token rotation with replay detection.",
  "research_artifact_ids": ["rsa_example_sweep", "rsa_example_question"]
}
```

`link_research_artifacts` — attach existing artifacts to an existing plan (1–50 ids, same project; idempotent: the response splits `linked` from `already_linked`):

```json
{
  "project_id": "prj_example",
  "plan_id": "fplan_example",
  "artifact_ids": ["rsa_example_verification"],
  "linked_by": "conductor"
}
```

`finalize_plan` with a waiver — only for a plan that genuinely had no research; without research and without this field the call is refused `failed_precondition`:

```json
{
  "project_id": "prj_example",
  "plan_id": "fplan_example",
  "no_research_reason": "One-line typo fix requested directly by the user; no investigation was needed."
}
```

The reason is recorded as a plan-scoped `summary` artifact titled "No pre-plan research recorded" and reported back as `research_waiver_artifact_id`. A reason supplied for a plan that already has research is ignored and noted.

## Human design question

`ask_user_questions`

```json
{
  "project_id": "prj_example",
  "questions": [
    {
      "prompt": "Which compatibility window should the migration preserve?",
      "options": ["No overlap", "24 hours", "One release"]
    }
  ]
}
```

Questionnaire answers inform design but never constitute plan approval.

## Task specification and overlap gate

`get_task`

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation"
}
```

`get_overlap_report`

```json
{
  "project_id": "prj_example",
  "task_ids": ["tsk_rotation", "tsk_metrics"]
}
```

Supply exactly one selector: `task_ids` or `board_id`.

`update_task` — correct a card's declared scope before dispatch (here: a stub module the plan draft left undeclared); `description` and `complexity` are omitted and stay as they are

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "write_files": ["src/rotation/mod.rs", "src/rotation/consume.rs", "tests/rotation.rs"]
}
```

The reply carries `previous_write_files` (the scope any earlier dispatch decision was based on) and `amended_at`/`amended_by`; re-run `get_overlap_report` afterwards, because a report computed before the amendment is stale. Accepted only while the card is `pending`/`ready` with no live lease — `conflict` on a held lease or when the card changed between the tool's own read and its write (re-read and retry; an earlier `get_task` is not a guard), `failed_precondition` once the card is past `ready`.

## Record a wave

`record_wave`

```json
{
  "project_id": "prj_example",
  "phase_id": "pph_example",
  "sequence": 1,
  "label": "Parallel-safe storage and telemetry tasks",
  "base_sha": "42a4056677e5bcdc00b42dcb62cfa4cf0d4ddbb1",
  "task_ids": ["tsk_rotation", "tsk_metrics"]
}
```

`update_wave_status`

```json
{
  "project_id": "prj_example",
  "wave_id": "wav_example",
  "status": "running"
}
```

## Worker start: claim, spec, worktree, executing

`start_task` — the instructed default, composing `claim_task` + `get_task` + `register_worktree` + `update_task_status(executing)` in one call, folding the `queued` hop into the claim:

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "agent_name": "implementor@runner/task-05",
  "lease_ttl_secs": 7200,
  "path": "/srv/worktrees/task-05",
  "branch": "work/task-05",
  "base_branch": "feature/refresh-rotation",
  "base_sha": "42a4056677e5bcdc00b42dcb62cfa4cf0d4ddbb1"
}
```

Verify the response's granted `lease_ttl_seconds` matches the request, its embedded `get_task` spec's `write_files` matches the assignment boundary, and its embedded `register_worktree` step succeeded — each is a distinct failure mode, not one pass/fail bit. If the granted TTL is lower than requested, call `renew_task_lease` immediately **with** `lease_ttl_secs`. The individual atomic tools (`claim_task`, `get_task`, `register_worktree`, `update_task_status`) remain callable directly for recovery from a partial composite failure or for a host that has not adopted the composite.

## Worker narration and mid-task renewal

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "agent_name": "implementor@runner/task-05",
  "content": "Atomic rotation implementation complete; starting focused tests."
}
```

`renew_task_lease` before a long check

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "agent_name": "implementor@runner/task-05",
  "lease_ttl_secs": 7200
}
```

## Worker finish: commits, summary, idle worktree, in_review

`finish_task` — the instructed default, composing `record_commits` + `record_task_summary` + `update_worktree_status(idle)` + `update_task_status(in_review)` in one call:

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "agent_name": "implementor@runner/task-05",
  "worktree_id": "wkt_example",
  "commits": [
    {
      "sha": "b6be319eaa4a74903cfb5ddf52151be0fb93d256",
      "subject": "rotation: consume refresh tokens atomically"
    }
  ],
  "summary": "Implemented atomic refresh-token rotation in the two declared files. Focused tests and lint passed. Source commit b6be319eaa4a74903cfb5ddf52151be0fb93d256. No out-of-scope writes; documentation update needed for replay behavior."
}
```

The current surface preserves the worktree's SHA through the embedded `record_commits`; if a future discovered schema adds a current-SHA field, populate it from `git.inspect`. The worker retains the lease and returns. It does not write `validated` or `completed` and does not release. The individual atomic tools (`record_commits`, `record_task_summary`, `update_worktree_status`, `update_task_status`) remain callable directly for recovery from a partial composite failure.

## Conductor task verdict and validation hop

`record_gate_results` — the instructed default for a wave's gate set, up to 50 entries per call:

```json
{
  "project_id": "prj_example",
  "entries": [
    {
      "task_id": "tsk_rotation",
      "name": "task-focused-tests",
      "status": "passed",
      "detail": "24 tests passed; branch containment and write scope verified."
    },
    {
      "task_id": "tsk_metrics",
      "name": "task-focused-tests",
      "status": "passed",
      "detail": "9 tests passed; no out-of-scope writes."
    }
  ]
}
```

The response reports one outcome per entry, by index, in `results`: either `{ok: true, id, status, updated_at}` or `{ok: false, error_code, field, correction_hint}`. Check every index — one entry's failure does not stop or invalidate the rest, so a batch response is not a single success. Use singular `record_gate_result` only for a one-off gate outside a wave.

`record_task_verdicts` — same batching, for a wave's verdicts:

```json
{
  "project_id": "prj_example",
  "entries": [
    {
      "task_id": "tsk_rotation",
      "round": 0,
      "verdict": "pass",
      "detail": "All acceptance criteria met."
    },
    {
      "task_id": "tsk_metrics",
      "round": 0,
      "verdict": "pass",
      "detail": "All acceptance criteria met."
    }
  ]
}
```

Check each entry's `results[index]` before treating any task as validated. Use singular `record_task_verdict` only for a one-off.

`update_task_statuses` to `validated` before merge — batched when multiple cards move together, otherwise `update_task_status`:

```json
{
  "project_id": "prj_example",
  "entries": [
    {
      "task_id": "tsk_rotation",
      "agent_name": "implementor@runner/task-05",
      "status": "validated"
    },
    {
      "task_id": "tsk_metrics",
      "agent_name": "implementor@runner/task-06",
      "status": "validated"
    }
  ]
}
```

Again, check every entry's outcome in `results` by index before merging that task's branch.

## Conductor merged commit mapping

After the main loop lands the branch, call `record_commits` again with the mapping fields supported by the live schema:

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "worktree_id": "wkt_example",
  "commits": [
    {
      "sha": "b6be319eaa4a74903cfb5ddf52151be0fb93d256",
      "merged_sha": "ef60c2be9cc134bf472ee0d3747faf85515bf2f1",
      "subject": "rotation: consume refresh tokens atomically"
    }
  ]
}
```

Then transition the worktree through `merged` and `removed` as the corresponding main-loop git operations finish.

## Integration gate and terminal hop

`record_gate_result`

```json
{
  "project_id": "prj_example",
  "phase_id": "pph_example",
  "name": "wave-1-integration-tests",
  "status": "passed",
  "detail": "Full suite passed on ef60c2be9cc134bf472ee0d3747faf85515bf2f1."
}
```

`update_task_statuses` to `completed` after every required gate passes — batched when the wave completes multiple cards together, otherwise `update_task_status`:

```json
{
  "project_id": "prj_example",
  "entries": [
    {
      "task_id": "tsk_rotation",
      "agent_name": "implementor@runner/task-05",
      "status": "completed"
    },
    {
      "task_id": "tsk_metrics",
      "agent_name": "implementor@runner/task-06",
      "status": "completed"
    }
  ]
}
```

The batched ack above is minimal — `{ok, index, id, status, updated_at}` per entry, no `column_move_skipped` or `blocking_task_ids` — so when the blocker signal matters, follow up with the singular `update_task_status` (which reports it when present) or a `get_task`/`get_pipeline_state` read before calling `release_task`:

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "agent_name": "implementor@runner/task-05"
}
```

Finally mark the wave `merged`.

## Review round and action-item convergence

See [Review payloads](../review-templates.md) and [Action-item payloads](../ACTION_ITEMS_TEMPLATE.md). The initial review is round 0; follow-up rounds are exactly 1 and 2.

## Plan close-out (explicit user request only)

`complete_plan` — conductor-only, called after State 8 reporting on explicit user request, never automatically:

```json
{
  "project_id": "prj_example",
  "plan_id": "fplan_example",
  "completed_by": "conductor@runner/session-01",
  "expected_revision": "rev_7f3ec2d5e208664d"
}
```

`expected_revision` is optional but recommended when the last-read revision is known. Add `"allow_incomplete": true` only when the human has explicitly accepted leaving named tasks incomplete; the `unfinished-tasks` `failed_precondition` response names this override as its correction hint. A successful response returns `plan_id`, `project_id`, `status: "completed"`, `completed_by`, `completed_at`, `revision`, and `next_step`.
