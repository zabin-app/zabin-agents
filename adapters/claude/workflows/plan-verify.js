export const meta = {
  name: 'plan-verify',
  description: 'Adversarially verify the factual assumptions in a drafted plan or TASKS.md before presenting it: one skeptic per assumption tries to refute it against the real code/docs',
  whenToUse: 'After drafting PLAN.md/BUG.md or a TASKS.md breakdown, to attack every statement about existing code, file paths, layer dependencies, and library capabilities.',
  phases: [{ title: 'Verify', detail: 'one sonnet skeptic per assumption' }],
}

// args: { assumptions: [{ label, agentType, claim }] }
//   Extract from the draft: every statement about existing code, file paths in the
//   File Overlap Analysis, layer-dependency assumptions, library capabilities.
// Tolerate args passed as a JSON-encoded string (a common dispatch mistake) as well as a real object.
const A = (() => { try { return typeof args === 'string' ? JSON.parse(args) : (args || {}) } catch { return {} } })()
const ASSUMPTIONS = A.assumptions || []
if (!ASSUMPTIONS.length) {
  log('No assumptions provided in args.assumptions — nothing to verify.')
  return { refuted: [] }
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['refuted', 'reasoning'],
  properties: {
    refuted: { type: 'boolean', description: 'true if the assumption is wrong or unsupported' },
    reasoning: { type: 'string' },
    correction: { type: 'string', description: 'what is actually true, if refuted' },
  },
}

// Sonnet skeptics — verification is where capability matters, so this stage is not haiku.
const checks = await parallel(ASSUMPTIONS.map(a => () =>
  agent(
    `Try to REFUTE this assumption: "${a.claim}"\nInspect the actual code/docs. Default to refuted=true if you cannot confirm it with concrete evidence.`,
    { agentType: a.agentType || 'codebase_researcher', model: 'sonnet', label: `verify:${a.label}`, phase: 'Verify', schema: VERDICT_SCHEMA }
  ).then(v => ({ assumption: a, verdict: v }))
))

const bad = checks.filter(Boolean).filter(x => !x.verdict || x.verdict.refuted)
log(`${bad.length}/${ASSUMPTIONS.length} assumptions refuted`)
return { refuted: bad.map(x => ({ ...x.assumption, reasoning: x.verdict?.reasoning, correction: x.verdict?.correction })) }
