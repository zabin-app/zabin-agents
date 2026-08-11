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
  "max_phases": 25
}
```

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

Follow `next_offset` until absent. Apply the same paging discipline to `list_workspaces`, `get_plan`, and other paged reads.

## Research

`record_research_artifact`

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

## Worker claim and authoritative spec read

`claim_task` on the worker surface

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "agent_name": "implementor@runner/task-05",
  "lease_ttl_secs": 7200
}
```

Verify the response returns the same agent and requested `lease_ttl_seconds`. Then call `get_task` and compare its `write_files` to the assignment boundary.

## Worker worktree registration

`register_worktree`

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "agent_name": "implementor@runner/task-05",
  "path": "/srv/worktrees/task-05",
  "branch": "work/task-05",
  "base_branch": "feature/refresh-rotation",
  "base_sha": "42a4056677e5bcdc00b42dcb62cfa4cf0d4ddbb1"
}
```

For a worktree on another machine, include `host` and `base_sha`. Retain the returned `worktree_id`.

## Worker status and narration

`update_task_status` to queued

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "agent_name": "implementor@runner/task-05",
  "status": "queued"
}
```

Repeat with `status:"executing"`, then later `status:"in_review"`.

`post_progress_message`

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

## Worker commit and idle worktree record

`record_commits`

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "worktree_id": "wkt_example",
  "commits": [
    {
      "sha": "b6be319eaa4a74903cfb5ddf52151be0fb93d256",
      "subject": "rotation: consume refresh tokens atomically"
    }
  ]
}
```

Mark the completed worktree idle before handoff:

```json
{
  "project_id": "prj_example",
  "worktree_id": "wkt_example",
  "agent_name": "implementor@runner/task-05",
  "status": "idle"
}
```

Call `update_worktree_status`. The current surface preserves the SHA through `record_commits`; if a future discovered schema adds a current-SHA field, populate it from `git.inspect`.

## Worker summary and handoff

After writing `in_review`, call `record_task_summary`:

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "agent_name": "implementor@runner/task-05",
  "summary": "Implemented atomic refresh-token rotation in the two declared files. Focused tests and lint passed. Source commit b6be319eaa4a74903cfb5ddf52151be0fb93d256. No out-of-scope writes; documentation update needed for replay behavior."
}
```

The worker retains the lease and returns. It does not write `validated` or `completed` and does not release.

## Conductor task verdict and validation hop

`record_gate_result`

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "name": "task-focused-tests",
  "status": "passed",
  "detail": "24 tests passed; branch containment and write scope verified."
}
```

`record_task_verdict`

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "round": 0,
  "verdict": "pass",
  "detail": "All acceptance criteria met."
}
```

`update_task_status` before merge

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "agent_name": "implementor@runner/task-05",
  "status": "validated"
}
```

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

`update_task_status` after every required gate passes

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_rotation",
  "agent_name": "implementor@runner/task-05",
  "status": "completed"
}
```

Inspect `blocking_task_ids`, then call `release_task`:

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
