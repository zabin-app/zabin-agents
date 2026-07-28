# Review Diff

Multi-dimension code review of a diff: each review dimension finds issues, then every Critical/Major finding is adversarially verified by a panel of refuters (majority-refute drops false positives). Returns confirmed findings + a synthesized verdict.

**When to use:** Phase review of a completed feature/bug diff, or re-review of a fix diff (pass `previousReview`).

**Phases:**
1. **Review** — one reviewer per dimension over the diff
2. **Verify** — 3 cheap-tier refuters per Critical/Major finding; majority kills false positives

## Inputs

```
diffRange: string          // default "HEAD~1..HEAD"
taskFiles: string[]        // acceptance criteria / scope references
changeType: "feature" | "bug"   // default "feature"
previousReview?: string    // path to a prior REVIEW.md — enables re-review/convergence mode
```

## Dimensions

Dimensions map to review agent types. Every delegate call must carry an explicit model — the conductor's model strategy sets tiers here (workhorse for most dimensions; deep-reasoning tier for logic + security).

| Dimension key | agentType | model |
|---|---|---|
| `architecture` | `architecture_enforcer` | `claude-sonnet-5` |
| `quality` | `code_quality_inspector` | `claude-sonnet-5` |
| `logic` | `logic_reasoning_checker` | `claude-opus-4.8` |
| `risks` | `risks_tradeoffs_analyzer` | `claude-sonnet-5` |
| `security` | `security_reviewer` | `claude-opus-4.8` |

If `changeType == "bug"`, prepend: `bugfix` → `bug_fix_reviewer` → `claude-sonnet-5`.

## Procedure

Executed by the conductor issuing `delegate` calls directly from the main loop — each reviewer is a separate top-level delegate (they cannot recursively fan out to the 3 refuter votes themselves), so the conductor also issues the refuter delegate calls directly.

### Stage 1 — Review (parallel, one per dimension)

For each dimension `d`, dispatch:

```
delegate(source: d.agentType, provider: "github_copilot", model: d.model,
  instructions: "Review the following code change as your dimension (<d.key>).

Diff range: git diff <diffRange>
Task files (acceptance criteria / scope): <taskFiles.join(', ') or '(none provided)'>
<if previousReview set:>
RE-REVIEW MODE — a previous review exists at: <previousReview>. Verify prior Critical/Major findings are resolved and review THIS fix diff with full rigor. Do NOT re-litigate unchanged code; new issues in untouched code are out of scope unless newly CRITICAL.
<end if>
Treat the diff as the source of truth — distinguish code introduced by this change from pre-existing code (you have read-only git access). Reference docs/ARCHITECTURE.md, docs/CODE_STANDARDS.md, docs/REVIEW_FOCUS.md for standards. Rate each finding's severity honestly (Critical / Major / Minor). Return JSON matching the Findings Schema.",
  working_dir: "<repo path>",
  async: true)
```

**Findings Schema:**
```json
{
  "dimension": "string",
  "verdict": "PASS | CONCERNS | FAIL",
  "findings": [
    {
      "title": "string",
      "file": "string",
      "line": "string",
      "severity": "Critical | Major | Minor",
      "problem": "string",
      "recommendation": "string"
    }
  ]
}
```

Dispatch all dimensions' delegate calls together (they are independent reads over the same diff), then `load(source: "<task_id>")` each as it completes.

### Stage 2 — Verify (as each dimension's review lands: 3 refuters per Critical/Major finding)

For each dimension's review, split its findings into `blocking` (Critical or Major) and `minors` (Minor). If no blocking findings, that dimension contributes 0 confirmed findings (just the minors). Otherwise, for **each** blocking finding, dispatch **3 parallel** refuter delegates:

```
delegate(source: none, provider: "github_copilot", model: "claude-haiku-4.5",
  instructions: "A <d.key> reviewer flagged this <severity> finding on diff `<diffRange>`:

Title: <title>
File: <file>:<line>
Problem: <problem>

Try to REFUTE it: is this actually a real problem introduced by THIS diff? Default refuted=true if it is a false positive, pre-existing, or a misread. Return JSON matching the Refute Verdict Schema.",
  async: true)
```

Note: this is an ad-hoc refuter pass with no fixed `source` agent type — omit `source` and rely on `instructions` alone.

**Refute Verdict Schema:**
```json
{
  "refuted": "boolean — true if the finding is NOT a real problem in this diff (false positive, pre-existing, or misread)",
  "reasoning": "string"
}
```

### Voting logic (per finding, 3 votes)

- Dead/failed voters (no result) **abstain** — an infra failure is not a refutation.
- A finding is **dropped** only when a **majority of the actual (surviving) votes** refute it: i.e. `refutes * 2 > realVotesCount`.
- If **all** voters died (zero real votes), the finding **survives** — fail toward blocking, never toward silently approving.
- Surviving findings become `confirmed` for that dimension; refuted findings are dropped entirely (not returned anywhere).

## Output

```json
{
  "verdict": "REJECTED | NEEDS_WORK | APPROVED_WITH_CONCERNS | APPROVED",
  "diffRange": "...",
  "reReview": "true if previousReview was set",
  "confirmed": ["confirmed Critical/Major findings across all dimensions, each tagged with its dimension"],
  "minors": ["all Minor findings across all dimensions"],
  "perDimension": [
    { "dimension": "...", "verdict": "raw dimension verdict or 'PASS'", "confirmedCount": 0, "minorCount": 0 }
  ]
}
```

### Verdict synthesis (severity floor — apply in this order)

1. Any confirmed **Critical** finding → `REJECTED`
2. Else any confirmed **Major** finding → `NEEDS_WORK`
3. Else any dimension's raw verdict != PASS, OR any Minor findings exist → `APPROVED_WITH_CONCERNS`
4. Else → `APPROVED`

Log: `"review-diff: <verdict> — <C> Critical, <M> Major confirmed (<Min> Minor); dimensions: <list>"`.

## Failure semantics

- A dimension reviewer that fails/returns nothing is dropped from `perDimension` (no findings contributed) — it does not block the review, but note its absence.
- A refuter delegate that fails counts as an abstention per the voting logic above (never counts as a refute vote).

## Worktree behavior

None — this runbook only reads the diff via `git diff <diffRange>`; no worktrees are created or needed.
