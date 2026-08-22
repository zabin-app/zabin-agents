# Claude Code Adapter Notes

Host-specific translation for one client. The [conductor skill](../SKILL.md) and every other reference stay host-neutral; nothing here is a portable requirement, and a host without these primitives runs the same states through whatever it does provide. Read this file only when the running host is Claude Code.

## Capability mapping

| Portable capability | Claude Code primitive |
|---|---|
| `mcp.discover`, `mcp.call` | The configured MCP servers, addressed as `mcp__<server>__<tool>` |
| `filesystem.read`, `filesystem.search` | Read, Glob, Grep |
| `filesystem.write` | Write, Edit |
| `process.run`, `git.*` | Bash, in the main loop for every topology and merge operation |
| `agent.dispatch` | A workflow program dispatched by name, or a single subagent dispatched directly |
| `agent.wait` | The background completion notification a dispatched program raises; a blocking monitor for a long command |
| `human.prompt` | A pause in the main chat |
| `human.wait_event` | `zabctl events --project <id> --exit-on '<event>' --timeout <secs>`, blocked on rather than polled; exit `0` matched, exit `6` timed out |

An event is a wake-up, never proof: confirm plan approval with a `get_plan` read after either exit code.

## Server qualification and the same-session boundary

The canonical policy in [`config/zabin-mcp.json`](../../../config/zabin-mcp.json) owns the surface identities, URLs, and credential environment variables; do not restate them here or in a prompt. Its client server keys qualify as `mcp__zabin__<tool>` for the conductor surface and `mcp__zabin-worker__<tool>` for the worker surface. `zabctl agents render --target claude_code` produces the `.mcp.json` and `.claude/settings.json` that register them (bearer values read from the environment), plus one `.claude/agents/<role>.md` subagent definition per registered role — the frontmatter `tools:` allowlists below are rendered from `config/agents.json`, not hand-maintained.

Both servers are registered in one session, so every subagent process can reach both listeners regardless of which one its dispatch text names (Invariant 11 in the skill). The enforcement here is the dispatched agent type's frontmatter `tools:` allowlist: an implementor must be granted `mcp__zabin-worker__*` and nothing more. An agent type carrying `tools: '*'` or the conductor grant can claim, verdict, and complete its own card from inside its worktree, whatever the stub says.

## Workflow programs

The six programs are carried in this repository at [`adapters/claude/workflows/`](../../../adapters/claude/workflows) and belong in Claude Code's user workflow directory, `~/.claude/workflows/`. `zabctl agents install` lays them there for the `claude_code` target — manifest-tracked byte copies, tombstoned when a program leaves this payload, refused if an unowned file already sits at the path. Never edit the installed copy; it is downstream of this repository.

Dispatch one by name with the Workflow tool — `Workflow({name: "review-diff", args: {…}})` — passing inputs as the `args` object documented in that program's header. Programs run in the background and notify on completion. A program returns synthesized data and persists nothing: no MCP call, no ledger, no merge. The main loop writes every result to Zabin in the same turn it arrives.

| Portable program | `name` | `args` | Returns |
|---|---|---|---|
| [Research sweep](../workflows/research-sweep.md) | `research-sweep` | `{questions:[{label, agentType, q}]}` | `{answered, unanswered, refutedClaims, contestedClaims}` |
| [Plan verification](../workflows/plan-verify.md) | `plan-verify` | `{assumptions:[{label, agentType, claim}]}` | `{refuted:[…]}` |
| [Wave implementation](../workflows/implement-wave.md) | `implement-wave` | `{workingBranch, baseRef?, tasks:[{slug, complexity, agentType, content, worktreePath?}]}` | per task `{slug, branch, status, qualityGate, files, notes, docUpdatesNeeded, completionSummary, wroteOutsideWorktree}` |
| [Diff review](../workflows/review-diff.md) | `review-diff` | `{diffRange, changeType, taskFiles?, docs?, previousReview?, repoRoot?}` | `{verdict, confirmed, minors, perDimension}` |
| [Follow-up investigation](../workflows/followup-investigate.md) | `followup-investigate` | `{issues:[{label, text}]}` | `{taskable, contested, notReproduced}` |
| [Documentation exploration](../workflows/docs-explore.md) | `docs-explore` | `{subsystems:[{label, path}], scale?, unitCount?, packageCount?, stacks?, pinnedStructure?}` | `{maps, recommendedStructure, rationale}` |

`implement-wave` carries the dispatch text in `tasks[].content` — the identity stub described in the skill's State 4, never a `path`. The legacy `path` form hands an implementor a filesystem location outside its own worktree, which is how work lands in the user's primary checkout. `worktreePath` names a worktree the main loop pre-created; worktree creation, merging, and removal stay in the main loop either way. `review-diff`'s `taskFiles` stays empty: task text lives in Zabin.

## Tier strings

The portable registry in [`config/model-tiers.json`](../../../config/model-tiers.json) has three tiers. Their adapter spellings:

| Zabin complexity | Portable tier | `implement-wave` `complexity` | Program's model |
|---|---|---|---|
| `trivial`, `simple` | `fast` | `low` | haiku |
| `moderate` | `balanced` | `medium` | sonnet |
| `complex`, `epic` | `deep` | `high` | opus |

The `low`/`medium`/`high` strings are the program's own vocabulary and are not Zabin complexity values; the concrete model names are resolved inside the program. Other programs set their own dimension tiers internally and take no tier argument. Never write a concrete model name into a portable instruction.

## Vocabulary translation

Program output is not MCP vocabulary, and an off-list value is rejected rather than stored (Invariant 12).

| Source | Program spelling | MCP value |
|---|---|---|
| `review-diff` verdict | `APPROVED`, `APPROVED_WITH_CONCERNS`, `NEEDS_WORK`, `REJECTED` | `approved`, `approved_with_concerns`, `needs_work`, `rejected` |
| `implement-wave` `qualityGate` | `PASS`, `FAIL` | gate status `passed`, `failed` |
| `implement-wave` `status` | `Done`, `Blocked`, `Failed` | task verdict `pass`, `concern`, `fail`, decided with the validator report |
| Finding severity | `Critical`, `Major`, `Minor` | `critical`, `major`, `minor` |
