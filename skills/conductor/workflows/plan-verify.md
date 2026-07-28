# Plan Verify

Adversarially verify the factual assumptions in a drafted plan or TASKS.md before presenting it: one skeptic per assumption tries to refute it against the real code/docs.

**When to use:** After drafting `PLAN.md`/`BUG.md` or a `TASKS.md` breakdown, to attack every statement about existing code, file paths, layer dependencies, and library capabilities.

**Phases:**
1. **Verify** — one workhorse skeptic per assumption

## Inputs

`assumptions: [{ label, agentType, claim }]`

Extract from the draft: every statement about existing code, file paths in the File Overlap Analysis, layer-dependency assumptions, library capabilities.

If no assumptions are provided, return immediately: `{ refuted: [] }` and log "No assumptions provided — nothing to verify."

## Procedure

The conductor issues one `delegate` call per assumption directly from the main loop (parallel), since fan-out cannot be pushed down into a single recursive subagent.

For each assumption:

```
delegate(source: <agentType, default "codebase_researcher">, provider: "chatgpt_codex", model: "gpt-5.6-terra",
  instructions: "Try to REFUTE this assumption: \"<claim>\"\nInspect the actual code/docs. Default to refuted=true if you cannot confirm it with concrete evidence. Return JSON matching the Verdict Schema.",
  async: true)
```

Skeptics run on the workhorse tier (`gpt-5.6-terra`) — verification is where capability matters, so this stage is never the cheap tier.

**Verdict Schema:**
```json
{
  "refuted": "boolean — true if the assumption is wrong or unsupported",
  "reasoning": "string",
  "correction": "string — what is actually true, if refuted"
}
```

Dispatch all assumption checks in parallel, then `load(source: "<task_id>")` each.

## Output

An assumption is bad if its delegate failed OR returned `refuted: true`.

```json
{
  "refuted": [
    { "label": "...", "agentType": "...", "claim": "...", "reasoning": "...", "correction": "..." }
  ]
}
```

Log: `"<N>/<total> assumptions refuted"`.

## Failure semantics

- A skeptic delegate that fails/returns nothing counts as **refuted** (fail toward caution — an unconfirmed assumption is not safe to build on).
- The conductor must fix every refuted assumption in the plan/TASKS.md before presenting it to the user.

## Worktree behavior

None — read-only verification; no worktrees are created.
