# Research Sweep

Fan out independent research questions, then adversarially verify every load-bearing claim before planning. This is a conductor main-loop program: children perform one bounded assignment and never spawn, await, cancel, or otherwise orchestrate other children.

Use it for three or more questions, an unknown affected area, or assumptions whose falsity would change the plan.

## Host capability contract

The host must bind these semantic operations before execution:

- `spawn-role(envelope)` dispatches one registered research role. `envelope.role_input` is the closed registered-role object; tier, directory, timeout, and correlation data are sibling host metadata and are never injected into it.
- `spawn-ad-hoc(input, capability-tier, working-directory)` dispatches one bounded skeptic without inventing a registered role.
- `await-result(dispatch-id)` returns a structured completion, failure, or timeout result.
- `cancel(dispatch-id)` requests cancellation after the caller's bounded wait policy expires; cancellation is not proof that the child stopped.
- `working-directory(path)` binds read-only repository context for a dispatch.
- `validate-schema(value, schema)` returns valid or a typed validation error.

Required research roles are `codebase_researcher`, `external_researcher`, and `git_historian`. Research uses the registered role's tier, normally `fast`; skeptic passes use `balanced`. The host resolves tiers through its portable registry. Runtime-specific identifiers do not belong in this program.

A host dispatch envelope has this separation:

```json
{
  "role": "codebase_researcher",
  "role_input": {"objective": "Locate session ownership", "scope": ["src/session"]},
  "capability_tier": "fast",
  "working_directory": "/repo",
  "metadata": {"correlation_id": "question-1"}
}
```

Construct `role_input` by role, with no other root fields:

- `codebase_researcher`: `objective`, `scope`, optional `context`;
- `external_researcher`: `objective`, `source_policy`, optional `context`;
- `git_historian`: `objective`, `scope`, optional `revision_range`.

Question label, repository, tier, timeout, dispatch id, and schema references belong to the envelope. For external research, derive a non-empty `source_policy` from the question's approved source constraints; if none can be supplied, do not spawn and mark the question unanswered.

## Registered role-input walkthrough

```json
{
  "codebase_researcher": {"objective":"Locate session ownership","scope":["src/session"],"context":{"question":"owner"}},
  "external_researcher": {"objective":"Verify library support","source_policy":["official documentation"],"context":{"question":"support"}},
  "git_historian": {"objective":"Find the introducing change","scope":["src/session"],"revision_range":"main..HEAD"}
}
```

## Retrieval before dispatch

Before building `role_input` for a question, run 1-2 `search_context`
queries scoped to that question — e.g. `search_context(project_id, "session
ownership token refresh")` — to check for prior art: a research artifact,
review round, or task that already answers it. This is two-stage: a snippet
plus `source_type`/`source_id` first, a full fetch (`get_task`,
`get_project_doc`, `get_plan`, or the artifact's own round) only for the
specific hit that looks load-bearing. A keyword-only note in the response
means the semantic index was unavailable and the hits are BM25-only — still
usable, record it in the finding's `caveats`. Fold anything load-bearing
found this way into the question's `context` for the dispatched role rather
than re-researching it from nothing.

This narrows which questions still need a fresh dispatch; it does not
replace enumeration (list the affected surface with the paged list tools,
not with search hits) and it does not replace the researcher's own reads
once scope narrows to a specific file, module, or the document the plan is
about to act on — those are read in full, never from a snippet.

## Input schema

Validate the program input before dispatch:

```json
{
  "type": "object",
  "required": ["project_id", "repository", "questions"],
  "properties": {
    "project_id": {"type": "string", "minLength": 1},
    "plan_id": {"type": "string", "minLength": 1},
    "repository": {"type": "string", "minLength": 1},
    "questions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["label", "role", "question"],
        "properties": {
          "label": {"type": "string", "minLength": 1},
          "role": {"enum": ["codebase_researcher", "external_researcher", "git_historian"]},
          "question": {"type": "string", "minLength": 1},
          "scope": {"type": "array", "items": {"type": "string"}},
          "source_policy": {"type": "array", "minItems": 1},
          "revision_range": {"type": "string"}
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

`project_id` is explicit even though children do not persist state. It identifies the later MCP handoff. An absent `plan_id` is valid before a plan exists.

## Child result schemas

Research roles return their registered output shape (`summary`, `evidence`, and `caveats`). The conductor validates that result first, then normalizes the dispatch identity plus those fields into this finding schema and validates again:

```json
{
  "type": "object",
  "required": ["question", "found", "summary", "claims", "related_files", "caveats"],
  "properties": {
    "question": {"type": "string"},
    "found": {"type": "boolean"},
    "summary": {"type": "string"},
    "claims": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claim", "evidence", "load_bearing"],
        "properties": {
          "claim": {"type": "string"},
          "evidence": {"type": "array", "items": {"type": "string"}},
          "load_bearing": {"type": "boolean"}
        },
        "additionalProperties": false
      }
    },
    "related_files": {"type": "array", "items": {"type": "string"}},
    "caveats": {"type": "array", "items": {"type": "string"}}
  },
  "additionalProperties": false
}
```

Each skeptic returns:

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

1. Call `validate-schema` on the input. A validation error returns the invalid-input output below without dispatching.
2. If `questions` is empty, return a schema-valid empty output.
3. Build the exact closed `role_input` shown above from `config/agents.json`; call `validate-schema(role_input, registered_input_schema)`. Never place host metadata in it.
4. Put tier, correlation, and `working-directory(repository)` in the host envelope. External researchers receive required `source_policy` inside `role_input`; the other roles receive required `scope` inside `role_input`.
5. Call `spawn-role(envelope)` once per question without awaiting between spawns. Retain the mapping from dispatch id to question in conductor state.
6. Call `await-result` for every dispatch. After a bounded timeout, call `cancel` once and record the question as unanswered. First validate the untouched child return against the registered output schema. Only after it passes, have the conductor transform it into a finding using the dispatch mapping; validate that distinct normalized object against the finding schema. Invalid registered or normalized results are unanswered. A child is never required to return both shapes.
7. For every valid `found: true` finding, collect claims with `load_bearing: true`. Call `spawn-ad-hoc` twice per claim at the `balanced` tier. Each skeptic gets the claim, offered evidence, repository scope, and the skeptic schema; it gets no orchestration capabilities.
8. Await and validate all skeptic results. Failed, timed-out, cancelled, or invalid results abstain.
9. Classify each claim:
   - two surviving refutations: `refuted`;
   - two surviving confirmations: `verified`;
   - split votes, one surviving vote, or zero surviving votes: `contested`.
10. Call `validate-schema` on the aggregate output before returning.

## Output schema

Every return path, including empty and invalid input, uses this schema:

```json
{
  "type": "object",
  "required": ["status", "answered", "unanswered", "claims", "warnings"],
  "properties": {
    "status": {"enum": ["complete", "partial", "invalid_input"]},
    "answered": {"type": "array", "items": {"type": "object"}},
    "unanswered": {"type": "array", "items": {"type": "object"}},
    "claims": {
      "type": "object",
      "required": ["verified", "refuted", "contested"],
      "properties": {
        "verified": {"type": "array", "items": {"type": "object"}},
        "refuted": {"type": "array", "items": {"type": "object"}},
        "contested": {"type": "array", "items": {"type": "object"}}
      },
      "additionalProperties": false
    },
    "warnings": {"type": "array", "items": {"type": "string"}}
  },
  "additionalProperties": false
}
```

An empty question set returns `status: "complete"` with empty arrays. Invalid input returns `status: "invalid_input"`, empty arrays, and the validation error in `warnings`. Any unanswered question or contested claim makes status `partial`.

## Executable schema walkthrough

These fixtures cover every top-level return path and are parsed and walked against the output schema by the static verification command:

```json
[
  {"status":"complete","answered":[],"unanswered":[],"claims":{"verified":[],"refuted":[],"contested":[]},"warnings":[]},
  {"status":"partial","answered":[],"unanswered":[{"label":"q1"}],"claims":{"verified":[],"refuted":[],"contested":[]},"warnings":["researcher timeout"]},
  {"status":"invalid_input","answered":[],"unanswered":[],"claims":{"verified":[],"refuted":[],"contested":[]},"warnings":["questions is invalid"]}
]
```

## Parallelism, failure, and abstention

Research questions are independent and run in parallel. Skeptic passes start only after their source finding validates, but all eligible skeptic passes run in parallel. Never hand fan-out control to a child.

A researcher failure is an unanswered question, never negative evidence. A skeptic failure is an abstention, never confirmation or refutation. Contested and refuted claims cannot become plan facts.

## Worktree ownership

This program is read-only. It creates no branch or worktree, and no child may mutate the repository. `working-directory` selects the caller-owned checkout only as read context.

## MCP persistence handoff

Children never call conductor MCP mutations. In the same main-loop turn, the conductor serializes the aggregate as a `record_research_artifact` body with claim states `verified`, `refuted`, and `contested`, using the explicit `project_id` and `plan_id` when available. Refuted, contested, and unanswered items also flow into plan risks. Persistence failure is reported to the caller and must not be disguised as a complete sweep.
