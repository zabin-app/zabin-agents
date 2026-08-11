# Plan Verify

Adversarially verify factual assumptions and proposed write scopes in a draft plan before it reaches the human approval gate. This is a conductor main-loop program; each child performs one bounded check and cannot recursively orchestrate.

## Host capability contract

- `spawn-role(envelope)` dispatches one registered researcher. The closed `envelope.role_input` is separate from host tier, directory, timeout, and correlation metadata.
- `spawn-ad-hoc(input, capability-tier, working-directory)` is available for a bounded second opinion when no registered role fits; it is not needed on the normal path.
- `await-result(dispatch-id)` returns a structured completion, failure, or timeout.
- `cancel(dispatch-id)` requests cancellation after the bounded wait expires.
- `working-directory(path)` binds the repository as read-only context.
- `validate-schema(value, schema)` validates inputs, child results, and every program return.

Use the assumption's registered research role at the `balanced` tier because this pass is adversarial verification. The host resolves the tier through its registry; runtime-specific identifiers are forbidden.

Exact registered inputs are:

- `codebase_researcher`: `objective`, `scope`, optional `context`;
- `external_researcher`: `objective`, `source_policy`, optional `context`;
- `git_historian`: `objective`, `scope`, optional `revision_range`.

The envelope carries role, `capability_tier: "balanced"`, `working_directory`, and correlation metadata. Those fields never appear in `role_input`. If an external assumption lacks a non-empty approved `source_policy`, classify it unresolved without spawning.

## Registered role-input walkthrough

```json
{
  "codebase_researcher": {"objective":"Refute the ownership assumption","scope":["src/session"]},
  "external_researcher": {"objective":"Refute the library assumption","source_policy":["official documentation"]},
  "git_historian": {"objective":"Refute the history assumption","scope":["src/session"],"revision_range":"main..HEAD"}
}
```

## Input schema

```json
{
  "type": "object",
  "required": ["project_id", "plan_id", "repository", "assumptions"],
  "properties": {
    "project_id": {"type": "string", "minLength": 1},
    "plan_id": {"type": "string", "minLength": 1},
    "repository": {"type": "string", "minLength": 1},
    "assumptions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["label", "claim"],
        "properties": {
          "label": {"type": "string", "minLength": 1},
          "claim": {"type": "string", "minLength": 1},
          "role": {"enum": ["codebase_researcher", "external_researcher", "git_historian"]},
          "scope": {"type": "array", "items": {"type": "string"}},
          "source_policy": {"type": "array", "minItems": 1},
          "revision_range": {"type": "string"},
          "kind": {"enum": ["existing_code", "file_path", "write_scope", "dependency", "library_capability"]}
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

Default `role` to `codebase_researcher` and `kind` to `existing_code` after validation.

## Child result schema

The child result first satisfies the registered research-role output schema. The conductor then normalizes its summary/evidence/caveats plus the dispatch identity into this verdict schema and validates it separately:

```json
{
  "type": "object",
  "required": ["status", "reasoning", "evidence", "correction"],
  "properties": {
    "status": {"enum": ["verified", "refuted", "unresolved"]},
    "reasoning": {"type": "string"},
    "evidence": {"type": "array", "items": {"type": "string"}},
    "correction": {"type": "string"}
  },
  "additionalProperties": false
}
```

`verified` requires concrete evidence. A child that cannot establish the fact returns `unresolved`; it does not guess.

## Procedure

1. Validate input. Invalid input returns `invalid_input` without dispatch.
2. If `assumptions` is empty, return a schema-valid `pass` with empty arrays.
3. For each assumption, construct only the exact registered input fields above and validate that closed object against `config/agents.json`. Put role, tier, `working-directory(repository)`, timeout, and the assumption label in the host envelope, then call `spawn-role(envelope)`. Do not grant spawn or mutation capabilities.
4. Spawn all checks before awaiting any. Retain dispatch-to-assumption identity.
5. Await each result. On timeout, request `cancel`. Validate the untouched child return only against its registered output schema. The conductor then transforms that result plus dispatch identity into a separate verdict object and validates the verdict schema. The child never returns the normalized verdict shape.
6. Put explicit `refuted` results in `refuted`. Put failed, timed-out, cancelled, invalid, or explicit `unresolved` results in `unresolved`. Only evidence-backed `verified` results enter `verified`.
7. Set verdict to `blocked` when either `refuted` or `unresolved` is non-empty. The plan must correct or explicitly risk-route every blocked assumption before approval.
8. Validate the complete output schema before returning.

## Output schema

```json
{
  "type": "object",
  "required": ["status", "verdict", "verified", "refuted", "unresolved", "warnings"],
  "properties": {
    "status": {"enum": ["complete", "partial", "invalid_input"]},
    "verdict": {"enum": ["pass", "blocked"]},
    "verified": {"type": "array", "items": {"type": "object"}},
    "refuted": {"type": "array", "items": {"type": "object"}},
    "unresolved": {"type": "array", "items": {"type": "object"}},
    "warnings": {"type": "array", "items": {"type": "string"}}
  },
  "additionalProperties": false
}
```

Invalid input returns `status: "invalid_input"`, `verdict: "blocked"`, empty result arrays, and validation details in `warnings`. Dispatch or result failures return `partial` and `blocked`.

## Executable schema walkthrough

```json
[
  {"status":"complete","verdict":"pass","verified":[],"refuted":[],"unresolved":[],"warnings":[]},
  {"status":"complete","verdict":"blocked","verified":[],"refuted":[{"label":"a1"}],"unresolved":[],"warnings":[]},
  {"status":"partial","verdict":"blocked","verified":[],"refuted":[],"unresolved":[{"label":"a1"}],"warnings":["worker timeout"]},
  {"status":"invalid_input","verdict":"blocked","verified":[],"refuted":[],"unresolved":[],"warnings":["assumptions is invalid"]}
]
```

## Parallelism, failure, and abstention

Assumptions are independent and all checks run in parallel. Children never spawn other children. A failure or missing result is an abstention from the factual question, represented as `unresolved`; because plan facts require affirmative evidence, abstention blocks approval.

## Worktree ownership

This program is read-only. It creates no worktree and makes no repository mutation. The caller owns the checkout selected through `working-directory`.

## MCP persistence handoff

The conductor persists the result with `record_research_artifact` under the explicit project and plan. It repairs refuted plan text and routes unresolved claims into plan risks before `finalize_plan`. Children never mutate plan or MCP state. A persistence failure keeps the verification gate blocked.
