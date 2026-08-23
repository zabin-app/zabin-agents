export const meta = {
  name: 'followup-investigate',
  description: 'Root-cause investigation of code-review findings: investigate each Critical/Major issue, then cross-check the diagnosis before it becomes a fix task. Filters out findings that do not reproduce.',
  whenToUse: 'Conductor followup loop, when a review verdict is NEEDS_WORK/REJECTED and there are findings to diagnose before writing fix tasks.',
  phases: [
    { title: 'Investigate', detail: 'one investigator per issue (sonnet) — confirm it reproduces' },
    { title: 'Cross-check', detail: 'a second sonnet pass refutes the diagnosis before tasking' },
  ],
}

// args: { issues: [{ label, text }] }  — paste the full finding text per Critical/Major item.
// Tolerate args passed as a JSON-encoded string (a common dispatch mistake) as well as a real object.
const A = (() => { try { return typeof args === 'string' ? JSON.parse(args) : (args || {}) } catch { return {} } })()
const ISSUES = A.issues || []
if (!ISSUES.length) {
  log('No issues provided in args.issues — nothing to investigate.')
  return { taskable: [], contested: [], notReproduced: [] }
}

const DIAGNOSIS_SCHEMA = {
  type: 'object',
  required: ['issue', 'confirmed', 'rootCause', 'fixApproach', 'filesToChange'],
  properties: {
    issue: { type: 'string' },
    confirmed: { type: 'boolean', description: 'false if the finding does not reproduce in the code' },
    rootCause: { type: 'string', description: 'file:line and mechanism' },
    fixApproach: { type: 'string' },
    filesToChange: { type: 'array', items: { type: 'string' } },
    regressionRisk: { type: 'string' },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['refuted', 'reasoning'],
  properties: {
    refuted: { type: 'boolean', description: 'true if the diagnosis/fix is wrong, incomplete, or would regress' },
    reasoning: { type: 'string' },
    correction: { type: 'string' },
  },
}

const diagnoses = await pipeline(
  ISSUES,
  i => agent(
    `Investigate this code-review finding and locate its root cause:\n\n${i.text}\n\nVerify the issue actually exists in the code before diagnosing. If it does not reproduce, set confirmed=false and explain.`,
    { agentType: 'codebase-researcher', model: 'sonnet', label: `investigate:${i.label}`, phase: 'Investigate', schema: DIAGNOSIS_SCHEMA }
  ),
  (d, i) => !d || !d.confirmed ? { item: i, diagnosis: d, upheld: false } :
    agent(
      `A diagnosis claims the root cause of "${i.label}" is: ${d.rootCause} with fix: ${d.fixApproach}. Try to REFUTE it — is the root cause correct, and would the fix be complete without regressions? Default refuted=true if unconvinced.`,
      { agentType: 'codebase-researcher', model: 'sonnet', label: `crosscheck:${i.label}`, phase: 'Cross-check', schema: VERDICT_SCHEMA }
    ).then(v => ({ item: i, diagnosis: d, upheld: !!v && !v.refuted, dissent: v?.correction }))
)

const res = diagnoses.filter(Boolean)
log(`followup-investigate: ${res.filter(x => x.upheld).length} taskable, ${res.filter(x => x.diagnosis?.confirmed && !x.upheld).length} contested, ${res.filter(x => x.diagnosis && !x.diagnosis.confirmed).length} not reproduced`)
return {
  taskable: res.filter(x => x.upheld).map(x => x.diagnosis),
  contested: res.filter(x => x.diagnosis?.confirmed && !x.upheld).map(x => ({ ...x.diagnosis, dissent: x.dissent })),
  notReproduced: res.filter(x => x.diagnosis && !x.diagnosis.confirmed).map(x => x.diagnosis.issue),
}
