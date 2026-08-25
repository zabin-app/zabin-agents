# Follow-up Investigate

Diagnose confirmed Critical and Major review findings, then cross-check each diagnosis before creating a fix card. The conductor main loop owns fan-out and synthesis; children receive no orchestration capabilities.

## Host capability contract

- `spawn-role(envelope)` dispatches a registered `codebase_researcher`. Its closed `role_input` is separate from host tier, directory, timeout, and correlation metadata.
- `spawn-ad-hoc(input, capability-tier, working-directory)` is available only if the role registry has no suitable bounded cross-check; the normal path uses `spawn-role`.
- `await-result(dispatch-id)` returns a structured completion, failure, or timeout.
- `cancel(dispatch-id)` requests cancellation after the wait policy expires.
- `working-directory(path)` supplies read-only repository context.
- `validate-schema(value, schema)` validates input, diagnoses, cross-checks, and every return path.

Investigation and cross-check use the `balanced` capability tier. The host resolves the portable tier; runtime-specific identifiers are forbidden.

Every registered dispatch uses the exact role input illustrated below.

## Registered role-input walkthrough

```json
{"codebase_researcher":{"objective":"Reproduce and diagnose action item act_example","scope":["src/session.rs"],"context":{"finding":"full finding text"}}}
```

Only `objective`, `scope`, and optional `context` enter `role_input`, matching `codebase_researcher.input_schema`. Role, `balanced` tier, `working_directory`, timeout, issue/action-item correlation, and the expected registered output schema are host-envelope metadata.

## Retrieval before dispatch

Before building an issue's `role_input`, run 1-2 `search_context` queries
scoped to the finding — e.g. `search_context(project_id, "action item
act_042 clipboard OSC 52 duplicate write")` — to check whether this finding,
or one like it, was already diagnosed: a prior research artifact, a
`contested` or `not_reproduced` diagnosis from an earlier round, or a
related action item. This is two-stage: a snippet plus
`source_type`/`source_id` first, a full fetch (`get_task`, the artifact, or
the action item's own round) only for the hit that matches. A keyword-only
note in the response means BM25-only degradation — still usable, mention it
in the diagnosis's evidence.

This locates prior art before dispatch; it does not replace enumeration (the
open/deferred action-item list still comes from the listing surface, not
from search hits) and it does not replace the investigator's own
reproduction — which reads the actual code the finding names — nor the full
`get_task`/action-item read for the issue currently being diagnosed.

## Input schema

```json
{
  "type": "object",
  "required": ["project_id", "phase_id", "review_round_id", "repository", "issues"],
  "properties": {
    "project_id": {"type": "string", "minLength": 1},
    "phase_id": {"type": "string", "minLength": 1},
    "review_round_id": {"type": "string", "minLength": 1},
    "repository": {"type": "string", "minLength": 1},
    "issues": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["action_item_id", "label", "severity", "finding"],
        "properties": {
          "action_item_id": {"type": "string", "minLength": 1},
          "label": {"type": "string", "minLength": 1},
          "severity": {"enum": ["critical", "major"]},
          "finding": {"type": "string", "minLength": 1},
          "file_ref": {"type": "string"}
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

## Child result schemas

The investigator first returns the registered research-role output contract. The conductor then normalizes its summary/evidence/caveats plus the issue identity into this diagnosis schema and validates it separately:

```json
{
  "type": "object",
  "required": ["action_item_id", "confirmed", "root_cause", "evidence", "fix_approach", "files_to_change", "regression_risk"],
  "properties": {
    "action_item_id": {"type": "string"},
    "confirmed": {"type": "boolean"},
    "root_cause": {"type": "string"},
    "evidence": {"type": "array", "items": {"type": "string"}},
    "fix_approach": {"type": "string"},
    "files_to_change": {"type": "array", "items": {"type": "string"}},
    "regression_risk": {"type": "string"}
  },
  "additionalProperties": false
}
```

A cross-check returns:

```json
{
  "type": "object",
  "required": ["refuted", "reasoning", "evidence", "correction"],
  "properties": {
    "refuted": {"type": "boolean"},
    "reasoning": {"type": "string"},
    "evidence": {"type": "array", "items": {"type": "string"}},
    "correction": {"type": "string"}
  },
  "additionalProperties": false
}
```

## Procedure

1. Validate input. Invalid input returns the fail-closed invalid result below.
2. If `issues` is empty, return a schema-valid complete result with empty arrays.
3. For every issue, build only `objective`, `scope`, and optional `context`; validate that closed object against `codebase_researcher.input_schema`. Put role, `balanced` tier, `working-directory(repository)`, timeout, and correlation data in the host envelope and call `spawn-role(envelope)`. Ask it to reproduce before diagnosing. It may read but not write or orchestrate.
4. Spawn all investigators before awaiting. On timeout request `cancel`; preserve the issue as contested, not as not reproduced.
5. Validate the untouched child result against `codebase_researcher.output_schema`. The conductor alone transforms that registered result plus issue identity into a distinct diagnosis object, then validates the diagnosis schema. Only an evidence-backed normalized `confirmed: false` result is `not_reproduced`. The child is never asked to satisfy both shapes. Failed, missing, cancelled, or invalid registered/normalized results are `contested`.
6. For every valid normalized `confirmed: true` diagnosis, build another exact `codebase_researcher` role input and spawn an independent cross-check in a host envelope. Ask it to refute the root cause, scope, and proposed fix. Spawn all cross-checks before awaiting.
7. Validate each untouched cross-check return against the registered output schema, then have the conductor transform it into the separate verdict schema and validate that object. A diagnosis becomes `taskable` only when the normalized cross-check succeeds and returns `refuted: false`. Explicit refutation, failure, timeout, cancellation, or invalid output makes it `contested`.
8. Validate the aggregate output before returning.

## Output schema

```json
{
  "type": "object",
  "required": ["status", "taskable", "contested", "not_reproduced", "warnings"],
  "properties": {
    "status": {"enum": ["complete", "partial", "invalid_input"]},
    "taskable": {"type": "array", "items": {"type": "object"}},
    "contested": {"type": "array", "items": {"type": "object"}},
    "not_reproduced": {"type": "array", "items": {"type": "object"}},
    "warnings": {"type": "array", "items": {"type": "string"}}
  },
  "additionalProperties": false
}
```

Invalid input returns `invalid_input` with no taskable diagnoses. Any dispatch/result failure returns `partial`. Empty input returns `complete`.

## Executable schema walkthrough

```json
[
  {"status":"complete","taskable":[],"contested":[],"not_reproduced":[],"warnings":[]},
  {"status":"complete","taskable":[{"action_item_id":"act_1"}],"contested":[],"not_reproduced":[],"warnings":[]},
  {"status":"partial","taskable":[],"contested":[{"action_item_id":"act_1"}],"not_reproduced":[],"warnings":["cross-check timeout"]},
  {"status":"invalid_input","taskable":[],"contested":[],"not_reproduced":[],"warnings":["issues is invalid"]}
]
```

## Parallelism, failure, and abstention

Investigations run in parallel. Cross-checks depend on valid confirmed diagnoses, then run in parallel as a second barrier. Children never recursively orchestrate. Infrastructure failure is an abstention and therefore `contested`; it never proves that a finding does not reproduce. Only `taskable` items may become fixes.

## Worktree ownership

The program reads the caller's checkout and creates no branch or worktree. The caller supplies the exact review SHA through its repository state; resulting fix tasks later receive separate conductor-owned worktrees.

## MCP persistence handoff

The conductor persists contested and not-reproduced evidence with `record_research_artifact` under the original phase/review scope. It creates fix cards only for `taskable` diagnoses, reuses the existing board, carries `action_item_id`, declares exact `write_files`, and obtains a fresh overlap report. Children never create tasks, change action-item status, or start a nested plan/review loop. If no taskable diagnosis remains, the conductor stops and escalates.
