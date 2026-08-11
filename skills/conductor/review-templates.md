# Review MCP Payload Recipes

These payloads replace feature-review, bug-review, quick-review, rejection, and review-ledger Markdown templates. Review agents return evidence; the conductor normalizes and persists it through the public MCP tools.

The latest scoped review round in `get_pipeline_state` is authoritative. Never maintain a local round counter.

## Normalize the synthesis

Before persistence, require:

- exact diff range and `reviewed_sha`;
- scope (`phase_id` or `plan_id`);
- verdict normalized to `approved`, `approved_with_concerns`, `needs_work`, or `rejected`;
- deduplicated, adversarially verified findings;
- each finding's severity (`critical`, `major`, or `minor`), title, body, file reference, and related task when known;
- explicit caveats for partial or missing reviewer results.

A missing review dimension fails toward caution. Never translate a partial result into approval without evidence.

## Record the initial review

Call `record_review_round` with round zero:

```json
{
  "project_id": "prj_example",
  "phase_id": "pph_example",
  "round": 0,
  "verdict": "needs_work",
  "reviewed_sha": "4f5ca08a0d61c860b94f6a6d68f1d3c5d09154ee",
  "summary": "Atomic rotation passes tests, but replay telemetry leaks a token prefix.",
  "review_ref": "zabin://attachments/review-round-0.json"
}
```

Use `plan_id` instead of `phase_id` for a plan-level review. Round numbers are append-only and unique within the scope.

## Persist the full review artifact

If the synthesized review is too detailed for the round summary, encode the structured result and attach it to the plan or owning task, then use that attachment reference as `review_ref`.

```json
{
  "project_id": "prj_example",
  "owner": "plan",
  "owner_id": "fplan_example",
  "filename": "review-round-0.json",
  "mime_type": "application/json",
  "content_base64": "eyJ2ZXJkaWN0IjoibmVlZHNfd29yayJ9"
}
```

Call `attach_file`. Do not put credentials, tokens, session ids, or unredacted command environments in an attachment.

## File each confirmed finding once

```json
{
  "project_id": "prj_example",
  "severity": "critical",
  "title": "Replay telemetry exposes token material",
  "body": "The replay log includes the first eight characters of the presented refresh token. Log only the stable token record id.",
  "file_ref": "src/domain/session.rs:188",
  "review_round_id": "rvr_example",
  "task_id": "tsk_example"
}
```

Call `add_action_item` once per finding, including Minor findings. Do not combine unrelated findings in one title and do not add the same finding again in a later round.

## Persist implementation and integration gates

Task-scoped verification:

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_example",
  "name": "task-unit-tests",
  "status": "passed",
  "detail": "24 session tests passed; 0 failed."
}
```

Wave integration verification uses phase scope and a unique wave-qualified name:

```json
{
  "project_id": "prj_example",
  "phase_id": "pph_example",
  "name": "wave-2-integration-tests",
  "status": "passed",
  "detail": "Full suite passed after merging wave 2."
}
```

Call `record_gate_result`. Supply exactly one of `task_id` and `phase_id`. Gate records upsert by scope and name, so reusing a prior wave's name destroys history.

## Record a worker verdict

```json
{
  "project_id": "prj_example",
  "task_id": "tsk_example",
  "round": 0,
  "verdict": "pass",
  "detail": "All acceptance criteria met; write scope and branch containment verified."
}
```

Call `record_task_verdict`. A `pass` is immediately followed by the conductor's `validated` status write under the worker's lease name, before merge. `concern` or `fail` stays unmerged and follows `needs_rework`.

## Record convergence rounds

Round 1 uses the same `record_review_round` shape with `round:1` and targets Critical plus Major findings from round 0. Round 2 uses `round:2` and targets only unresolved or newly introduced Critical findings after round 1.

```json
{
  "project_id": "prj_example",
  "phase_id": "pph_example",
  "round": 1,
  "verdict": "approved_with_concerns",
  "reviewed_sha": "ef60c2be9cc134bf472ee0d3747faf85515bf2f1",
  "summary": "Token material is removed; one Minor naming concern remains deferred.",
  "review_ref": "zabin://attachments/review-round-1.json"
}
```

The round-1 attachment carries the prior review reference and convergence evidence; `review_ref` points to the new round's own artifact.

## Verdict ratchet

| Latest round | In-scope follow-up | Terminal conditions |
|---|---|---|
| 0 | Critical + Major | `approved` or `approved_with_concerns` |
| 1 | Critical only | no Critical findings, or a passing verdict |
| 2 | none | always terminal; escalate if non-passing |

Minor findings never trigger a follow-up round. A non-improving verdict, the same blocker twice, no taskable diagnosis, or an approved-design change stops the ratchet early.
