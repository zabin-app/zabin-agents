export const meta = {
  name: 'review-diff',
  description: 'Multi-dimension code review of a diff: each review dimension finds issues, then every Critical/Major finding is adversarially verified by a panel of refuters (majority-refute drops false positives). Returns confirmed findings + a synthesized verdict.',
  whenToUse: 'Phase review of a completed feature/bug diff, or re-review of a fix diff (pass previousReview).',
  phases: [
    { title: 'Review', detail: 'one reviewer per dimension over the diff' },
    { title: 'Verify', detail: '3 haiku refuters per Critical/Major finding; majority kills false positives' },
  ],
}

// args: { diffRange, taskFiles: string[], changeType: 'feature'|'bug', previousReview?: string,
//         docs?: string[], repoRoot?: string }
//   repoRoot — absolute path of the repo the diff lives in, when it is NOT the session repo
//   (e.g. an app repo nested inside the checkout). Reviewers and refuters are told to run every
//   git command as `git -C <repoRoot> ...`. Same cross-repo extension implement-wave.js carries.
//   docs — the doc paths the conductor resolved for the units this diff touches (see conductor
//   SKILL.md "Doc routing"). On a split-doc project the root docs/ARCHITECTURE.md is only an index,
//   so reviewers must be pointed at the unit docs explicitly. Omit on a flat project.
// Tolerate args passed as a JSON-encoded string (a common dispatch mistake) as well as a real object.
const A = (() => { try { return typeof args === 'string' ? JSON.parse(args) : (args || {}) } catch { return {} } })()
const DIFF = A.diffRange || 'HEAD~1..HEAD'
const TASK_FILES = A.taskFiles || []
const CHANGE_TYPE = A.changeType || 'feature'
const PREV = A.previousReview
const DOCS = Array.isArray(A.docs) ? A.docs.filter(Boolean) : []
const REPO_ROOT = A.repoRoot
const GIT_CLAUSE = REPO_ROOT
  ? `The diff lives in the repo at ${REPO_ROOT} (NOT the session repo) — run EVERY git command as \`git -C ${REPO_ROOT} ...\` and read source files under that root. `
  : ''

const DOCS_CLAUSE = DOCS.length
  ? `Reference these docs for standards (already resolved for the units this diff touches — read these rather than hunting for others):\n${DOCS.map(d => `  - ${d}`).join('\n')}`
  : `Reference docs/ARCHITECTURE.md, docs/CODE_STANDARDS.md, docs/REVIEW_FOCUS.md for standards. If docs/DOC_POLICY.md exists, the project's docs are split: map the changed files to their doc unit via its unit table and read that unit's doc too — the root docs/ARCHITECTURE.md is only an index and will not contain module detail.`

// Dimensions map to the review agentTypes. Agents carry no model in frontmatter — the
// conductor's model strategy sets tiers here (sonnet workhorses; logic + security on opus).
const DIMENSIONS = [
  { key: 'architecture', agentType: 'architecture_enforcer', model: 'sonnet' },
  { key: 'quality', agentType: 'code_quality_inspector', model: 'sonnet' },
  { key: 'logic', agentType: 'logic_reasoning_checker', model: 'opus' },
  { key: 'risks', agentType: 'risks_tradeoffs_analyzer', model: 'sonnet' },
  { key: 'security', agentType: 'security_reviewer', model: 'opus' },
]
if (CHANGE_TYPE === 'bug') DIMENSIONS.unshift({ key: 'bugfix', agentType: 'bug_fix_reviewer', model: 'sonnet' })

const FINDINGS_SCHEMA = {
  type: 'object',
  required: ['dimension', 'verdict', 'findings'],
  properties: {
    dimension: { type: 'string' },
    verdict: { type: 'string', enum: ['PASS', 'CONCERNS', 'FAIL'] },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['title', 'severity', 'problem'],
        properties: {
          title: { type: 'string' },
          file: { type: 'string' },
          line: { type: 'string' },
          severity: { type: 'string', enum: ['Critical', 'Major', 'Minor'] },
          problem: { type: 'string' },
          recommendation: { type: 'string' },
        },
      },
    },
  },
}

const REFUTE_SCHEMA = {
  type: 'object',
  required: ['refuted', 'reasoning'],
  properties: {
    refuted: { type: 'boolean', description: 'true if the finding is NOT a real problem in this diff (false positive, pre-existing, or misread)' },
    reasoning: { type: 'string' },
  },
}

const reviewPrompt = (d) => `Review the following code change as your dimension (${d.key}).

Diff range: git diff ${DIFF}
${GIT_CLAUSE ? GIT_CLAUSE + '\n' : ''}Task files (acceptance criteria / scope): ${TASK_FILES.join(', ') || '(none provided)'}
${PREV ? `\nRE-REVIEW MODE — a previous review exists at: ${PREV}. Verify prior Critical/Major findings are resolved and review THIS fix diff with full rigor. Do NOT re-litigate unchanged code; new issues in untouched code are out of scope unless newly CRITICAL.\n` : ''}
Treat the diff as the source of truth — distinguish code introduced by this change from pre-existing code (you have read-only git access). ${DOCS_CLAUSE} Rate each finding's severity honestly (Critical / Major / Minor).`

// Pipeline: each dimension reviews, then its Critical/Major findings are adversarially verified
// as soon as that dimension returns — no barrier between dimensions.
const reviewed = await pipeline(
  DIMENSIONS,
  d => agent(reviewPrompt(d), { agentType: d.agentType, model: d.model, label: `review:${d.key}`, phase: 'Review', schema: FINDINGS_SCHEMA }),
  (review, d) => {
    if (!review || !review.findings?.length) return { dimension: d.key, raw: review, confirmed: [], minors: [] }
    const blocking = review.findings.filter(f => f.severity === 'Critical' || f.severity === 'Major')
    const minors = review.findings.filter(f => f.severity === 'Minor')
    if (!blocking.length) return { dimension: d.key, raw: review, confirmed: [], minors }
    return parallel(blocking.map(f => () =>
      parallel([0, 1, 2].map(n => () =>
        agent(
          `A ${d.key} reviewer flagged this ${f.severity} finding on diff \`${DIFF}\`:\n${GIT_CLAUSE ? '\n' + GIT_CLAUSE + '\n' : ''}\nTitle: ${f.title}\nFile: ${f.file || '?'}:${f.line || '?'}\nProblem: ${f.problem}\n\nTry to REFUTE it: is this actually a real problem introduced by THIS diff? Default refuted=true if it is a false positive, pre-existing, or a misread.`,
          { model: 'haiku', label: `verify:${d.key}#${n}`, phase: 'Verify', schema: REFUTE_SCHEMA }
        )
      )).then(votes => {
        // Dead voters (null) abstain — an infra failure is not a refutation. A finding is
        // dropped only when a majority of ACTUAL votes refute it; if every voter died,
        // the finding survives (fail toward blocking, never toward silently approving).
        const real = votes.filter(Boolean)
        const refutes = real.filter(v => v.refuted).length
        return { finding: { ...f, dimension: d.key }, survived: !real.length || refutes * 2 <= real.length }
      })
    )).then(checked => ({
      dimension: d.key,
      raw: review,
      confirmed: checked.filter(c => c.survived).map(c => c.finding),
      minors,
    }))
  }
)

const rows = reviewed.filter(Boolean)
const confirmed = rows.flatMap(r => r.confirmed)
const minors = rows.flatMap(r => r.minors)
const crit = confirmed.filter(f => f.severity === 'Critical')
const major = confirmed.filter(f => f.severity === 'Major')
const anyConcern = rows.some(r => r.raw && r.raw.verdict !== 'PASS') || minors.length > 0

// Synthesis honors the severity floor: NEEDS_WORK/REJECTED require a confirmed Critical/Major.
let verdict
if (crit.length) verdict = 'REJECTED'
else if (major.length) verdict = 'NEEDS_WORK'
else if (anyConcern) verdict = 'APPROVED_WITH_CONCERNS'
else verdict = 'APPROVED'

log(`review-diff: ${verdict} — ${crit.length} Critical, ${major.length} Major confirmed (${minors.length} Minor); dimensions: ${rows.map(r => r.dimension).join(', ')}`)
return {
  verdict,
  diffRange: DIFF,
  reReview: !!PREV,
  confirmed,
  minors,
  perDimension: rows.map(r => ({ dimension: r.dimension, verdict: r.raw?.verdict || 'PASS', confirmedCount: r.confirmed.length, minorCount: r.minors.length })),
}
