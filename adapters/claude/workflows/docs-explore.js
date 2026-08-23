export const meta = {
  name: 'docs-explore',
  description: 'Explore a codebase in parallel (one agent per subsystem) and return a compact, architecture-altitude map per subsystem, plus a flat / hub-and-spoke / per-module structure recommendation. Feeds a docs rebuild — does NOT write docs.',
  whenToUse: 'Dispatched by the docs-sync skill to ground a compact docs rebuild in the current code. Use when core docs have drifted or bloated and need reconstruction rather than incremental edits.',
  phases: [
    { title: 'Explore', detail: 'sonnet explorer per subsystem builds a compact map (the map is the deliverable)' },
    { title: 'Trim', detail: 'sonnet altitude-check strips implementation detail from each map' },
  ],
}

// args: {
//   subsystems: [{ label, path }],   — one per DOC UNIT (docs-sync groups packages into units first)
//   scale?: 'small'|'medium'|'large',— budget tier, measured by docs-sync from source LOC (not file count)
//   unitCount?: number,              — doc units after grouping (defaults to subsystems.length)
//   packageCount?: number,           — raw manifest count, for reporting only
//   stacks?: number,                 — distinct tech stacks (defaults to 1)
//   pinnedStructure?: string,        — a `Set by: user` DOC_POLICY.md structure; short-circuits the recommendation
// }
// Tolerate args passed as a JSON-encoded string (a common dispatch mistake) as well as a real object.
const A = (() => { try { return typeof args === 'string' ? JSON.parse(args) : (args || {}) } catch { return {} } })()
const SUBSYSTEMS = A.subsystems || []
if (!SUBSYSTEMS.length) {
  log('No subsystems provided in args.subsystems — nothing to explore.')
  return { maps: [], recommendedStructure: 'flat', rationale: 'no input' }
}

// Per-doc caps by budget tier — must stay in sync with schemas.md → Project Scale & Size Budgets.
const CAPS = { small: 400, medium: 500, large: 600 }
const SCALE = CAPS[A.scale] ? A.scale : 'medium'
const CAP = CAPS[SCALE]

const MAP_SCHEMA = {
  type: 'object',
  required: ['subsystem', 'responsibility', 'keyModules', 'dependencies', 'estimatedDocLines'],
  properties: {
    subsystem: { type: 'string' },
    path: { type: 'string' },
    responsibility: { type: 'string', description: '1-2 sentences: what this subsystem is for' },
    keyModules: {
      type: 'array',
      description: 'The handful of modules that matter, one line of responsibility each — NOT every file',
      items: {
        type: 'object',
        required: ['name', 'responsibility'],
        properties: { name: { type: 'string' }, responsibility: { type: 'string' } },
      },
    },
    dependencies: { type: 'array', items: { type: 'string' }, description: 'other subsystems/modules this one depends on' },
    keyPublicTypes: {
      type: 'array',
      items: { type: 'object', required: ['name', 'purpose'], properties: { name: { type: 'string' }, purpose: { type: 'string' } } },
      description: 'central public types/traits/interfaces — minimal, no field-level detail',
    },
    dataFlows: { type: 'array', items: { type: 'string' }, description: 'high-level flows, one line each' },
    devSignals: {
      type: 'object',
      description: 'signals for DEVELOPMENT.md / CODE_STANDARDS.md (not for ARCHITECTURE.md)',
      properties: {
        buildRunTestCommands: { type: 'array', items: { type: 'string' } },
        conventionsObserved: { type: 'array', items: { type: 'string' } },
      },
    },
    estimatedDocLines: { type: 'number', description: 'how many ARCHITECTURE lines this subsystem honestly warrants at map altitude (a few dozen, not hundreds)' },
  },
}

// Explore (sonnet — the map IS the deliverable and is only thinly checked downstream)
// → altitude-trim (sonnet, strips low-altitude detail).
const maps = await pipeline(
  SUBSYSTEMS,
  s => agent(
    `Explore the subsystem at \`${s.path}\` (${s.label}) and produce a COMPACT, architecture-altitude map of it.

Capture: its responsibility, the handful of key modules (one line each — not every file), what it depends on, its central public types, and its high-level data flows. Note any build/run/test commands and coding conventions you observe under devSignals (those feed other docs, not ARCHITECTURE).

Stay at map altitude: describe the SHAPE, not the implementation. Do NOT enumerate every file, describe private functions/fields/columns step by step, or narrate history ("Phase N"). estimatedDocLines should be a few dozen at most.`,
    { agentType: 'codebase-researcher', model: 'sonnet', label: `explore:${s.label}`, phase: 'Explore', schema: MAP_SCHEMA }
  ),
  (map, s) => {
    if (!map) return null
    return agent(
      `Here is a draft architecture map for subsystem "${s.label}":\n\n${JSON.stringify(map, null, 2)}\n\nTrim it to architecture altitude. REMOVE: any keyModule/type that is private implementation detail, any step-by-step or field/column-level description, any per-file enumeration, and any historical/"Phase N" framing. Keep responsibilities to one tight line. Return the trimmed map in the same schema; lower estimatedDocLines if you cut substantially.`,
      { model: 'sonnet', label: `trim:${s.label}`, phase: 'Trim', schema: MAP_SCHEMA }
    )
  }
)

const out = maps.filter(Boolean)
const totalLines = out.reduce((n, m) => n + (m.estimatedDocLines || 0), 0)
const units = A.unitCount || out.length
const packages = A.packageCount || units
const stacks = A.stacks || 1

// Structure is set by DOC-UNIT count (packages already grouped by docs-sync), then escalated if
// the material genuinely won't fit the tier cap at correct altitude. See schemas.md → Doc Structure.
// A pinned `Set by: user` policy short-circuits the whole decision.
const recommend = () => {
  if (A.pinnedStructure) {
    return [A.pinnedStructure, `pinned by docs/DOC_POLICY.md (Set by: user) — not re-derived.`]
  }
  if (units >= 9) {
    return ['per-module', `${units} doc units; give each its own doc and keep a linked root index.`]
  }
  if (units >= 4 || stacks >= 2) {
    return ['hub-and-spoke', `${units} doc units across ${stacks} stack(s); split into per-unit spokes with a linked index.`]
  }
  if (out.length > 1 && totalLines > CAP - 50) {
    return ['hub-and-spoke', `only ${units} unit(s), but ~${totalLines} lines of material crowds the ${SCALE} cap of ${CAP}; escalate one rung rather than truncating.`]
  }
  return ['flat', `${units} unit(s), ~${totalLines} lines — fits one flat doc set under the ${SCALE} cap of ${CAP}.`]
}
const [recommendedStructure, rationale] = recommend()

// Grouping sanity check — surface it rather than silently accepting a filing-cabinet split.
const grouping = units > 12
  ? `WARNING: ${units} doc units is likely under-grouped (target 5-12) — merge homogeneous families and exclude example/benchmark packages.`
  : (packages > 12 && units < 4)
    ? `WARNING: ${packages} packages collapsed to only ${units} unit(s) — likely under-split; docs will pin at cap.`
    : null
if (grouping) log(`docs-explore: ${grouping}`)

log(`docs-explore: ${out.length} maps, ${units} units from ${packages} packages, ${stacks} stack(s), ~${totalLines} est. ARCHITECTURE lines, ${SCALE} tier (cap ${CAP}) → recommend ${recommendedStructure}`)
return {
  maps: out,
  recommendedStructure,
  rationale,
  scale: SCALE,
  perDocCap: CAP,
  unitCount: units,
  packageCount: packages,
  stacks,
  estimatedTotalLines: totalLines,
  groupingWarning: grouping,
}
