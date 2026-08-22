export const meta = {
  name: 'research-sweep',
  description: 'Parallel deep research: fan out researchers per question, then adversarially verify every load-bearing claim before it reaches a plan',
  whenToUse: 'Pre-plan research with 3+ questions, unknown affected code area, or load-bearing assumptions that must be verified.',
  phases: [
    { title: 'Research', detail: 'haiku researchers fan out, one per question' },
    { title: 'Verify', detail: 'sonnet skeptics try to refute load-bearing claims' },
  ],
}

// args: { questions: [{ label, agentType, q }] }
//   agentType ∈ codebase_researcher (internal code) | external_researcher (web/docs) | git_historian (history)
// Tolerate args passed as a JSON-encoded string (a common dispatch mistake) as well as a real object.
const A = (() => { try { return typeof args === 'string' ? JSON.parse(args) : (args || {}) } catch { return {} } })()
const QUESTIONS = A.questions || []
if (!QUESTIONS.length) {
  log('No questions provided in args.questions — nothing to research.')
  return { answered: [], unanswered: [], refutedClaims: [] }
}

const FINDING_SCHEMA = {
  type: 'object',
  required: ['question', 'found', 'summary', 'claims'],
  properties: {
    question: { type: 'string' },
    found: { type: 'boolean', description: 'false if the answer could not be located — do not guess' },
    summary: { type: 'string', description: '2-4 sentence answer' },
    claims: {
      type: 'array',
      description: 'Atomic, checkable claims the planner may rely on',
      items: {
        type: 'object',
        required: ['claim', 'evidence', 'loadBearing'],
        properties: {
          claim: { type: 'string' },
          evidence: { type: 'string', description: 'file:line refs, URLs, or commit hashes' },
          loadBearing: { type: 'boolean', description: 'true if the plan would change were this claim false' },
        },
      },
    },
    relatedFiles: { type: 'array', items: { type: 'string' } },
    caveats: { type: 'string' },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['refuted', 'reasoning'],
  properties: {
    refuted: { type: 'boolean', description: 'true if the claim is wrong or unsupported by the code' },
    reasoning: { type: 'string' },
    correction: { type: 'string', description: 'what is actually true, if refuted' },
  },
}

// Cheap-first-pass + adversarial verify:
//   - finders run on HAIKU (broad, mechanical search/trace)
//   - each load-bearing claim is challenged by 2 SONNET skeptics; majority-refute kills it
const findings = await pipeline(
  QUESTIONS,
  item => agent(
    `${item.q}\n\nReturn a precise, evidence-backed finding. If the answer cannot be located, set found=false rather than guessing. Mark a claim loadBearing only if a plan built on it would change were the claim false.`,
    { agentType: item.agentType, model: 'haiku', label: `research:${item.label}`, phase: 'Research', schema: FINDING_SCHEMA }
  ),
  (finding, item) => {
    if (!finding || !finding.found) return { item, finding, verified: [], refuted: [], contested: [] }
    const loadBearing = finding.claims.filter(c => c.loadBearing)
    return parallel(loadBearing.flatMap(c => [0, 1].map(n => () =>
      agent(
        `Try to REFUTE this claim against the actual codebase/docs: "${c.claim}"\nEvidence offered: ${c.evidence}\nDefault to refuted=true if you cannot confirm it with concrete evidence.`,
        { agentType: item.agentType, model: 'sonnet', label: `verify:${item.label}#${n}`, phase: 'Verify', schema: VERDICT_SCHEMA }
      ).then(v => ({ claim: c, verdict: v }))
    ))).then(checks => {
      // group the 2 votes per claim
      const byClaim = new Map()
      for (const x of checks) {
        const key = x.claim.claim
        if (!byClaim.has(key)) byClaim.set(key, { claim: x.claim, votes: [] })
        byClaim.get(key).votes.push(x.verdict)
      }
      // Dead skeptics (null) abstain. Unanimous refute → refuted; split vote or no
      // surviving votes → contested (needs a human/planner look, not silently dropped);
      // unanimous confirm → verified.
      const verified = [], refuted = [], contested = []
      for (const { claim, votes } of byClaim.values()) {
        const real = votes.filter(Boolean)
        const refutes = real.filter(v => v.refuted).length
        const correction = real.find(v => v.correction)?.correction
        if (real.length && refutes === real.length) refuted.push({ ...claim, correction })
        else if (refutes || !real.length) contested.push({ ...claim, correction })
        else verified.push(claim)
      }
      return { item, finding, verified, refuted, contested }
    })
  }
)

const results = findings.filter(Boolean)
log(`${results.length}/${QUESTIONS.length} questions answered; ${results.flatMap(r => r.refuted).length} load-bearing claims refuted, ${results.flatMap(r => r.contested).length} contested`)
return {
  answered: results.filter(r => r.finding && r.finding.found),
  unanswered: results.filter(r => !r.finding || !r.finding.found).map(r => r.item.q),
  refutedClaims: results.flatMap(r => r.refuted),
  contestedClaims: results.flatMap(r => r.contested),
}
