# Review Diff

Review an exact phase diff across required architecture, quality, logic, risk, and security dimensions, then adversarially verify Critical and Major findings. Bug changes add bug-fix correctness. The conductor main loop owns every dispatch, synthesis, and MCP write; no child recursively orchestrates.

## Host capability contract

- `spawn-role(envelope)` dispatches one registered reviewer. Its closed `role_input` is separate from host tier, directory, timeout, dimension, round, and correlation metadata.
- `spawn-ad-hoc(input, capability-tier, working-directory)` dispatches one bounded finding refuter.
- `await-result(dispatch-id)` returns a structured completion, failure, or timeout.
- `cancel(dispatch-id)` requests cancellation after the bounded wait expires.
- `working-directory(path)` binds exact read-only repository context.
- `validate-schema(value, schema)` validates input, reviewer/refuter results, and every aggregate return.

Architecture, quality, risks, and bug-fix review use their registered `balanced` tier. Logic and security use `deep`. Refuters use `fast`. The host resolves portable tiers through the registry; runtime-specific APIs are forbidden.

Every registered reviewer receives only fields allowed by its closed input schema:

- architecture: `objective`, `diff_range`, optional `context`;
- quality: `objective`, `diff_range`, optional `standards`;
- logic: `objective`, `diff_range`, optional `invariants`;
- risks: `objective`, `diff_range`, optional `decisions`;
- security: `objective`, `diff_range`, optional `trust_boundaries`;
- bug-fix correctness: `objective`, `diff_range`, optional `reproduction`.

Dimension, round, previous-review reference, tier, repository, timeout, and correlation belong to the host envelope. They may inform an allowed optional role field, but are never added as new root fields to `role_input`.

## Input schema

```json
{
  "type": "object",
  "required": ["project_id", "phase_id", "repository", "diff_range", "reviewed_sha", "change_type", "task_ids"],
  "properties": {
    "project_id": {"type": "string", "minLength": 1},
    "phase_id": {"type": "string", "minLength": 1},
    "repository": {"type": "string", "minLength": 1},
    "diff_range": {"type": "string", "minLength": 1},
    "reviewed_sha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
    "change_type": {"enum": ["feature", "bug", "refactor"]},
    "task_ids": {"type": "array", "items": {"type": "string"}},
    "round": {"enum": [0, 1, 2]},
    "previous_review_ref": {"type": "string"},
    "review_focus": {"type": "array", "items": {"type": "string"}}
  },
  "additionalProperties": false
}
```

Normalize round before the rest of input validation: an absent value becomes integer `0`; integer `0`, `1`, or `2` is preserved; strings, booleans, null, fractions, negative values, and values above `2` are rejected without coercion. Round 1 and 2 require non-empty `previous_review_ref`; round 3 is forbidden. The caller must prove that `diff_range` ends at `reviewed_sha` before dispatch.

## Reviewer and refuter schemas

Reviewer output first satisfies the registered role schema (`verdict`, `summary`, and `findings`). The conductor then adds the dimension from its dispatch mapping, normalizes vocabulary and finding fields into this schema, and validates it separately:

```json
{
  "type": "object",
  "required": ["dimension", "verdict", "summary", "findings"],
  "properties": {
    "dimension": {"enum": ["architecture", "quality", "logic", "risks", "security", "bugfix"]},
    "verdict": {"enum": ["pass", "concern", "fail"]},
    "summary": {"type": "string"},
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["title", "file_ref", "severity", "problem", "recommendation"],
        "properties": {
          "title": {"type": "string"},
          "file_ref": {"type": "string"},
          "severity": {"enum": ["critical", "major", "minor"]},
          "problem": {"type": "string"},
          "recommendation": {"type": "string"},
          "task_id": {"type": "string"}
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

Each ad-hoc refuter returns:

```json
{
  "type": "object",
  "required": ["refuted", "reasoning", "evidence"],
  "properties": {
    "refuted": {"type": "boolean"},
    "reasoning": {"type": "string"},
    "evidence": {"type": "array", "items": {"type": "string"}}
  },
  "additionalProperties": false
}
```

## Procedure

1. Normalize `round` exactly as above, then validate the normalized input, convergence constraints, git range, reviewed SHA, and read-only checkout status. An invalid round or unverifiable scope returns fail closed without dispatch; no child runs.
2. Build the required dimensions: `architecture_enforcer`, `code_quality_inspector`, `logic_reasoning_checker`, `risks_tradeoffs_analyzer`, and `security_reviewer`; add `bug_fix_reviewer` for bugs.
3. Construct each closed `role_input` using only the fields listed above and validate it against `config/agents.json`. Put dimension, normalized round, previous-review reference, tier, timeout, correlation, and `working-directory(repository)` in the host envelope. Map review-focus or convergence context only into an optional field that the selected role schema allows.
4. Call `spawn-role(envelope)` for all dimensions before awaiting any. Children receive no spawn, mutation, or MCP persistence capabilities.
5. Await every dimension. After timeout request `cancel`. Validate the untouched child return only against its registered output schema. The conductor then adds dispatch dimension, normalizes vocabulary/fields into a separate review object, and validates the normalized schema. Preserve failed, timed-out, cancelled, invalid-registered, or invalid-normalized dimensions in `missing_dimensions`. A child never satisfies both schemas simultaneously.
6. For every valid Critical or Major finding, call `spawn-ad-hoc` three times at `fast`. Give each refuter the exact finding, diff range, and refuter schema. Ask whether it is a real problem introduced or exposed by this diff. Spawn all eligible votes before awaiting.
7. Await and validate all votes. Failed, timed-out, cancelled, or invalid votes abstain, but the conservative denominator remains the original three assigned votes. Drop a finding only with at least two schema-valid explicit refutations. One refutation can never erase a finding, even when the other two voters abstain. Zero or one refutation preserves the finding.
8. Keep all Minor findings. Synthesize the normalized verdict in this order:
   - any confirmed Critical: `rejected`;
   - any missing required dimension or any raw reviewer `fail`: `needs_work`;
   - any confirmed Major: `needs_work`;
   - any Minor or raw reviewer concern: `approved_with_concerns`;
   - otherwise: `approved`.
9. Validate the aggregate output before returning.

## Output schema

```json
{
  "type": "object",
  "required": ["status", "verdict", "diff_range", "reviewed_sha", "round", "confirmed", "minor", "dimensions", "missing_dimensions", "warnings"],
  "properties": {
    "status": {"enum": ["complete", "partial", "invalid_input"]},
    "verdict": {"enum": ["approved", "approved_with_concerns", "needs_work", "rejected"]},
    "diff_range": {"type": "string"},
    "reviewed_sha": {"type": "string"},
    "round": {"type": ["integer", "null"], "enum": [0, 1, 2, null]},
    "confirmed": {"type": "array", "items": {"type": "object"}},
    "minor": {"type": "array", "items": {"type": "object"}},
    "dimensions": {"type": "array", "items": {"type": "object"}},
    "missing_dimensions": {"type": "array", "items": {"type": "string"}},
    "warnings": {"type": "array", "items": {"type": "string"}}
  },
  "additionalProperties": false
}
```

Invalid input returns `status: "invalid_input"`, verdict `needs_work`, empty finding/dimension arrays, the available scope identity, and validation warnings. If round normalization failed, output `round: null`; otherwise echo the normalized integer. Missing reviewer results or any raw reviewer fail return `partial`/`needs_work` or `complete`/`needs_work` respectively and can never produce a passing verdict. Validate even these return paths.

## Executable schema walkthrough

```json
[
  {"status":"complete","verdict":"approved","diff_range":"base..head","reviewed_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","round":0,"confirmed":[],"minor":[],"dimensions":[],"missing_dimensions":[],"warnings":[]},
  {"status":"complete","verdict":"approved_with_concerns","diff_range":"base..head","reviewed_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","round":0,"confirmed":[],"minor":[{"title":"minor"}],"dimensions":[],"missing_dimensions":[],"warnings":[]},
  {"status":"complete","verdict":"needs_work","diff_range":"base..head","reviewed_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","round":1,"confirmed":[{"severity":"major"}],"minor":[],"dimensions":[],"missing_dimensions":[],"warnings":[]},
  {"status":"complete","verdict":"needs_work","diff_range":"base..head","reviewed_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","round":0,"confirmed":[],"minor":[],"dimensions":[{"dimension":"security","verdict":"fail"}],"missing_dimensions":[],"warnings":["raw reviewer failure"]},
  {"status":"complete","verdict":"rejected","diff_range":"base..head","reviewed_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","round":2,"confirmed":[{"severity":"critical"}],"minor":[],"dimensions":[],"missing_dimensions":[],"warnings":[]},
  {"status":"partial","verdict":"needs_work","diff_range":"base..head","reviewed_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","round":0,"confirmed":[],"minor":[],"dimensions":[],"missing_dimensions":["security"],"warnings":["security timeout"]},
  {"status":"invalid_input","verdict":"needs_work","diff_range":"base..head","reviewed_sha":"","round":null,"confirmed":[],"minor":[],"dimensions":[],"missing_dimensions":[],"warnings":["round is invalid"]}
]
```

## Executable round and voting walkthrough

```json
{
  "round_cases": [
    {"present":false,"input":null,"accepted":true,"normalized":0},
    {"present":true,"input":0,"accepted":true,"normalized":0},
    {"present":true,"input":1,"accepted":true,"normalized":1},
    {"present":true,"input":2,"accepted":true,"normalized":2},
    {"present":true,"input":"1","accepted":false,"normalized":null},
    {"present":true,"input":true,"accepted":false,"normalized":null},
    {"present":true,"input":3,"accepted":false,"normalized":null}
  ],
  "vote_cases": [
    {"valid_refutations":0,"valid_confirmations":0,"abstentions":3,"drop":false},
    {"valid_refutations":1,"valid_confirmations":0,"abstentions":2,"drop":false},
    {"valid_refutations":2,"valid_confirmations":0,"abstentions":1,"drop":true},
    {"valid_refutations":2,"valid_confirmations":1,"abstentions":0,"drop":true}
  ]
}
```

## Parallelism, failure, and abstention

Required dimensions are independent and run in parallel. Refuter panels begin only for schema-valid blocking findings, then run in parallel. Children never fan out.

Reviewer failure is not an abstention from the overall review: a missing dimension or raw `fail` forces `needs_work`. Refuter failure is an abstention and never reduces the fixed three-vote denominator. At least two explicit valid refutations are required to drop a finding. This is consistently fail closed; there is no implicit degraded approval mode.

## Worktree ownership

This program is read-only and creates no worktree. It reviews the conductor's integrated checkout at the exact `reviewed_sha`; reviewers and refuters cannot mutate it. Fix worktrees, if needed, are created later by the conductor.

## MCP persistence handoff

The conductor persists the synthesis in the same turn with `record_review_round`, using the exact phase, round, normalized verdict, and reviewed SHA. It attaches the full structured artifact when necessary and calls `add_action_item` once per confirmed or Minor finding. Missing dimensions are recorded in the summary and keep the round non-passing. Review children never write MCP state. Follow-up uses the latest authoritative Zabin round; it never creates a local review ledger and never runs round 3.
