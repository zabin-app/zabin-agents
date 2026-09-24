# Planning MCP Payload Recipes

These payloads replace plan, task-index, task-file, and overlap-matrix Markdown templates. Substitute ids and repository-grounded content, then invoke the public MCP tool name with the shown argument object. Every project-scoped payload carries `project_id` explicitly.

See [Payload examples](references/payload-examples.md) for lifecycle calls and [MCP lifecycle](references/mcp-lifecycle.md) for strict vocabularies.

## Persist research before planning

```json
{
  "project_id": "prj_example",
  "kind": "sweep",
  "title": "Authentication boundary research",
  "body": "verified: middleware owns token parsing (src/http/auth.rs:41); contested: refresh rotation ownership; refuted: handlers parse bearer tokens",
  "phase_id": "pph_example"
}
```

Call `record_research_artifact` and keep every returned `rsa_…` id. State 1 research normally predates the plan, so it is recorded without `plan_id`; nothing links it later unless you carry the ids into the plan shell below. Research recorded after the draft exists takes the returned `plan_id` (and `phase_id` once a phase exists).

## Create the plan shell

```json
{
  "project_id": "prj_example",
  "title": "Rotate refresh tokens safely",
  "description": "Add one-time refresh-token rotation with replay detection.",
  "research_artifact_ids": ["rsa_example_sweep", "rsa_example_question"]
}
```

Call `create_plan_draft` with every State 1 artifact id in `research_artifact_ids` and retain the returned `plan_id` and revision. The ids are validated before the plan exists, so a wrong id refuses the call without leaving a draft. The plan's Docs view lists exactly the research linked here, recorded with its `plan_id`, or linked later with `link_research_artifacts`.

## Set scalar and list sections

Scalar section with `set_plan_section`:

```json
{
  "project_id": "prj_example",
  "plan_id": "fplan_example",
  "section": "tldr",
  "action": "set",
  "content": {
    "text": "Rotate refresh tokens atomically and reject replayed tokens."
  }
}
```

List section:

```json
{
  "project_id": "prj_example",
  "plan_id": "fplan_example",
  "section": "risks",
  "action": "set",
  "content": {
    "items": [
      "Concurrent refreshes must have one winner.",
      "Existing sessions need a documented migration path."
    ]
  }
}
```

Use `content.modules` for the `modules` section. Supported actions are `set`, `append`, and `clear`; `clear` needs no section content.

## Add a phase

```json
{
  "project_id": "prj_example",
  "plan_id": "fplan_example",
  "phase": {
    "title": "Rotation domain and persistence",
    "goal": "Make token consumption atomic and observable.",
    "milestone": "Concurrent refresh requests produce exactly one successor token.",
    "steps": [
      "Add the rotation transaction.",
      "Expose replay outcome to the service layer.",
      "Cover concurrency and migration cases."
    ]
  }
}
```

Call `add_phase`. Phase task dependency indices are zero-based and local to the phase.

## Add complete task drafts

```json
{
  "project_id": "prj_example",
  "plan_id": "fplan_example",
  "phase_index": 0,
  "tasks": [
    {
      "title": "Implement atomic refresh rotation",
      "description": "Objective: consume a refresh token and insert its successor in one transaction. Acceptance: two concurrent consumers yield one success and one replay error; rollback leaves the original usable; existing repository error mapping is preserved. Write only the declared files. Read dependencies: src/domain/session.rs and docs/DEVELOPMENT.md. Verification: run the repository unit-test and lint commands documented for this module.",
      "complexity": "complex",
      "effort": "1 day",
      "labels": ["backend", "security"],
      "write_files": [
        "src/storage/refresh_tokens.rs",
        "tests/refresh_rotation.rs"
      ],
      "depends_on": []
    },
    {
      "title": "Wire replay outcome into the session service",
      "description": "Objective: translate the storage replay outcome through the existing session service. Acceptance: callers receive the established replay error and unrelated errors are unchanged. Read dependency: src/storage/refresh_tokens.rs. Verification: run session-service tests and the repository lint command.",
      "complexity": "moderate",
      "write_files": [
        "src/domain/session.rs",
        "tests/session_service.rs"
      ],
      "depends_on": [0]
    }
  ]
}
```

Call `add_phase_tasks`. Reject a draft that lacks a self-contained description or non-empty `write_files`.

## Finalize and wait for approval

```json
{
  "project_id": "prj_example",
  "plan_id": "fplan_example"
}
```

`finalize_plan` refuses (`failed_precondition`) a draft with no research linked or recorded against it. Link what State 1 produced rather than waiving: `link_research_artifacts {project_id, plan_id, artifact_ids}` attaches existing artifacts and is idempotent. Only a plan that genuinely had no research passes `"no_research_reason": "<why>"`; the server records that reason as a plan-scoped `summary` artifact titled "No pre-plan research recorded", so the operator sees it.

Call `finalize_plan`, pause for human approval, then confirm approval with the minimal approval-check read:

```json
{
  "project_id": "prj_example",
  "plan_id": "fplan_example",
  "sections": [],
  "include_task_drafts": false
}
```

Call `get_plan` with both fields set this way to shrink the response to `approved_by`, `approved_at`, and the current revision — no prose sections, no phase or task-draft payload. Require both `approved_by` and `approved_at` set before proceeding.

## Materialize the approved plan

```json
{
  "project_id": "prj_example",
  "plan_id": "fplan_example",
  "name": "Refresh-token rotation",
  "expected_revision": "7"
}
```

Call `create_board` only after the authoritative approval read. A revision conflict requires a re-read; it is not safe to drop `expected_revision`.

## Verify materialized cards

For every intended card, call `get_task`:

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_example"
}
```

Confirm description, write scope, status, relationships, and subtasks from the response. Page `list_tasks` filtered to `ready` (the only dispatchable status) and `list_workspaces` filtered to `active`/`idle` before scheduling — not an unfiltered walk through the whole board.

## Ask the server for overlap

```json
{
  "project_id": "prj_example",
  "task_ids": ["tsk_first", "tsk_second"]
}
```

Call `get_overlap_report` before every dispatch. `parallel_safe:true` authorizes parallel worktrees. Any `overlaps` pair must be separated; any `unscoped` task must be re-scoped or run sequentially.

## Add ad-hoc, fix, or documentation tasks

```json
{
  "project_id": "prj_example",
  "board_id": "brd_example",
  "tasks": [
    {
      "title": "Document refresh-token replay handling",
      "description": "Update the project security and development documentation from the accepted implementation evidence. Acceptance: behavior, verification command, and migration note match the landed code. This is a core-doc task and must be routed to the documentation-maintainer role.",
      "complexity": "simple",
      "labels": ["docs"],
      "write_files": [
        "docs/ARCHITECTURE.md",
        "docs/DEVELOPMENT.md"
      ]
    }
  ]
}
```

Call `create_tasks`. For a review fix, include the finding's `action_item_id` in that task object. Reuse the existing board; do not create a new plan for a follow-up round.
