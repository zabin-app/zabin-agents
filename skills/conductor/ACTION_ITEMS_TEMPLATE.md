# Action-Item MCP Payload Recipes

Action items are durable Zabin records, not an `ACTION_ITEMS.md` checklist. Create one record per confirmed review finding and update that same record across follow-up rounds.

## Title rule

`title` is a short name for the finding, not the finding itself: **120 characters or fewer** (the same point `get_pipeline_state`'s summary view truncates an open finding's title, flagging `title_truncated` — write short enough that this never triggers) and it names one finding only. Every fact that supports the finding — evidence, reasoning, exact behavior, suggested fix — goes in `body`, which has no such limit. Do not combine unrelated findings into one title; file each as its own entry instead.

Compare:

- Good: `title: "Refresh-token replay leaks credential material"`, with the mechanism, evidence, and fix in `body` (see the example below).
- Bad: `title: "Replay telemetry logs the first eight characters of the presented refresh token instead of the stable token record id, which could let an attacker with log access reconstruct enough of a token to replay it and also the fix should add a regression test"` — this is a body pasted where a title belongs; a summary read truncates it at 120 characters, silently dropping the fix instruction and half the mechanism.

## File a round's findings, batched

`add_action_items` — the instructed default for a review round's worth of findings, including Minor ones:

```json
{
  "project_id": "prj_example",
  "entries": [
    {
      "severity": "critical",
      "title": "Refresh-token replay leaks credential material",
      "body": "Replay telemetry logs a token prefix. Replace it with the stable record id and add a regression assertion.",
      "file_ref": "src/domain/session.rs:188",
      "review_round_id": "rvr_round_0",
      "task_id": "tsk_rotation"
    },
    {
      "severity": "minor",
      "title": "Clarify replay metric name",
      "body": "The metric name does not distinguish replay rejection from expiration.",
      "file_ref": "src/telemetry/session_metrics.rs:24",
      "review_round_id": "rvr_round_0"
    }
  ]
}
```

Check each entry's outcome in the response's `results` individually, by index — either `{ok: true, index, id, status, updated_at}` or `{ok: false, index, error_code, field, correction_hint}` — before treating any finding as filed; a batch response is not a single success. The created record defaults to `open`. Critical and Major items from round 0 are eligible for round 1. Minor items are recorded but never trigger a round.

## Create a single item

Use singular `add_action_item` only for a one-off finding filed outside a round:

```json
{
  "project_id": "prj_example",
  "severity": "critical",
  "title": "Refresh-token replay leaks credential material",
  "body": "Replay telemetry logs a token prefix. Replace it with the stable record id and add a regression assertion.",
  "file_ref": "src/domain/session.rs:188",
  "review_round_id": "rvr_round_0",
  "task_id": "tsk_rotation"
}
```

## Link a fix card

Create a task on the existing board with the action item id:

```json
{
  "project_id": "prj_example",
  "board_id": "brd_example",
  "tasks": [
    {
      "title": "Remove token material from replay telemetry",
      "description": "Objective: log only stable token-record identity on replay. Acceptance: no presented token bytes reach logs; replay outcome remains observable; regression test covers structured logging. Read dependency: the round-0 review artifact. Verification: run session tests and repository lint.",
      "complexity": "moderate",
      "labels": ["security", "followup"],
      "write_files": [
        "src/domain/session.rs",
        "tests/session_service.rs"
      ],
      "action_item_id": "act_example"
    }
  ]
}
```

Call `create_tasks`. Follow-up tasks reuse the board and still require specification and overlap gates.

## Resolve after verified convergence

```json
{
  "project_id": "prj_example",
  "action_item_id": "act_example",
  "status": "resolved",
  "resolution_note": "Fixed by merged commit ef60c2be9cc134bf472ee0d3747faf85515bf2f1; convergence review round 1 confirmed no token material is logged."
}
```

Call `update_action_item` only after the re-review confirms the finding is fixed.

## Defer a passing concern

```json
{
  "project_id": "prj_example",
  "action_item_id": "act_minor",
  "status": "deferred",
  "resolution_note": "Minor naming concern accepted for later cleanup; review round 1 is approved_with_concerns."
}
```

`approved_with_concerns` is passing and terminal. Deferring a Minor item does not open another round.

## Record an intentional non-fix

```json
{
  "project_id": "prj_example",
  "action_item_id": "act_example",
  "status": "wont_fix",
  "resolution_note": "The proposed change conflicts with the human-approved compatibility decision recorded on plan fplan_example."
}
```

Use `wont_fix` only with a durable reason. If the change would revise approved design, stop the ratchet and request a new decision.

## Reopen a surviving finding

```json
{
  "project_id": "prj_example",
  "action_item_id": "act_example",
  "status": "open",
  "resolution_note": "Round 1 reproduced the original leak in the structured error path; the item remains blocking."
}
```

Never call `add_action_item` again for the same finding. Updates preserve its original review evidence and make convergence auditable.
