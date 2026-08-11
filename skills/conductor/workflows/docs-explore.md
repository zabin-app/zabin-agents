# Docs Explore

Explore a codebase in parallel, one bounded research role per subsystem, and return compact architecture-altitude maps plus a flat-versus-hub-and-spoke recommendation. This runbook is read-only and feeds [docs-sync](../../docs-sync/SKILL.md); it never writes documentation or creates worktrees.

## Inputs and preconditions

Input:

```json
{"subsystems": [{"label": "string", "path": "repository-relative path"}]}
```

Resolve the repository root with `git.inspect`. Before dispatch, read the [portable role registry](../../../config/agents.json) and map the semantic host operations `agent.dispatch` and `agent.wait` from the conductor's [host-capability contract](../references/host-capabilities.md). Use the registered `codebase_researcher` role and its exact input/output schemas. The registry selects the role's tier; the host resolves that tier. Do not name a client, provider, concrete model, transport-qualified tool, or host-specific spawn command in the program.

Reject absolute paths, paths outside the repository, duplicate labels, and overlapping subsystem paths unless the overlap is intentional and explained by the caller. If the list is empty, return immediately:

```json
{"maps": [], "recommendedStructure": "flat", "rationale": "no input"}
```

Report `No subsystems provided — nothing to explore.`

## Map schema

The main loop synthesizes each successful registered research result into this shape:

```json
{
  "subsystem": "string",
  "path": "string",
  "responsibility": "one or two sentences",
  "keyModules": [
    {"name": "string", "responsibility": "one line"}
  ],
  "dependencies": ["other subsystem or module"],
  "keyPublicTypes": [
    {"name": "string", "purpose": "one line"}
  ],
  "dataFlows": ["high-level flow in one line"],
  "devSignals": {
    "buildRunTestCommands": ["observed command"],
    "conventionsObserved": ["observed convention"]
  },
  "estimatedDocLines": 0
}
```

`estimatedDocLines` is the number of architecture lines the subsystem warrants after trimming, normally a few dozen rather than hundreds.

## Procedure

### 1. Dispatch bounded research in parallel

For each subsystem, validate this exact registered role input before calling `agent.dispatch`:

```json
{
  "objective": "Produce evidence for a compact architecture-altitude map of the named subsystem: its responsibility, handful of key modules, dependencies, central public types, high-level data flows, and observed development commands or conventions. Omit private implementation detail, per-file tours, field-level descriptions, step-by-step algorithms, and historical narrative.",
  "scope": ["<subsystem path>"],
  "context": {
    "subsystem_label": "<label>",
    "deliverable": "docs-explore map evidence"
  }
}
```

Issue all independent dispatches before waiting. Bind each dispatch to the same repository and read-only role scope. Retain the dispatch id, subsystem label, and path in main-loop state; do not put host metadata into the closed role input.

Collect results with `agent.wait` using bounded host monitoring. Validate every untouched result against the registered `codebase_researcher` output schema. A missing, timed-out, cancelled, partial-without-evidence, or schema-invalid result fails that subsystem closed.

### 2. Synthesize and trim in the main loop

For each successful research result:

1. Build one map only from cited repository evidence. Put uncertainty in the run summary rather than inventing a field value.
2. Keep only modules and public types needed to explain the subsystem's shape.
3. Remove private symbols, field or column detail, file-by-file inventories, algorithms, recovery/idempotency walkthroughs, dates, and “Phase N” history.
4. Keep responsibilities and flows to one line each. Preserve observed commands and conventions only under `devSignals`; they do not belong in architecture prose.
5. Estimate the resulting architecture footprint and validate the map against the schema above.

This deterministic main-loop trim replaces an unregistered free-form second agent. Agents never dispatch other agents, and no child result is accepted under an invented output contract.

## Output and recommendation

Return:

```json
{
  "maps": ["successfully synthesized maps"],
  "recommendedStructure": "flat | hub-and-spoke",
  "rationale": "string"
}
```

Compute `totalLines = sum(map.estimatedDocLines)`. If more than one map succeeds and `totalLines > 450`, recommend `hub-and-spoke` because the material would approach the 500-line hard cap. Otherwise recommend `flat`.

Report `docs-explore: <N> subsystem maps, ~<totalLines> estimated ARCHITECTURE lines → recommend <structure>`.

## Failure semantics

- Drop a failed subsystem entirely; never include partial or fabricated map data.
- If every subsystem fails, return an empty `maps` array, recommend `flat`, and explain that no documentation rebuild may proceed from unverified maps.
- Preserve caveats and dispatch failures in the run summary so `docs-sync` can pause rather than overwrite docs from incomplete evidence.
- A missing safe mapping for either `agent.dispatch` or `agent.wait` is a blocking host-capability error.
