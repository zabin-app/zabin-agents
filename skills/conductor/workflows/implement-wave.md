# Implement Wave

Dispatch a server-authorized, parallel-safe set of Zabin task cards into conductor-created worktrees. Each implementor executes the worker-owned lifecycle through `in_review`; the conductor then validates and decides whether a branch may merge. This program never merges, completes, or releases a task.

## Preconditions

The conductor must already have:

- an explicit `project_id` and authoritative task ids;
- self-contained task descriptions and non-empty `write_files` from `get_task`;
- satisfied dependencies and `ready` status;
- a fresh `get_overlap_report` for exactly this task set with `parallel_safe: true` and no `unscoped` entries;
- a recorded wave with the exact `base_sha` and status `running`;
- one isolated worktree per task, created by the main loop from that base.

If any precondition is absent, return `blocked` without spawning. Overlapping or unscoped tasks use the conductor's sequential path, not this program.

## Host capability contract

- `spawn-role(envelope)` dispatches a registered `implementor` or `task_validator`. `envelope.role_input` is validated as a closed role object; branch, identity, tier, directory, timeout, TTL, and correlation are sibling host metadata.
- `spawn-ad-hoc(input, capability-tier, working-directory)` is not used; implementation and validation require registered roles.
- `await-result(dispatch-id)` returns a structured completion, failure, or timeout.
- `cancel(dispatch-id)` requests cancellation after a bounded wait; it never revokes a Zabin lease.
- `working-directory(path)` binds the exact registered worktree for each task.
- `validate-schema(value, schema)` validates input, role output, and every aggregate return.

Select only portable capability tiers. The registered implementor tier is `balanced`; raise to `deep` for `complex` or `epic` work when the registry permits task-scoped mutation. Validators use their registered `fast` read-only tier. A tier whose mutation contract cannot satisfy the role is a precondition failure. Never name a runtime-specific API.

The main loop alone creates/removes worktrees, chooses bases, merges, handles conflicts, and runs integration gates. Children may not spawn other agents or recursively run this program.

The registered inputs illustrated below are exact and closed.

## Registered role-input walkthrough

```json
{
  "implementor": {"project_id":"prj_example","task_id":"tsk_example","worktree":"/worktrees/task","write_files":["src/file"]},
  "task_validator": {"objective":"Validate task tsk_example","diff_range":"base..head","acceptance_criteria":["criterion"]}
}
```

The implementor envelope carries exact `agent_name`, branch, base branch/SHA, worktree id, complexity/tier, TTL, verification context, and dispatch correlation. The validator envelope carries branch/worktree identity, tier, correlation, and a separate `context` object containing task id/title, authoritative `write_files`, worker summary, lease-holder name, source commits, and expected branch. None of that metadata or context is injected into either closed `role_input`.

## Cross-document contract audit fixture

This fixture is checked against `config/agents.json`, `agents/implementor.md`, and `agents/task_validator.md`. It demonstrates that validator containment data stays outside the closed role input while remaining available to the validator:

```json
{
  "implementor_statuses": ["done", "blocked", "failed"],
  "validator_dispatch": {
    "role_input": {
      "objective": "Validate task tsk_example",
      "diff_range": "base..source",
      "acceptance_criteria": ["all declared behavior is present"]
    },
    "context": {
      "task_id": "tsk_example",
      "task_title": "Example task",
      "write_files": ["src/file"],
      "worker_summary": "Implemented the declared file",
      "lease_holder_name": "implementor@example/task",
      "source_commits": ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
      "expected_branch": "work/task"
    }
  },
  "containment": {
    "rule": "every committed path must be a member of write_files",
    "undeclared_path_result": "fail"
  }
}
```

## Input schema

```json
{
  "type": "object",
  "required": ["project_id", "phase_id", "wave_id", "base_branch", "base_sha", "tasks"],
  "properties": {
    "project_id": {"type": "string", "minLength": 1},
    "phase_id": {"type": "string", "minLength": 1},
    "wave_id": {"type": "string", "minLength": 1},
    "base_branch": {"type": "string", "minLength": 1},
    "base_sha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
    "tasks": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["task_id", "agent_name", "branch", "worktree", "worktree_id", "complexity", "write_files", "lease_ttl_secs", "acceptance_criteria", "verification"],
        "properties": {
          "task_id": {"type": "string", "minLength": 1},
          "agent_name": {"type": "string", "minLength": 1},
          "branch": {"type": "string", "minLength": 1},
          "worktree": {"type": "string", "minLength": 1},
          "worktree_id": {"type": "string", "minLength": 1},
          "complexity": {"enum": ["trivial", "simple", "moderate", "complex", "epic"]},
          "write_files": {"type": "array", "minItems": 1, "items": {"type": "string"}},
          "lease_ttl_secs": {"type": "integer", "minimum": 1},
          "acceptance_criteria": {"type": "array", "minItems": 1, "items": {"type": "string"}},
          "verification": {"type": "array", "items": {"type": "string"}}
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

The input is an identity and containment stub, not a copied task specification. The worker obtains the authoritative description, relationships, and write scope from `get_task`.

## Implementor result schema

Each child must satisfy the registered `implementor.output_schema` exactly:

```json
{
  "type": "object",
  "required": ["status", "summary", "files_changed", "verification"],
  "properties": {
    "status": {"type": "string"},
    "summary": {"type": "string"},
    "files_changed": {"type": "array"},
    "verification": {"type": "array"}
  },
  "additionalProperties": false
}
```

After registered-schema validation, accept only the lowercase contract values `done`, `blocked`, or `failed` in `status`; reject rather than case-fold any other value. The conductor reconciles branch, commit, lease, task, and worktree facts from git and Zabin; it never trusts invented child fields for those facts.

## Worker lifecycle stub

For each task, build the exact four-field `implementor` role input above, validate it against `config/agents.json`, and call `spawn-role(envelope)`. Host metadata supplies exact agent/worktree/branch/base identity, TTL, and verification/doc-routing context without changing the role input. Inside its one worktree, the implementor performs this order using only the worker MCP surface:

1. `start_task` with `project_id`, `task_id`, exact `agent_name`, `lease_ttl_secs`, `branch`, `base_branch`, and `base_sha`. This composite claims the lease, fetches the full card, registers the worktree, and writes status `executing` in one call — there is no separate `queued` hop. Verify the returned owner and TTL (resize with `renew_task_lease` if the grant is lower than requested); verify the returned card's identity, authoritative description, dependencies, and `write_files` against the dispatch boundary, stopping on disagreement; retain `worktree_id` from the response.
2. Post bounded progress messages and implement only the authoritative scope. The worker must not create, switch, merge, rebase, remove, or clean worktrees, and must not spawn agents.
3. Renew the explicit TTL immediately before long verification. Run the repository-grounded verification commands in the assigned worktree.
4. Before committing, require every changed path to be present in the authoritative `write_files` set. Any undeclared lockfile, generated file, task ledger, re-export, import, or other path is a containment failure: preserve the evidence and stop rather than staging or committing it. Commit only declared paths using `git.commit`. Do not edit or append a local task ledger unless it is itself declared; Zabin is the task record.
5. `finish_task` with `project_id`, `task_id`, exact `agent_name`, `commits`, `summary`, and `worktree_sha`. This composite records the source commits, sets the worktree `idle`, writes task status `in_review`, and records the task summary in one call; the lease is retained. `worktree_sha` is validated and echoed back in the response only — it is not persisted to the worktree row (the domain worktree record has no tip-SHA field; that persistence is a tracked follow-up, not part of this call).
6. Return a schema-valid implementor result while retaining the lease. Never write `validated` or `completed`, and never call `release_task`.

Each composite reports `steps_committed` — which of its underlying steps actually landed — and stops at the first failing step rather than rolling back what already committed. On a partial `steps_committed`, do not retry the composite; finish the remaining steps with the matching singular tool under the still-held lease (for example, a `start_task` that claimed but did not register the worktree leaves the card `ready` with the lease held — the fix is completed with a direct `register_worktree` call, then `update_task_status` to `queued` and, separately, to `executing`; the `queued` hop is required on this singular repair path even though `start_task` folds it into one call, and `steps_committed` carries no card-fetch flag because the card fetch runs last, after `executing`, so it is never among the landed steps when `register_worktree` failed. A `finish_task` that recorded commits but not the summary is completed with a direct `record_task_summary` call, then `update_worktree_status` and `update_task_status` for whichever step is still unmarked). `claim_task`, `get_task`, `register_worktree`, `update_task_status`, `record_commits`, `update_worktree_status`, and `record_task_summary` all remain individually callable for exactly this repair path.

If implementation or verification fails, the worker still preserves and commits useful scoped work when required by the implementor contract, reports `status: "failed"`, marks the worktree idle if safe, writes `in_review` only when a reviewable commit and summary exist, and retains the lease for conductor recovery. It does not invent a lifecycle transition to escape failure.

## Main-loop procedure

1. Validate input and all preconditions against fresh MCP and git reads.
2. Spawn every implementor envelope before awaiting any result. Record dispatch ids by task id in conductor state.
3. Await all implementors. After timeout, request `cancel`, preserve the lease/worktree/branch, and mark the aggregate task result failed. Cancellation does not authorize release or cleanup.
4. Validate every untouched child result only against `implementor.output_schema`. The conductor alone transforms the registered result plus git/MCP/envelope facts into the per-task aggregate object; it validates that distinct object against the output schema. Reconcile with `get_task`, `list_workspaces`, recorded commits, git head, and task summary. Any missing or contradictory evidence is a containment failure.
5. For each reviewable `in_review` task, build exactly `objective`, `diff_range`, and `acceptance_criteria`, then validate that closed object against `task_validator.input_schema`. In the sibling host envelope `context`, supply at least authoritative `write_files` and, when available, task id/title, worker summary, lease-holder name, source commits, and expected branch. The envelope also binds the worktree and `fast` tier. Missing `context.write_files` is a fail-closed dispatch error because containment would be unverifiable. The validator is read-only, runs no orchestration, and returns only its registered output.
6. Await and validate validators. A missing, failed, timed-out, cancelled, or invalid validator result is `fail`; no branch with `concern` or `fail` may merge.
7. Return the aggregate to the conductor. The conductor persists task gates and verdicts, writes `validated` only for pass under the worker's exact agent name, and performs merge/integration/complete/release later under the conductor-owned lifecycle.

## Output schema

```json
{
  "type": "object",
  "required": ["status", "wave_id", "tasks", "warnings"],
  "properties": {
    "status": {"enum": ["ready_for_verdicts", "blocked", "partial", "invalid_input"]},
    "wave_id": {"type": "string"},
    "tasks": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["task_id", "agent_name", "branch", "worktree_id", "source_sha", "worker_status", "validator_verdict", "files_changed", "verification", "summary"],
        "properties": {
          "task_id": {"type": "string"},
          "agent_name": {"type": "string"},
          "branch": {"type": "string"},
          "worktree_id": {"type": "string"},
          "source_sha": {"type": ["string", "null"]},
          "worker_status": {"enum": ["done", "blocked", "failed"]},
          "validator_verdict": {"enum": ["pass", "concern", "fail"]},
          "files_changed": {"type": "array", "items": {"type": "string"}},
          "verification": {"type": "array"},
          "summary": {"type": "string"}
        },
        "additionalProperties": false
      }
    },
    "warnings": {"type": "array", "items": {"type": "string"}}
  },
  "additionalProperties": false
}
```

Invalid input returns `invalid_input`, the supplied wave id when valid or an empty string, no task results, and validation warnings. A precondition failure returns `blocked`. Child infrastructure or schema failures return `partial`; their per-task validator verdict is `fail`. Validate the aggregate before returning.

## Executable schema walkthrough

```json
[
  {"status":"ready_for_verdicts","wave_id":"wav_1","tasks":[],"warnings":[]},
  {"status":"blocked","wave_id":"wav_1","tasks":[],"warnings":["overlap precondition failed"]},
  {"status":"partial","wave_id":"wav_1","tasks":[{"task_id":"tsk_1","agent_name":"worker-1","branch":"work/1","worktree_id":"wkt_1","source_sha":null,"worker_status":"failed","validator_verdict":"fail","files_changed":[],"verification":[],"summary":"worker timeout"}],"warnings":["worker timeout"]},
  {"status":"invalid_input","wave_id":"","tasks":[],"warnings":["tasks is invalid"]}
]
```

## Parallelism, failure, and abstention

Parallelism exists only because the server's exact overlap report authorized it and every task has its own worktree. Implementors run concurrently. Validators may start as individual reviewable results arrive and may run concurrently because they are read-only.

Implementation failure is never an abstention from validation. Validator failure is a fail-closed `fail`. Missing durable bookkeeping or any out-of-scope write blocks the task. No child recursively orchestrates.

## Worktree ownership

The conductor owns worktree topology. The worker owns edits and its source commit inside the assigned worktree. Validators are read-only. A failed task's branch and worktree evidence are preserved; cleanup, merge ordering, conflict handling, commit mapping, and removal remain main-loop responsibilities.

## MCP persistence handoff

Workers persist claim, task status through `in_review`, progress, workspace registration/idle state, source commits, and summary on the worker surface — driven by the `start_task`/`finish_task` composites, with the singular tools as the partial-failure repair path. The conductor persists gate results and task verdicts; on pass it writes `validated`, merges, records merged commit mappings and workspace transitions, runs integration gates, then writes `completed` and releases. The worker lease remains held across this handoff.
