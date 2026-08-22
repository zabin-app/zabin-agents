# Conductor skill — deployment notes

Operational instructions live in [`SKILL.md`](SKILL.md) and its references. This file records how many conductors exist and where, so a host never has to choose between two of them.

## One conductor

`skills/conductor` is the single conductor contract. It is installed as a portable skill by `zabctl agents install`, and any host-specific translation belongs in an adapter note beside it ([Claude Code](references/claude.md)) rather than in a forked copy of the skill. A second conductor — user-level, project-level, or vendored — is a drift source, not a customization mechanism: two documents describing one pipeline diverge, and the divergence is discovered by an agent following the stale one.

The pre-MCP Claude Code conductor it replaces is preserved, uninstalled, in [`attic/claude-conductor-markdown-era`](../../attic/claude-conductor-markdown-era/README.md).

## Recommendation: retire the project-local `conductor-mcp`

The zabin repository carries its own project-level skill, `conductor-mcp`. There is no literal name collision — `conductor` and `conductor-mcp` are different skill names, so neither shadows the other — which makes this a redundancy question rather than a loading question, and the recommendation is **retire it in favor of the installed user-level conductor**.

Rationale:

- Its content now has three homes and no fourth: the pipeline discipline is this skill, the host-specific dispatch and vocabulary translation are the adapter note, and the project-specific facts (documentation policy, deployment ports, verification commands) belong in the zabin repository's own managed documents. Keeping a fourth copy means maintaining the same rules twice and trusting whichever an agent happened to load.
- The redundancy is the failure mode this pipeline already refuses elsewhere: a task card is deliberately the single copy of its contract because a second pasted copy drifts silently. A second conductor skill is the same defect at a larger scale.
- A project-level override earns its keep only by holding facts that are genuinely project-specific. `conductor-mcp` mostly holds general pipeline rules — the lease walk, the review cap, gate and vocabulary discipline — which this skill now states portably.

Retirement preconditions — relocate these before deleting anything, because they exist only in `conductor-mcp` today:

1. **Backlog triage.** The research-phase sweep of open and deferred action items, the aging rule for long-deferred minors, and the requirement that a batched minor finding cite the artifact itemizing it. This is pipeline discipline; it belongs in this skill or a reference beside it, not in a project skill.
2. **Deployment specifics.** The deployment's MCP ports, token files, and event-wait invocation are configuration, not pipeline state; the zabin repository's configuration document owns them, and [`config/zabin-mcp.json`](../../config/zabin-mcp.json) owns the canonical surface identities.
3. **Project routing.** The documentation policy, the doc set, and the verification commands stamped into task cards come from the project's own documents at run time; verify that nothing else in the project skill is load-bearing before removing it.

Execution is deliberately not part of this change: retiring a project-local skill alters a live checkout's behavior, so it happens under the user-triggered cutover, with the preconditions above satisfied first. Until then the project-local skill stays in place and governs work in that repository.
