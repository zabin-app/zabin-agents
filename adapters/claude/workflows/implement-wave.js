export const meta = {
  name: 'implement-wave',
  description: 'Implement a wave of NON-overlapping tasks in parallel git worktrees and validate each immediately. Returns per-task branch + verdict for the conductor to merge in the main loop. Does NOT merge.',
  whenToUse: 'Dispatched by the conductor for the worktree-parallel sub-group of a wave (tasks with no write-file overlap). Sequential/overlapping tasks stay in the main loop.',
  phases: [
    { title: 'Implement', detail: 'one implementor per task, isolated worktree, model per complexity' },
    { title: 'Validate', detail: 'task_validator (haiku) checks each task as soon as it lands' },
  ],
}

// args: {
//   workingBranch: string,          // branch the conductor is on; worktrees sync to it
//   baseRef?: string,               // ref pre-created worktrees were cut from / validators diff against (default: workingBranch)
//   tasks: [{ slug, complexity, agentType, content?, path?, worktreePath? }]
// }
//
// PREFER `content`: the FULL text of the task file, read by the conductor and inlined here.
// When `content` is present the implementor never sees a filesystem path outside its own
// worktree, which is the only reliable way to stop agents writing into the user's primary
// checkout. `path` is the legacy fallback and is strictly more dangerous — see PATH_WARNING.
//
// `worktreePath` (per task): absolute path of a worktree the CONDUCTOR pre-created (for repos
// outside the session repo, e.g. an app repo the harness worktrees can't reach). When present,
// the implementor is dispatched WITHOUT harness worktree isolation and told to cd there; the
// branch is already cut from `baseRef`, so there is no sync step. The conductor owns worktree
// creation, merging, and removal. When absent, behavior is the original harness-worktree flow.
//
// Completion summaries come back through the `completionSummary` schema field; the CONDUCTOR
// writes them to the task file. An implementor must never write outside its worktree, so it
// must never be asked to update the task file itself.
//
// Tolerate args passed as a JSON-encoded string (a common dispatch mistake) as well as a real object.
const A = (() => { try { return typeof args === 'string' ? JSON.parse(args) : (args || {}) } catch { return {} } })()
const WORKING_BRANCH = A.workingBranch
const TASKS = A.tasks || []
if (!WORKING_BRANCH || !TASKS.length) {
  log('Need args.workingBranch and args.tasks[] — nothing to implement.')
  return []
}
const BASE_REF = A.baseRef || WORKING_BRANCH

const legacy = TASKS.filter(t => !t.content && t.path).length
if (legacy) log(`WARNING: ${legacy}/${TASKS.length} task(s) passed by path instead of inlined content — those implementors can see the primary checkout. Prefer args.tasks[].content.`)

// Complexity → model tier (cheap-first-pass). Conductor may pre-resolve; we default safely.
const MODEL_FOR = { low: 'haiku', medium: 'sonnet', high: 'opus' }

const IMPL_SCHEMA = {
  type: 'object',
  required: ['slug', 'status', 'branch', 'qualityGate', 'files'],
  properties: {
    slug: { type: 'string' },
    status: { type: 'string', enum: ['Done', 'Blocked', 'Failed'] },
    branch: { type: 'string', description: 'the worktree branch name the work was committed to' },
    qualityGate: { type: 'string', enum: ['PASS', 'FAIL'] },
    files: { type: 'array', items: { type: 'string' }, description: 'source files written, worktree-relative' },
    notes: { type: 'string', description: '1-2 sentence summary of key decisions or blockers' },
    docUpdatesNeeded: { type: 'string', description: 'empty unless core docs need updating' },
    completionSummary: {
      type: 'string',
      description: 'Markdown Completion Summary for the task file: files modified + what changed, notable decisions/tradeoffs, testing performed, risks. The CONDUCTOR writes this to the task file — do NOT write it to disk yourself.',
    },
    wroteOutsideWorktree: {
      type: 'boolean',
      description: 'true if you wrote ANY file outside your worktree root at any point, even if you reverted it. Answer honestly — the conductor verifies independently and an accurate report is far more useful than a clean one.',
    },
  },
}

const VALIDATION_SCHEMA = {
  type: 'object',
  required: ['verdict'],
  properties: {
    verdict: { type: 'string', enum: ['PASS', 'CONCERN', 'FAIL'] },
    criteriaUnmet: { type: 'array', items: { type: 'string' } },
    outOfScope: { type: 'array', items: { type: 'string' } },
    issues: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
}

const CONTAINMENT = `**STEP 0b — YOUR WORKTREE IS THE ONLY PLACE YOU MAY WRITE:**

\`\`\`bash
git rev-parse --show-toplevel
\`\`\`

That is \`$WT\`, your isolated worktree, and your shell's cwd is already there. **Every file you create or modify must be under \`$WT\`.** Use relative paths.

Other checkouts of this same repository exist elsewhere on this machine, including the user's live working copy holding uncommitted work. Writing into one corrupts it. So:

- Never pass an absolute path to Write/Edit. Relative paths cannot escape \`$WT\`.
- If you ever type an absolute path, verify it starts with \`$WT\` first. If it does not, stop — it is wrong.
- Never run \`git clean\`, \`git checkout --\`, \`git reset --hard\`, \`git stash\`, or \`rm\` anywhere except inside \`$WT\`, and never with a path argument pointing outside it.
- If you realise you have already written outside \`$WT\`: do NOT reach for \`git clean\`/\`checkout\`/\`reset\` to undo it — that is how uncommitted user work gets destroyed. Edit your own added lines back out by hand, then set \`wroteOutsideWorktree: true\` and say exactly what happened in \`notes\`.

You need nothing from outside \`$WT\`. The task is inlined below; do not go looking for it on disk.`

const PATH_WARNING = `**STEP 0b — WORKTREE CONTAINMENT (read carefully):**

\`\`\`bash
git rev-parse --show-toplevel
\`\`\`

That is \`$WT\`, your isolated worktree; your cwd is already there. **Every file you create or modify must be under \`$WT\`.**

You are being given a task-file path that points OUTSIDE \`$WT\`, into the user's primary checkout (the plan lives in a separate repo not present in your worktree). That path is **read-only**. You may read it. You may not write it, and you must not derive any other path from it — its parent directories are the user's live working copy, holding uncommitted work that writing there destroys.

- Never pass an absolute path to Write/Edit. Use relative paths, which cannot escape \`$WT\`.
- Do NOT append your Completion Summary to the task file. Return it in the \`completionSummary\` field instead; the conductor writes it.
- Never run \`git clean\`, \`git checkout --\`, \`git reset --hard\`, \`git stash\`, or \`rm\` outside \`$WT\`.
- If you realise you have already written outside \`$WT\`: do NOT reach for \`git clean\`/\`checkout\`/\`reset\` — that destroys uncommitted user work. Edit your own added lines back out by hand, then set \`wroteOutsideWorktree: true\` and explain in \`notes\`.`

// Shared tail: task body + docs + committing + reporting (identical for both intros).
const taskTail = (task) => `---

${task.content
  ? `## Task: ${task.slug}\n\nImplement the task specified below, according to its acceptance criteria.\n\n<task>\n${task.content}\n</task>`
  : `Implement task from: ${task.path}\n\nRead the task file and implement according to its acceptance criteria.`}

**Docs:** if the task above has a \`Docs:\` list, read exactly those — the conductor resolved them from the files you are changing. Otherwise follow docs/ARCHITECTURE.md for layer boundaries, docs/CODE_STANDARDS.md for conventions, docs/DEVELOPMENT.md for verification commands; and if docs/DOC_POLICY.md exists, the docs are split — map your write-files to their doc unit via its unit table and read that unit's doc too, since the root docs/ARCHITECTURE.md is only an index. Never edit any core doc, including colocated \`<package>/docs/*.md\` ones.

**Committing:** commit all your SOURCE changes inside \`$WT\` before reporting — the merge mechanism requires a committed branch. Commit only files under \`$WT\`; there is nothing else for you to commit.

**Reporting:** report your branch (\`git branch --show-current\`) in \`branch\`, the source files you wrote in \`files\` (worktree-relative), and your full Completion Summary markdown in \`completionSummary\` — the conductor writes that to the task file, so do not write it to disk. Set \`wroteOutsideWorktree\` honestly.`

const syncBlock = (task) => `**STEP 0 — WORKTREE SYNC (do this before anything else):**

The harness created this worktree from \`main\`, but the active working branch is \`${WORKING_BRANCH}\`. Before anything else, fast-forward your worktree to the working branch:

\`\`\`bash
git merge ${WORKING_BRANCH} --ff-only
\`\`\`

- Fast-forward succeeds, or "already up to date" → continue.
- "not possible to fast-forward" → this happens when \`main\` carries merge commits not on the working branch. Your worktree branch was freshly cut by the harness with NO work of its own, so a hard sync is lossless — but verify that first: \`git status --porcelain\` must be empty AND you must not have made any commits yet in this worktree. Both true → run \`git reset --hard ${WORKING_BRANCH}\` (this branch only; it points your fresh branch at the working-branch tip) and continue. Either false (you already changed something) → STOP and report; never reset over your own work, never rebase or non-ff merge.

${task.content ? CONTAINMENT : PATH_WARNING}

${taskTail(task)}`

// Pre-created external-repo worktree (conductor-owned): no harness isolation, no sync step.
const externBlock = (task) => `**STEP 0 — GO TO YOUR PRE-CREATED WORKTREE (do this before anything else):**

\`\`\`bash
cd ${task.worktreePath} && git rev-parse --show-toplevel && git branch --show-current
\`\`\`

That directory is \`$WT\` — a dedicated git worktree of the target repo, pre-created for this task, already on a fresh task branch cut from \`${BASE_REF}\`. \`git rev-parse --show-toplevel\` must print exactly \`${task.worktreePath}\` — if it does not, STOP and report in \`notes\`; do not work anywhere else. Do NOT create branches, do NOT run any \`git worktree\` command, do NOT sync/merge/rebase — the branch is already correct. Run every subsequent shell command from inside \`$WT\`.

**STEP 0b — \`$WT\` IS THE ONLY PLACE YOU MAY WRITE.** The surrounding directories are OTHER live checkouts on this machine — the framework checkout (reachable read-only at \`../../\` relative to \`$WT\`) and the app's primary checkout beside yours — holding the user's uncommitted work. Writing into them corrupts it. So:

- Every absolute path you pass to Write/Edit must start with \`${task.worktreePath}\`. Verify before every write; prefer relative paths from \`$WT\`.
- Relative READS of framework docs/examples (\`../../docs/...\`, \`../../examples/...\`) are fine — reads only, never writes, never edits, however wrong something there looks. If framework code seems to need a change, that is a finding for your \`notes\`, not an edit.
- Never run \`git clean\`, \`git checkout --\`, \`git reset --hard\`, \`git stash\`, or \`rm\` anywhere except inside \`$WT\`, and never with a path argument pointing outside it.
- If you realise you have already written outside \`$WT\`: do NOT reach for \`git clean\`/\`checkout\`/\`reset\` to undo it — that is how uncommitted user work gets destroyed. Edit your own added lines back out by hand, then set \`wroteOutsideWorktree: true\` and say exactly what happened in \`notes\`.

You need nothing from outside \`$WT\` except those read-only references. The task is inlined below; do not go looking for it on disk.

${taskTail(task)}`

const results = await pipeline(
  TASKS,
  // Stage 1 — implement in an isolated worktree (harness-created, or conductor-pre-created via worktreePath)
  task => {
    const opts = {
      agentType: task.agentType || 'implementor',
      model: MODEL_FOR[task.complexity] || 'sonnet',
      label: `impl:${task.slug}`,
      phase: 'Implement',
      schema: IMPL_SCHEMA,
    }
    if (!task.worktreePath) opts.isolation = 'worktree'
    return agent(task.worktreePath ? externBlock(task) : syncBlock(task), opts)
  },
  // Stage 2 — validate immediately (read-only, haiku). Skip if implement failed.
  (impl, task) => {
    if (!impl) return { task, impl: null, validation: { verdict: 'FAIL', notes: 'implementor returned no result' } }
    if (impl.status !== 'Done') return { task, impl, validation: { verdict: 'FAIL', notes: `implementor status ${impl.status}` } }
    const diffCmd = task.worktreePath
      ? `git -C ${task.worktreePath} diff ${BASE_REF}..HEAD`
      : `git diff ${WORKING_BRANCH}..${impl.branch}`
    const diffWhere = task.worktreePath
      ? `(the task's changes are committed in the pre-created worktree at ${task.worktreePath}, branched from ${BASE_REF}; run git ONLY via \`git -C ${task.worktreePath} …\`)`
      : `(the task's changes are on branch ${impl.branch}, based on ${WORKING_BRANCH})`
    return agent(
      `Validate the implementation of task \`${task.slug}\`.

Diff command: ${diffCmd}
${diffWhere}

You are READ-ONLY. Run only read-only git commands. Never run git clean/checkout/reset/stash/rm, and never modify, create, or delete any file — other checkouts of this repo exist on this machine and hold uncommitted user work.

${task.content
  ? `<task>\n${task.content}\n</task>`
  : `Task file: ${task.path} (read-only)`}

Verify every acceptance criterion, check file scope against the task's declared write-files, and scan for obvious errors. Do NOT run builds or tests.

Note: the implementor was instructed NOT to append a Completion Summary to the task file — the conductor does that. Its absence is expected and is NOT a finding.`,
      { agentType: 'task_validator', model: 'haiku', label: `validate:${task.slug}`, phase: 'Validate', schema: VALIDATION_SCHEMA }
    ).then(validation => ({ task, impl, validation }))
  }
)

const out = results.filter(Boolean).map(r => ({
  slug: r.task.slug,
  path: r.task.path || null,
  worktreePath: r.task.worktreePath || null,
  branch: r.impl?.branch || null,
  status: r.impl?.status || 'Failed',
  qualityGate: r.impl?.qualityGate || 'FAIL',
  verdict: r.validation?.verdict || 'FAIL',
  files: r.impl?.files || [],
  docUpdatesNeeded: r.impl?.docUpdatesNeeded || '',
  completionSummary: r.impl?.completionSummary || '',
  wroteOutsideWorktree: r.impl?.wroteOutsideWorktree === true,
  notes: [r.impl?.notes, r.validation?.notes].filter(Boolean).join(' | '),
}))

const pass = out.filter(t => t.verdict === 'PASS').length
const fail = out.filter(t => t.verdict === 'FAIL').length
const strayed = out.filter(t => t.wroteOutsideWorktree)
if (strayed.length) log(`CONTAINMENT BREACH self-reported by: ${strayed.map(t => t.slug).join(', ')} — conductor MUST verify the primary checkout (git status + git diff) before merging.`)
log(`implement-wave: ${pass} PASS, ${out.filter(t => t.verdict === 'CONCERN').length} CONCERN, ${fail} FAIL across ${out.length} tasks. Branches are NOT merged — conductor merges in task order. Completion summaries returned in-band for the conductor to write.`)
return out
