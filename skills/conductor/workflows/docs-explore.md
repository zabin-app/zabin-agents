# Docs Explore

Explore a codebase in parallel (one agent per subsystem) and return a compact, architecture-altitude map per subsystem, plus a flat-vs-hub-and-spoke recommendation. Feeds a docs rebuild — does NOT write docs.

**When to use:** Followed by the `docs-sync` skill to ground a compact docs rebuild in the current code. Use when core docs have drifted or bloated and need reconstruction rather than incremental edits.

**Phases:**
1. **Explore** — workhorse-tier explorer per subsystem builds a compact map (the map is the deliverable)
2. **Trim** — workhorse-tier altitude-check strips implementation detail from each map

## Inputs

`subsystems: [{ label, path }]` — the docs-sync skill discovers these from manifests/top-level dirs.

If no subsystems are provided, return immediately: `{ maps: [], recommendedStructure: "flat", rationale: "no input" }` and log "No subsystems provided — nothing to explore."

## Procedure

Executed by the conductor (or the `docs-sync` skill acting as conductor) issuing `delegate` calls directly from the main loop, one pair (explore → trim) per subsystem.

### Stage 1 — Explore (parallel, one per subsystem, workhorse tier)

For each subsystem, dispatch:

```
delegate(source: "codebase_researcher", provider: "chatgpt_codex", model: "gpt-5.6-terra",
  instructions: "Explore the subsystem at `<path>` (<label>) and produce a COMPACT, architecture-altitude map of it.

Capture: its responsibility, the handful of key modules (one line each — not every file), what it depends on, its central public types, and its high-level data flows. Note any build/run/test commands and coding conventions you observe under devSignals (those feed other docs, not ARCHITECTURE).

Stay at map altitude: describe the SHAPE, not the implementation. Do NOT enumerate every file, describe private functions/fields/columns step by step, or narrate history ('Phase N'). estimatedDocLines should be a few dozen at most. Return JSON matching the Map Schema.",
  working_dir: "<repo path>",
  async: true)
```

**Map Schema:**
```json
{
  "subsystem": "string",
  "path": "string",
  "responsibility": "string — 1-2 sentences: what this subsystem is for",
  "keyModules": [
    { "name": "string", "responsibility": "string — the handful that matter, one line each, NOT every file" }
  ],
  "dependencies": ["string — other subsystems/modules this one depends on"],
  "keyPublicTypes": [
    { "name": "string", "purpose": "string — central public types/traits/interfaces, minimal, no field-level detail" }
  ],
  "dataFlows": ["string — high-level flows, one line each"],
  "devSignals": {
    "buildRunTestCommands": ["string"],
    "conventionsObserved": ["string"]
  },
  "estimatedDocLines": "number — how many ARCHITECTURE lines this subsystem honestly warrants at map altitude (a few dozen, not hundreds)"
}
```

`load(source: "<task_id>")` each explore result as it completes.

### Stage 2 — Trim (per subsystem, workhorse tier, chained after its own explore)

For each subsystem's returned map, dispatch a trim pass:

```
delegate(source: none, provider: "chatgpt_codex", model: "gpt-5.6-terra",
  instructions: "Here is a draft architecture map for subsystem \"<label>\":

<map JSON>

Trim it to architecture altitude. REMOVE: any keyModule/type that is private implementation detail, any step-by-step or field/column-level description, any per-file enumeration, and any historical/'Phase N' framing. Keep responsibilities to one tight line. Return the trimmed map in the same Map Schema; lower estimatedDocLines if you cut substantially.",
  async: true)
```

If a subsystem's explore delegate failed/returned nothing, skip it entirely (no trim call, not included in output).

## Output

```json
{
  "maps": ["all successfully trimmed per-subsystem maps"],
  "recommendedStructure": "flat | hub-and-spoke",
  "rationale": "string"
}
```

**Recommendation rule:** compute `totalLines = sum(map.estimatedDocLines)` across all maps. If `maps.length > 1 AND totalLines > 450` → `hub-and-spoke` (rationale: "`<N>` subsystems totalling ~`<totalLines>` lines exceed a single 500-line doc; split into per-subsystem spokes with a linked index."). Otherwise → `flat` (rationale: "Material fits one flat doc set (~`<totalLines>` lines).").

Log: `"docs-explore: <N> subsystem maps, ~<totalLines> estimated ARCHITECTURE lines → recommend <recommendedStructure>"`.

## Failure semantics

- A subsystem whose explore delegate fails is dropped entirely from `maps` (not retried, not included with partial data) — the recommendation is computed only over the subsystems that succeeded.
- A subsystem whose trim delegate fails: fall back to the untrimmed explore result for that subsystem rather than dropping it, since the explore output is still usable material for the rebuild (note this deviation to the user if it occurs).

## Worktree behavior

None — this runbook only reads the codebase; no worktrees are created. It never writes any doc files; writing is done later by `doc_maintainer` in the `docs-sync` skill's main loop.
