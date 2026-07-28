# Research Sweep

Parallel deep research: fan out researchers per question, then adversarially verify every load-bearing claim before it reaches a plan.

**When to use:** Pre-plan research with 3+ questions, unknown affected code area, or load-bearing assumptions that must be verified.

**Phases:**
1. **Research** — cheap researchers fan out, one per question
2. **Verify** — workhorse skeptics try to refute load-bearing claims

## Inputs

`questions: [{ label, agentType, q }]`

`agentType` ∈ `codebase_researcher` (internal code) | `external_researcher` (web/docs) | `git_historian` (history)

If no questions are provided, return immediately: `{ answered: [], unanswered: [], refutedClaims: [], contestedClaims: [] }` and log "No questions provided — nothing to research."

## Procedure

This runbook is executed by the conductor issuing `delegate` calls directly from the main loop (a single delegated subagent cannot itself fan out to further subagents recursively, so the conductor is the fan-out point).

### Stage 1 — Research (parallel, one per question)

For each question in `questions`, issue:

```
delegate(source: <agentType>, provider: "github_copilot", model: "claude-haiku-4.5",
  instructions: "<q>\n\nReturn a precise, evidence-backed finding. If the answer cannot be located, set found=false rather than guessing. Mark a claim loadBearing only if a plan built on it would change were the claim false. Structure your final answer as JSON matching the Finding Schema below.",
  async: true)
```

Dispatch all questions' delegate calls together, then `load(source: "<task_id>")` each to collect results.

**Finding Schema** (each researcher must return JSON matching this shape):
```json
{
  "question": "string",
  "found": "boolean — false if the answer could not be located; do not guess",
  "summary": "string — 2-4 sentence answer",
  "claims": [
    {
      "claim": "string",
      "evidence": "string — file:line refs, URLs, or commit hashes",
      "loadBearing": "boolean — true if the plan would change were this claim false"
    }
  ],
  "relatedFiles": ["string"],
  "caveats": "string"
}
```

### Stage 2 — Verify (parallel, 2 skeptics per load-bearing claim)

For each finding where `found=true`, collect its claims where `loadBearing=true`. For each such claim, issue **2** parallel skeptic delegations:

```
delegate(source: <same agentType as the research question>, provider: "github_copilot", model: "claude-sonnet-5",
  instructions: "Try to REFUTE this claim against the actual codebase/docs: \"<claim>\"\nEvidence offered: <evidence>\nDefault to refuted=true if you cannot confirm it with concrete evidence. Return JSON matching the Verdict Schema.",
  async: true)
```

**Verdict Schema:**
```json
{
  "refuted": "boolean",
  "reasoning": "string",
  "correction": "string — what is actually true, if refuted"
}
```

### Voting logic (per claim, 2 votes)

- Dead/failed skeptics (no result) **abstain** — do not count as votes either way.
- If both surviving votes agree `refuted=true` → claim is **refuted**.
- If votes split, or **zero** surviving votes → claim is **contested** (needs a human/planner look — never silently dropped).
- If both surviving votes agree `refuted=false` → claim is **verified**.

## Output

Aggregate across all questions:

```json
{
  "answered": ["findings where found=true"],
  "unanswered": ["question text, for findings where found=false or missing"],
  "refutedClaims": ["claims voted refuted, with correction if given"],
  "contestedClaims": ["claims voted contested, with correction if given"]
}
```

Log a one-line summary: `"<N>/<total> questions answered; <R> load-bearing claims refuted, <C> contested"`.

## Failure semantics

- A question whose researcher delegate fails/returns nothing counts as `unanswered`.
- A claim whose both skeptic votes fail counts as `contested` (fail toward caution, never toward silent approval).
- Never treat a refuted or contested claim as verified in the calling plan — the conductor must route these into the plan's **Edge Cases & Risks** section, never the body.

## Worktree behavior

None — this runbook is read-only research; no worktrees are created.
