# Implement Wave

Implement a wave of NON-overlapping tasks in parallel git worktrees and validate each immediately. Returns per-task branch + verdict for the conductor to merge in the main loop. **Does NOT merge.**

**When to use:** For the worktree-parallel sub-group of a wave (tasks with no write-file overlap), as determined by the conductor's Overlap Matrix. Sequential/overlapping tasks stay in the main loop and do NOT use this runbook.

**Phases:**
1. **Implement** — one implementor per task, isolated worktree, model per task complexity
2. **Validate** — `task_validator` (cheap tier) checks each task as soon as it lands

## Inputs

```
workingBranch: string   // branch the conductor is on; worktrees sync to it
tasks: [{ path, slug, complexity, agentType }]
```

If `workingBranch` is missing or `tasks` is empty, do nothing and report "Need workingBranch and tasks[] — nothing to implement."

## Complexity → model tier

```
low    -> claude-haiku-4.5
medium -> claude-sonnet-5
high   -> claude-opus-4.8
```
Default to `claude-sonnet-5` if a task's complexity is missing/unrecognized.

## Procedure

Executed by the conductor issuing `delegate` calls directly from the main loop — implementor subagents run in isolated worktrees and cannot recursively delegate, so the conductor is responsible for dispatching each task's implementor AND its validator itself.

### Stage 1 — Implement (parallel, one per task, isolated worktree)

The conductor creates each worktree **before** delegating. Use collision-safe names and base every worktree on the recorded wave base/working branch:

```bash
repo_root="$(git rev-parse --show-toplevel)"
worktree_root="$(dirname "$repo_root")/.$(basename "$repo_root")-goose-worktrees"
mkdir -p "$worktree_root"
branch="goose/<task.slug>-<unique-suffix>"
worktree="$worktree_root/<task.slug>-<unique-suffix>"
git worktree add -b "$branch" "$worktree" "$workingBranch"
```

Record the `{task, branch, worktree}` mapping in the main loop. If creation fails, mark that task failed and do not delegate it. Never ask a subagent to create, merge, or remove its own worktree.

For each successfully created worktree, dispatch:

```
delegate(source: <task.agentType, default "implementor">,
  provider: "github_copilot",
  model: <MODEL_FOR[task.complexity]>,
  instructions: "Implement task from: <task.path>

You are already running in an isolated git worktree on branch <branch>. Do not switch branches, create/remove worktrees, merge, rebase, or modify the parent working tree.
Read the task file and implement according to its acceptance criteria.
Follow docs/ARCHITECTURE.md for layer boundaries, docs/CODE_STANDARDS.md for conventions, and docs/DEVELOPMENT.md for verification commands.
Commit ALL changes (including the task file) before reporting; the main-loop merge mechanism requires a committed branch.
Report branch <branch> in the structured 'branch' field of your final answer, matching the Implementation Result Schema below.",
  working_dir: "<worktree>",
  async: true)
```

Dispatch all implementor calls before waiting, then collect each task with `load(source: "<task_id>")`.

**Implementation Result Schema:**
```json
{
  "slug": "string",
  "status": "Done | Blocked | Failed",
  "branch": "string — the worktree branch name the work was committed to",
  "qualityGate": "PASS | FAIL",
  "files": ["source files written"],
  "notes": "string — 1-2 sentence summary of key decisions or blockers",
  "docUpdatesNeeded": "string — empty unless core docs need updating"
}
```

### Stage 2 — Validate (as each implement result lands, cheap tier, read-only)

For each task whose implementor result has `status: "Done"`, dispatch from that task's recorded worktree:

```
delegate(source: "task_validator",
  provider: "github_copilot",
  model: "claude-haiku-4.5",
  instructions: "Validate implementation of: <task.path>

Diff command: git diff <workingBranch>..<impl.branch>
(the task's changes are on branch <impl.branch>, based on <workingBranch>)

Verify every acceptance criterion, check file scope against the task's declared write-files, and scan for obvious errors. Do NOT run builds or tests. Return JSON matching the Validation Schema.",
  working_dir: "<worktree>",
  async: true)
```

If the implementor result is missing, or `status` is not `"Done"`, skip the delegate call and directly set `{ verdict: "FAIL", notes: "implementor returned no result" | "implementor status <status>" }`.

**Validation Schema:**
```json
{
  "verdict": "PASS | CONCERN | FAIL",
  "criteriaUnmet": ["string"],
  "outOfScope": ["string"],
  "issues": ["string"],
  "notes": "string"
}
```

## Output

For each task, assemble:

```json
{
  "slug": "...",
  "path": "...",
  "branch": "impl.branch or null",
  "status": "impl.status or 'Failed'",
  "qualityGate": "impl.qualityGate or 'FAIL'",
  "verdict": "validation.verdict or 'FAIL'",
  "files": "impl.files or []",
  "docUpdatesNeeded": "impl.docUpdatesNeeded or ''",
  "notes": "impl.notes + validation.notes, joined with ' | '"
}
```

Return the array of these per-task results. Log: `"implement-wave: <P> PASS, <C> CONCERN, <F> FAIL across <N> tasks. Branches are NOT merged — conductor merges in task order."`

## Failure semantics

- An implementor delegate that fails/times out → `status: "Failed"`, `verdict: "FAIL"`.
- A validator delegate that fails/times out → treat as `verdict: "FAIL"` (fail toward blocking, never toward silent approval).
- This runbook never merges branches and never resolves FAIL verdicts itself — it only reports. The conductor decides pause/merge per the Build-state rules in the conductor SKILL.md.

## Worktree behavior

- `delegate` does **not** create worktrees. Before fan-out, the conductor creates one branch and one `git worktree` per task and records its path.
- The conductor passes that path through `working_dir`; the implementor and validator operate only inside it.
- This runbook never asks a subagent to create, merge, rebase, or remove a worktree.
- After verdict assessment, the conductor merges passing branches in task-number order and removes their worktrees/branches. For a FAIL, remove the worktree but keep the branch for inspection. Run `git worktree prune` after cleanup.
