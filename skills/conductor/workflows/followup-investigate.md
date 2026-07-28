# Followup Investigate

Root-cause investigation of code-review findings: investigate each Critical/Major issue, then cross-check the diagnosis before it becomes a fix task. Filters out findings that do not reproduce.

**When to use:** Conductor followup loop, when a review verdict is NEEDS_WORK/REJECTED and there are findings to diagnose before writing fix tasks.

**Phases:**
1. **Investigate** — one investigator per issue (workhorse tier) — confirm it reproduces
2. **Cross-check** — a second workhorse-tier pass refutes the diagnosis before tasking

## Inputs

`issues: [{ label, text }]` — paste the full finding text per Critical/Major item.

If no issues are provided, return immediately: `{ taskable: [], contested: [], notReproduced: [] }` and log "No issues provided — nothing to investigate."

## Procedure

Executed by the conductor issuing `delegate` calls directly from the main loop.

### Stage 1 — Investigate (parallel, one per issue)

For each issue, dispatch:

```
delegate(source: "codebase_researcher", provider: "github_copilot", model: "claude-sonnet-5",
  instructions: "Investigate this code-review finding and locate its root cause:

<issue.text>

Verify the issue actually exists in the code before diagnosing. If it does not reproduce, set confirmed=false and explain. Return JSON matching the Diagnosis Schema.",
  async: true)
```

**Diagnosis Schema:**
```json
{
  "issue": "string",
  "confirmed": "boolean — false if the finding does not reproduce in the code",
  "rootCause": "string — file:line and mechanism",
  "fixApproach": "string",
  "filesToChange": ["string"],
  "regressionRisk": "string"
}
```

Dispatch all issues' investigate delegate calls in parallel, then `load(source: "<task_id>")` each.

### Stage 2 — Cross-check (only where confirmed=true)

For each issue whose diagnosis has `confirmed: true`, dispatch:

```
delegate(source: "codebase_researcher", provider: "github_copilot", model: "claude-sonnet-5",
  instructions: "A diagnosis claims the root cause of \"<issue.label>\" is: <rootCause> with fix: <fixApproach>. Try to REFUTE it — is the root cause correct, and would the fix be complete without regressions? Default refuted=true if unconvinced. Return JSON matching the Verdict Schema.",
  async: true)
```

If `confirmed` is `false` (or the investigate delegate failed), skip cross-check entirely and mark that issue `upheld: false` directly.

**Verdict Schema:**
```json
{
  "refuted": "boolean — true if the diagnosis/fix is wrong, incomplete, or would regress",
  "reasoning": "string",
  "correction": "string"
}
```

An issue is `upheld` only if the cross-check delegate succeeded AND returned `refuted: false`.

## Output

```json
{
  "taskable": ["diagnoses where upheld=true — includes filesToChange, rootCause, fixApproach, regressionRisk"],
  "contested": ["diagnoses where confirmed=true but upheld=false — includes dissent/correction from the cross-check"],
  "notReproduced": ["issue text, for diagnoses where confirmed=false or missing"]
}
```

Log: `"followup-investigate: <T> taskable, <Ct> contested, <NR> not reproduced"`.

## Failure semantics

- An investigate delegate that fails/returns nothing → treated as `confirmed: false` → lands in `notReproduced`.
- A cross-check delegate that fails/returns nothing → treated as NOT upheld (fail toward caution) → lands in `contested`.
- `contested` and `notReproduced` items must NOT be turned into fix tasks — only `taskable` diagnoses feed the fix `TASKS.md`. `notReproduced` items go into `TASKS.md` Notes for visibility, not as tasks.

## Worktree behavior

None — this runbook is read-only investigation over the existing working tree; no worktrees are created. (Any resulting fix tasks are later implemented via `implement-wave.md`, which does create/manage worktrees, in the conductor's Build state re-entry.)
