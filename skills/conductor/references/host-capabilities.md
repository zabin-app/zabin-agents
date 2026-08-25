# Host Capability Contract

The conductor describes operations, not a particular host API. At startup, map each required operation below to an available host primitive and validate its input/output shape. If an essential operation has no safe mapping, stop and report the missing capability.

These names are portable semantic identifiers. They are not MCP tool names and are never written into Zabin as if they were server operations.

## Core operations

| Capability | Minimum input | Required result | Ownership |
|---|---|---|---|
| `mcp.discover` | surface identity | public tool names and schemas | Main loop |
| `mcp.call` | public tool name, argument object | structured result or typed error | Main loop; worker only on worker surface |
| `filesystem.read` | absolute or repository-relative path | bytes/text and path identity | Any scoped role |
| `filesystem.search` | root, pattern/glob | matching paths/lines | Any scoped role |
| `filesystem.write` | path, bounded edit | changed path/evidence | Only a role whose declared scope contains the path |
| `git.inspect` | repository/worktree, query | branch, SHA, status, diff, or worktree metadata | Main loop and read-only roles |
| `git.create_worktree` | repository, branch, base ref, destination | isolated path, branch, resolved base SHA | Main loop only |
| `git.commit` | worktree, explicit paths, message | source commit SHA | Worker for its scoped worktree; main loop for inline work |
| `git.squash_merge` | primary checkout, source branch | merged tree or conflict evidence | Main loop only |
| `git.remove_worktree` | exact registered path | removal result | Main loop only, after durable reconciliation |
| `process.run` | working directory, argv, timeout | exit code, stdout/stderr summary | Scoped role; main loop controls destructive commands |
| `agent.dispatch` | registered role, structured assignment, worktree, tier | dispatch id | Main loop only |
| `agent.wait` | dispatch id(s), timeout/monitor policy | completed, partial, failed, or timed-out result | Main loop only |
| `human.prompt` | decision/question and context | explicit answer or pending state | Main loop only |
| `human.wait_event` | project/scope event filter and timeout | wake-up event or timeout | Main loop only; event is never proof of approval |

Optional research operations include `web.search` and `web.fetch`, subject to the external-research role's source policy.

## Dispatch assignment schema

Every bounded assignment includes enough identity to audit and contain it:

```json
{
  "role": "implementor",
  "objective": "Execute the authoritative Zabin task specification.",
  "project_id": "prj_example",
  "task_id": "tsk_example",
  "agent_name": "implementor@runner/task-05",
  "worktree": "/absolute/path/to/worktree",
  "branch": "work/task-05",
  "base_branch": "feature/base",
  "base_sha": "42a4056677e5bcdc00b42dcb62cfa4cf0d4ddbb1",
  "write_files": ["src/module.rs", "tests/module.rs"],
  "lease_ttl_secs": 7200,
  "verification": ["project test command", "project lint command"]
}
```

The implementation assignment does not contain a copied task specification. The worker's `start_task` composite call folds the claim, the full card fetch, worktree registration, and the status write to `executing` into one round trip and returns the full card — `description`, `write_files`, relationships, and subtasks included; the worker verifies identity and scope from that response and stops if it differs. `get_task` remains available standalone as the repair path when a composite reports a partial commitment.

Research, review, validation, and integration assignments use their registered role schemas from `config/agents.json`. Select `fast`, `balanced`, or `deep` from `config/model-tiers.json`; the host resolves the tier to an available model. Do not embed a vendor or concrete model identifier in pipeline instructions.

## Parallel dispatch

Parallel work is authorized only when `get_overlap_report` returns `parallel_safe:true` for the exact task set.

1. The main loop resolves the working branch and base SHA with `git.inspect`.
2. It creates one isolated worktree per card with `git.create_worktree`.
3. It issues independent `agent.dispatch` operations and retains every dispatch id.
4. It collects all results with `agent.wait`; a missing or partial result fails toward caution.
5. It validates each branch independently before any merge.

Agents do not dispatch other agents. A multi-voice research or review program is expanded by the main loop into bounded dispatches, then synthesized and persisted by the main loop.

## Sequential dispatch

Tasks that share a write path, have a dependency edge, or cannot be safely scoped do not run concurrently. Execute them one at a time. If a sequential worker mutates the primary checkout, record its pre-task SHA and validate the exact diff before starting the next task.

## Main-loop git boundary

Only the main loop may:

- choose branch/worktree topology;
- create or remove worktrees;
- order merges;
- abort or resolve a conflict;
- update source-to-merged commit mappings;
- inspect unexpected primary-checkout changes and decide whether to pause;
- run the post-merge integration gate.

Workers may edit and commit only inside their assigned worktree. Validators, reviewers, researchers, and integration verifiers are read-only. A documentation maintainer may edit only its declared documentation scope.

Never use cleanup, reset, checkout, or deletion to hide unexpected state. Preserve evidence and pause when containment cannot be established.

## Waiting and progress

Use host monitoring for long-running agents, verification commands, and approval events. Do not busy-poll. While a worker runs, it posts task-scoped progress to Zabin and renews before silent long stages. The main loop may also report phase-level progress through the available human channel, but it must not impersonate a worker's task narration.

An approval event wakes the main loop; a subsequent `get_plan` read establishes whether approval actually exists. A timeout returns control for a low-frequency read and user update, not for an automatic approval assumption.

## Failure mapping

| Host result | Pipeline treatment |
|---|---|
| Dispatch timeout with partial evidence | Preserve evidence; do not pass validation; renew/recover lease as applicable. |
| Tool unavailable | Re-run capability discovery; stop if required. |
| Process nonzero | Persist failed gate with concise output; diagnose within task scope. |
| Git conflict | Record worktree conflict, abort safely, preserve branch, pause. |
| Unexpected write outside scope | Stop, preserve diff, mark containment failure. |
| Human wait timeout | Re-read authoritative state and report pending gate. |
