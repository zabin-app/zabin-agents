# OpenCode MCP adapter compatibility

**Status: supported, with documented behavior and limitations.** Audited live
on 2026-08-28 against OpenCode `v1.18.25` (`github.com/anomalyco/opencode`).
Every claim below is labeled **VERIFIED-BY-RUN** (exercised against the real
binary in an isolated sandbox) or **DOC-CITED** (taken from the exact
built-in `customize-opencode` skill bundled in this pinned binary, or from
the published JSON Schema at `https://opencode.ai/config.json` fetched on the
audit date — not from memory or third-party docs). No claim in this file, or
in any file that cites it, may assert more than what is recorded here.

OpenCode is a strong structural match for Zabin: it reads project-root
`AGENTS.md` automatically, discovers Agent Skills from `.agents/skills`
(alongside `.claude/skills` and its own `.opencode/skill(s)`), speaks
Streamable-HTTP-shaped remote MCP with `{env:VAR}` / `{file:path}` header
interpolation, and qualifies MCP tools per-server so Zabin's two surfaces
(`zabin` conductor, `zabin-worker` worker) can coexist without name
collisions. Unlike the Goose and PI audits, this one did not surface a
blocking identity/credential-release-order defect in the paths exercised —
see "What was not tested" for the boundary of that claim.

## Audited artifact

| Field | Value |
| --- | --- |
| Repository | `github.com/anomalyco/opencode` |
| Release tag | `v1.18.25` (matches `opencode --version` exactly) |
| Install method | Official install script `https://opencode.ai/install`, run with an isolated install directory override and `--no-modify-path` (no shell rc files touched) |
| Release archive | `opencode-linux-x64.tar.gz`, SHA-256 `58a3729a6f3432dd6d2917fcc4a949788891a035818646ad480e12c947f56e78` |
| Installed binary | SHA-256 `d91e0d33676d0839f7cde87924cd4127ea88c9d6784eea9f009a7d08bdc60eeb` — byte-identical to the binary extracted directly from the GitHub release archive above (independently downloaded and hashed to cross-check the installer) |
| Binary shape | ELF 64-bit LSB x86-64, statically-linked Bun-compiled single executable, `BuildID[sha1]=c30f169b1bef81fa57467cd091ba53aab5235468`, not stripped |
| Runtime identity on the wire | `User-Agent: opencode/1.18.25 ai-sdk/provider-utils/4.0.23 runtime/bun/1.3.14` (observed on outbound model requests) |

No `client-lock.json`/`extension-lock.json` is produced by this audit —
OpenCode ships as one self-contained binary with no separate resolvable
dependency tree to lock (unlike PI's npm extension). The SHA-256 above is
the pin; a later release changes it and requires re-audit (see "Aging
notice").

## Methodology and containment

The install and every probe ran in an isolated sandbox, never in the real
project checkout, using the official install script (patched only to accept
an install-directory override — no `--binary`/network behavior was
changed) plus `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`,
`XDG_STATE_HOME`, `OPENCODE_TEST_HOME`, and `OPENCODE_CONFIG_DIR` all
pointed at a scratch directory, with `OPENCODE_DISABLE_AUTOUPDATE=1`,
`OPENCODE_DISABLE_MODELS_FETCH=1`, `OPENCODE_DISABLE_DEFAULT_PLUGINS=1`,
`OPENCODE_DISABLE_SHARE=1`.

Probes that needed a live model or a live MCP server were pointed at
loopback-only Python fixtures started for this audit (never a real
provider, never a real credential):

- a minimal Streamable-HTTP MCP stub answering `initialize` /
  `tools/list` / `tools/call`, logging every received header (including
  `Authorization`) verbatim to a local log file so header interpolation
  could be observed on the wire, not just in a resolved-config dump;
- a minimal OpenAI-compatible chat-completions stub (SSE streaming,
  matching what OpenCode's `@ai-sdk/openai-compatible` provider actually
  requests — `stream: true`), configured as a custom `provider` in
  `opencode.json`, which logs every request body (system prompt, messages,
  offered `tools`) and returns a small deterministic reply so the CLI's
  final text output is a direct, unambiguous witness of what reached the
  model-facing HTTP boundary.

**Containment incident (fully resolved, no repository or credential impact,
disclosed in full):** the very first invocation, before an explicit `HOME`
override was added to the sandbox wrapper (only `XDG_*` vars were set at
that point), triggered a bootstrap code path in OpenCode that resolves the
process's *global config lookup* independently of the `XDG_CONFIG_HOME`
override actually reported by `opencode debug paths` in the same run. That
one invocation read the real local user's pre-existing OpenCode
installation state (`~/.config/opencode`, `~/.local/share/opencode`,
`~/.cache/opencode`) and, because the CWD-independent project
resolver found the operator's real, already-configured OpenCode project
pointed at the real `zabin` checkout, produced: (a) a refreshed
`~/.cache/opencode/models.json` (public models.dev catalog data, no
secret), (b) SQLite WAL/SHM journal churn on the pre-existing
`~/.local/share/opencode/opencode.db` (main `.db` file's mtime is
unchanged — no content was altered, only journal files were touched), and
(c) one new 20-line diagnostic log file at
`~/.local/share/opencode/log/opencode.log`. The log confirms
`"project copy refresh done" ... updated=[] removed=[]` — **zero files in
the real project were read for content, written, or modified.** No
credential, no repository file, and no git state was touched. Deleting that
stray log file from outside this task's worktree was attempted and refused
by the sandbox's own guard, so it was left in place; it contains only
timestamps, skill-discovery diagnostics, and directory paths, no secrets.
Every subsequent invocation (after adding an explicit `HOME` override,
confirmed by `debug paths` reporting `home` inside the sandbox) was
independently verified, before and after, to leave the real `$HOME`
OpenCode state's mtimes completely unchanged.

**Practical lesson for the render/install tasks that depend on this
audit:** `XDG_CONFIG_HOME`/`XDG_DATA_HOME`/`XDG_CACHE_HOME` alone are
**not sufficient** to fully sandbox this binary — an explicit `HOME`
override (or `OPENCODE_TEST_HOME`, which the binary's `Global.home` getter
reads ahead of `os.homedir()`) is required for full isolation. Any future
live conformance harness for this adapter must set `HOME`, not just the
`XDG_*` family.

## Per-claim verdicts

| # | Claim | Verdict | Evidence |
| - | --- | --- | --- |
| 1 | Version + install provenance | **VERIFIED-BY-RUN** | `opencode --version` → `1.18.25`; installed binary SHA-256 matches the SHA-256 of the binary extracted directly from the official GitHub release tarball `opencode-linux-x64.tar.gz` for tag `v1.18.25`, downloaded independently (see table above). |
| 2 | Root `AGENTS.md` content reaches model context and is honored | **VERIFIED-BY-RUN** | `AGENTS.md` at the sandbox project root instructed "always answer with the exact token XYZZY-123". The stub model server's logged request body contains the literal `AGENTS.md` text inside the `system` message; `opencode run --agent build "hello"` (headless, `--format json`) produced final assistant text `XYZZY-123` — end to end, no manual step in between. |
| 3 | Skills at `.agents/skills/<name>/SKILL.md` are discovered | **VERIFIED-BY-RUN** | `.agents/skills/probe-skill/SKILL.md` (frontmatter `name: probe-skill`, matching `^[a-z0-9]+(-[a-z0-9]+)*$`) appeared in `opencode debug skill` output with its real `location` path and body, **and** in the live `system` prompt sent to the model inside an `<available_skills>` block (`<name>probe-skill</name>`, its description, and its filesystem location) captured by the model stub during the `AGENTS.md` run. The bundled `customize-opencode` built-in skill additionally documents `.agents/skills` is not a recognized default path by name — but external skill auto-loading from `~/.claude/skills` and `~/.agents/skills` is (see "External skills" row below); Zabin's project-local `.agents/skills` was discovered because it sits under the project root's own `.agents/skills`, which this version's skill loader scans as an external-skill root alongside `~/.claude` / `~/.agents` (confirmed live: the leaked containment-incident log from the real project showed the identical `.agents/skills` + `.claude/skills` discovery pattern against the operator's real `~/.agents` and `~/.claude` trees, with "duplicate skill name" warnings when the same skill exists in more than one root). |
| 3b | External skills auto-loaded from `~/.claude/skills` and `~/.agents/skills` | **DOC-CITED** (corroborated incidentally) | Documented verbatim in the bundled `customize-opencode` skill body: `"External skills (auto-loaded) | ~/.claude/skills/<name>/SKILL.md, ~/.agents/skills/<name>/SKILL.md"`. Not independently probed as a standalone fixture (out of scope: this audit's project-level skill probe already exercises the mechanism), but incidentally corroborated by the containment-incident log line `"duplicate skill name" name=doc_validate existing=~/.claude/skills/... duplicate=~/.agents/skills/...` produced by a real invocation against the operator's real trees. |
| 4a | `.opencode/agents/<name>.md` (plural) agent files are loaded | **VERIFIED-BY-RUN** | `probe-agent-plural.md` under `.opencode/agents/` appears in `opencode debug config`'s resolved `agent` map (name, description, mode, prompt all populated from the file) and in the `task` tool's `subagent_type` description as an available agent. |
| 4b | `.opencode/agent/<name>.md` (singular) agent files are ALSO loaded on this pinned version | **VERIFIED-BY-RUN — REFUTES the assumed upstream issue #14410 for this exact scenario** | A differently-named file `probe-agent-singular.md` placed under the **singular** `.opencode/agent/` directory (with **no colliding file** under the plural directory) also appears fully resolved in `opencode debug config`'s `agent` map and in the `task` tool description, on OpenCode `v1.18.25`. The binary's own bundled `customize-opencode` skill independently documents both forms as equally valid (`` `.opencode/agent/<name>.md` OR `.opencode/agents/<name>.md` ``). Do not carry forward wording that assumes singular `.opencode/agent/` is silently ignored on this version — it is not. Downstream doc/render tasks should still emit the plural form (matches the shipped skill's own preferred example and matches Claude Code's convention), but should not claim the singular form is broken here. |
| 5a | `opencode.json` `mcp.<name>` with `type: "remote"`, `url`, `headers.Authorization` parses | **VERIFIED-BY-RUN** | `opencode mcp list` reports both configured servers `connected`; `opencode debug config` shows the parsed `mcp` block unchanged in shape. |
| 5b | `{env:VAR}` header interpolation | **VERIFIED-BY-RUN, reaches the wire** | With `PROBE_MCP_TOKEN=env-bound-secret-token` in the process environment and `"Authorization": "Bearer {env:PROBE_MCP_TOKEN}"` in config, the loopback MCP stub's request log shows the literal received header `Authorization: Bearer env-bound-secret-token` on `initialize`, `tools/list`, and reconnect `GET` requests. `opencode debug config` also shows the value already substituted in its resolved-config dump — **note:** that dump prints the fully-interpolated secret value in plaintext, so `debug config` must never be run or captured with a real credential present; treat its output as sensitive. |
| 5c | `{file:path}` header interpolation (fallback binding) | **VERIFIED-BY-RUN, reaches the wire** | A second MCP server entry used `"Authorization": "Bearer {file:./probe-token.txt}"` pointing at a plaintext file containing `file-bound-secret-token`. The stub's request log shows the literal received header `Authorization: Bearer file-bound-secret-token`. Both forms resolved and reached the wire in the same run, from the same config file. |
| 5d | Shell-style `${VAR}` is *not* substituted | **DOC-CITED** | Stated explicitly in the bundled `customize-opencode` skill: `"the shell-style \${VAR} is not substituted"`. Not independently re-probed (probing a claimed non-substitution would only prove the literal string passes through unchanged, which the affirmative `{env:...}` proof above already covers structurally). |
| 6a | Wildcard MCP permission rule (`"<serverkey>_*": "deny"`) parses and takes effect | **VERIFIED-BY-RUN** | With `"permission": {"probemcp_*": "deny"}` and two configured MCP servers (`probemcp`, `probemcpfile`, both connected per `mcp list`, both had `tools/list` called against them per the stub's log), the **tools array actually offered to the model** contained `probemcpfile_get_task` and `probemcpfile_delete_attachment` but **zero** `probemcp_*` tools — the denied server's tools are hidden from the model entirely (pre-dispatch allowlist-style filtering), not merely blocked at call time. |
| 6b | `<serverkey>_<tool>` qualified-name shape for MCP tools | **VERIFIED-BY-RUN** | The offered tool names were literally `probemcpfile_get_task` and `probemcpfile_delete_attachment` — the MCP server's config key, an underscore, then the tool's own name, unmodified. (`get_task` and `delete_attachment` are the exact tool names Zabin's own worker/conductor MCP surfaces use, chosen deliberately for this probe.) |
| 7 | A custom `mode: subagent` agent can be invoked programmatically via the `task` tool | **VERIFIED-BY-RUN — REFUTES the task's assumed premise (upstream #29616/#20059) for this pinned version** | The stub model server was made to emit a `task` tool call with `subagent_type: "probe-agent-plural"` on the first turn. The audit observed, in strict sequence, on the SAME loopback stub: (1) the primary session's normal system prompt + the tool call; (2) a **second, distinct session ID**, with a system prompt that is **literally the probe agent's configured `prompt` body** (`"You are the plural-directory probe agent. Always answer with PLURAL-AGENT-OK."`); (3) the subagent's reply `PLURAL-AGENT-OK`; (4) a follow-up call on the **original** session, now carrying a `tool` role message whose content is `<task ... state="completed"><task_result>PLURAL-AGENT-OK</task_result></task>`; (5) final CLI text output `PRIMARY-GOT-RESULT:<task ...>PLURAL-AGENT-OK</task>`. The identical round trip was independently repeated for the **singular**-directory agent (`subagent_type: "probe-agent-singular"`), producing `SINGULAR-AGENT-OK` through the same sequence. Separately, `opencode run --agent probe-agent-singular "hello"` (direct CLI `--agent`, not the `task` tool) printed `"... is a subagent, not a primary agent. Falling back to default agent"` — confirming subagents are correctly barred from being launched as the *top-level* session agent, which is a different, narrower guard than the task tool's dispatch path and does not contradict the result above. **This means the "worker/interactive surface only, custom-subagent programmatic dispatch broken upstream (#29616)" framing some sibling tasks assume must not be copied verbatim** — on `v1.18.25`, programmatic dispatch of a project-defined subagent via the `task` tool works end-to-end. Any residual limitation from #29616/#20059 was not reproduced by this probe; if a narrower form of it still applies (e.g. a specific host, a specific triggering pattern), it was not found here and should not be asserted without a new, more targeted probe. |
| 8 | `.opencode/commands/<name>.md` with `description` frontmatter is discovered and invocable headlessly | **VERIFIED-BY-RUN** | `.opencode/commands/probe.md` appears in `opencode debug config`'s resolved `command` map (`description`, `template`). `opencode run --agent build --format json --command probe ""` (fully headless) actually injected the command's template body (`"probe command body. It does nothing real."`) into the user message sent to the model, confirmed in the stub's request log. Both singular `.opencode/command/` and plural `.opencode/commands/` are documented as equally valid by the bundled skill (parallel to the agent-directory finding); only the plural form was probed live for commands (time-boxed; the agent-directory probe already establishes singular-form loading works on this binary generally). |

## What was not tested

- No real upstream AI provider or real API key was used anywhere in this
  audit; all model traffic terminated at a loopback stub. Behavior that
  depends on a genuine LLM's judgement (e.g. whether a real model
  *chooses* to call a denied-looking tool, or free-form instruction
  following beyond the deterministic token-echo used here) was not and
  cannot be exercised this way — probe 2's claim is specifically "the
  content reaches the model and the CLI's output is a direct function of
  it", not "a production LLM will always obey it".
- TUI-only, interactively-driven behavior (mouse/keyboard flows, the `@`
  autocomplete menu, live approval prompts) was not exercised; every probe
  here used `opencode run` (headless) or `opencode debug`/`opencode mcp`
  subcommands. Where the task list anticipated a TUI-only claim (none of
  the eight ended up requiring it — all eight were reachable headlessly on
  this version) that headroom was unused, not exhausted.
- No OAuth-authenticated MCP server, no `type: "local"` (subprocess) MCP
  server, and no `oauth` config block were probed — only `type: "remote"`
  with static/interpolated headers, matching Zabin's two MCP surfaces
  exactly.
- Sandbox/process-isolation guarantees (or their absence) for OpenCode's
  own tool execution (`bash`, `edit`, arbitrary file writes) were not
  assessed; that is a materially different question from MCP credential
  handling and was out of this task's probe list.
- Update/removal lifecycle (`opencode upgrade`, `opencode uninstall`) was
  not exercised.

## Resulting adapter decisions

These are the decisions the dependent contract-assets task
(`tsk_000001a0474e36acSlKaBUJI`) should encode, each traceable to a row
above:

1. **Credential binding: `environment_interpolation`.** `{env:VAR}` header
   substitution is VERIFIED-BY-RUN (row 5b) and reaches the wire
   identically for both of Zabin's MCP surfaces' bearer tokens
   (`ZABIN_MCP_TOKEN`, `ZABIN_MCP_WORKER_TOKEN` per
   `.agents/config/zabin-mcp.json`'s existing `credential.source:
   "environment"` convention — this is a clean match, not a new pattern).
   `{file:path}` also works (row 5c) and is available as a documented
   fallback if a future policy prefers a token file, but is not the
   primary choice: Zabin's other adapters already standardize on
   environment-variable credentials, and OpenCode's environment-variable
   form matches that with no adapter-specific translation needed.
2. **Agent directory: plural `.opencode/agents/`.** Both forms load on
   this pinned version (row 4a/4b), but the plural form is what the
   binary's own bundled documentation uses as its canonical example and
   what matches Claude Code's convention already used elsewhere in this
   bundle; use it for anything the renderer emits. The singular form
   should not be described as broken in any doc this bundle ships,
   because it is not, on this pinned version.
3. **No workflow port.** OpenCode's `command` files are single-shot
   templated prompts (`$ARGUMENTS`/`$1`/`$2` substitution into one prompt
   string, per the bundled skill's own documented shape) and its `plugin`
   hook surface (`tool.execute.before/after`, `chat.message`, etc.) is a
   general extension mechanism, not an orchestration DSL comparable to
   Zabin's workflow programs. This finding is **DOC-CITED** (read from the
   config schema and the bundled skill's documented `command`/`plugin`
   shapes, not independently probed — there is nothing resembling a
   multi-step Workflow primitive to exercise). No workflow-equivalent
   asset should be rendered for this target.
4. **Subagent-dispatch limitation: do not assert one.** Row 7 refutes the
   premise this bundle's other in-flight tasks assume
   (`tsk_000001a0474e36acTofbeNcS`'s planned "custom-subagent programmatic
   dispatch broken upstream (#29616)" wording). On the audited version,
   dispatch works end-to-end for both agent-directory forms. The narrower,
   independently-verified limitation that *does* hold is: a `mode:
   subagent` agent cannot be launched as the top-level session agent via
   `--agent` (falls back to the default agent) or presumably via
   `opencode <project>`/TUI agent switch (not probed) — only via the
   `task` tool or `@mention` (mention not probed headlessly). Any doc task
   downstream of this one must update its planned wording to match this
   evidence rather than the pre-audit assumption, or explicitly call out
   why it is choosing not to (e.g. deliberately keeping worker dispatch
   off this path for a Zabin-specific reason, which would be a product
   decision this audit does not make).
5. **`tool_reference_mode: client_qualified`** (already assumed by the
   dependent task) is confirmed by row 6b: OpenCode itself performs the
   `<serverkey>_<tool>` qualification; Zabin's adapter must not
   pre-qualify names itself.
6. **`required_fields` for the opencode.json template:** `type` (must be
   `"remote"`), `url`, and `headers.Authorization` (or, if the file-binding
   fallback is ever chosen instead, `headers.Authorization` pointed at
   `{file:...}` with the file path resolved relative to the config that
   declares it) — all three are enforced by the schema (`required: ["type",
   "url"]`, `headers` an open string-map) and all three were exercised
   live.

## Aging notice

OpenCode ships multiple releases per week. The install script's own
`check_version` step confirms this concretely: it checks `command -v
opencode` on the ambient `PATH` (not the isolated sandbox target) and
printed `"Installed version: 1.18.4."` before installing `1.18.25` into the
isolated directory — meaning the machine this audit ran on already has an
entirely separate, real, PATH-visible system install of OpenCode
(`/usr/bin/opencode`, confirmed `1.18.4`) that this audit did not use,
modify, or depend on. 21 patch versions (`1.18.4` → `1.18.25`) separate that
system package from this audit's pin, with no way to tell from version
numbers alone how much calendar time that spans. Treat every
VERIFIED-BY-RUN row above as pinned to
`v1.18.25` and re-run this audit's probes (all reproducible headlessly, all
listed with their exact repro shape above) before relying on this file
against any newer release — especially rows 4b and 7, which explicitly
contradict a plausible reading of open upstream issues and could easily
regress or be version-gated in either direction.

## Acceptance probe (2026-08-28, tsk_000001a0474e36acAuKUNxjG)

Everything above audited the OpenCode binary against hand-built fixtures.
This probe instead built `zabctl` from `develop` (`67f4617a8a56ecc0d3cbaeb336f0a187809457ec`) and ran the real
`agents install` command to produce an actual rendered install tree, then
pointed the pinned OpenCode `v1.18.25` sandbox from the Methodology section
above at that real tree — no hand-authored `opencode.json` or `.opencode/`
content. The live daemon (`zabin-server`, standalone) was reachable from
the sandbox through pre-existing loopback `socat` bridges forwarding
`127.0.0.1:50052`/`127.0.0.1:50053` (the ports baked into
`.agents/config/zabin-mcp.json` and therefore into the rendered
`opencode.json` — the canonical defaults at probe time; an endpoint override
at install time, `--mcp-endpoint` / `--mcp-worker-endpoint` or the marker and
environment layers described in `docs/INSTALL.md#endpoints`, changes the URLs
rendered into `opencode.json` accordingly) to the daemon's actual binds; real `ZABIN_MCP_TOKEN` /
`ZABIN_MCP_WORKER_TOKEN` credentials from the ambient environment were used
— the stub-server fallback was not needed. **Correction to this task's own
dispatch context:** loopback is *not* auth-exempt for either MCP mount —
`zabin-server`'s MCP bearer-token layer runs unconditionally regardless of
peer address (only the separate gRPC `--api-key` middleware has a
loopback carve-out); a bare `curl` `initialize` with no `Authorization`
header against `127.0.0.1:50063/mcp-worker` returned `401 Missing bearer
token` before any token was supplied, confirming this directly.

Repro (all commands run from a throwaway location outside the repository;
`SC` is that scratch root):

```bash
CARGO_TARGET_DIR="$SC/probe-target" cargo build --bin zabctl -p zabin-cli
"$SC/probe-target/debug/zabctl" agents install \
  --contracts-root <worktree>/.agents \
  --destination "$SC/probe-install" \
  --mode copy --target claude_code,codex,opencode
# isolated sandbox env (HOME + XDG_* + OPENCODE_TEST_HOME, per Methodology)
# then, cd "$SC/probe-install" as the OpenCode project root:
opencode mcp list
opencode debug config      # resolved `agent` map; NEVER capture with a real token present (see row 5b)
opencode debug skill
opencode run --format json "TRIGGER_TOOL:<tool> ..."   # against a loopback ai-sdk-compatible stub model
```

| # | Check | Outcome | Evidence |
| - | --- | --- | --- |
| a | `opencode.json` parses, no MCP config errors | **PASS** | `opencode mcp list` on the freshly rendered, unmodified `opencode.json` (73-artifact install, `zabin`+`zabin-worker` MCP blocks + permission map exactly as rendered) reported both `zabin` and `zabin-worker` as `connected` against the **live** daemon (not a stub) on the first try — no parse or config-validation error. |
| b | Rendered `.opencode/agents/` roles appear in the agent list | **PASS** | The install wrote 13 files under `.opencode/agents/` (`architecture-enforcer`, `bug-fix-reviewer`, `codebase-researcher`, `code-quality-inspector`, `doc-maintainer`, `external-researcher`, `git-historian`, `implementor`, `integration-verifier`, `logic-reasoning-checker`, `risks-tradeoffs-analyzer`, `security-reviewer`, `task-validator`); `opencode debug config`'s resolved `agent` map contained exactly those 13 keys, no more, no fewer. |
| c | The `.agents/skills` conductor skill is discoverable | **PASS** | `opencode debug skill` listed `conductor` (plus `docs-sync`, `doc-validate`) with a real `location` and full body. The installer also symlinks `.claude/skills/conductor -> ../../.agents/skills/conductor` (confirmed with `readlink -f`), so regardless of which scanned root OpenCode's loader reports in `location`, it is reading the one file under `.agents/skills/conductor/SKILL.md`. |
| d | MCP connect + tools list under `<serverkey>_<tool>` | **PASS, live** | With the sandbox pointed at a loopback ai-sdk-compatible stub *model* (never a stub MCP — the two MCP servers were the real daemon throughout), the stub's captured request body shows **83 real Zabin tool names** offered to the model: 62 `zabin_*` + 21 `zabin-worker_*`, alongside 10 OpenCode built-ins (`bash`, `edit`, `glob`, `grep`, `read`, `skill`, `task`, `todowrite`, `webfetch`, `write`) — 93 total, qualified-name shape confirmed. A follow-up run drove the model to call the **allowed** `zabin-worker_list_tasks` with a synthetic `project_id`; the tool actually executed against the live daemon and returned a genuine structured domain error (`[not_found] no project is registered with id 'prj_probe_permission_test' ... call \`resolve_project\` ...`) which flowed back into the next model turn — proof the call reached the real server, not a local emulation. |
| e | Permission rules apply (a denied tool is refused) | **PASS, live** | The rendered top-level `opencode.json` permission map sets `zabin_create_board` to `"ask"` (translated from the policy's `human_gate` risk class). Driving the model to call it headlessly (no TTY to answer a prompt) produced `stderr: "permission requested: zabin_create_board (*); auto-rejecting"` and a tool-result `"error":"The user rejected permission to use this specific tool call."` — the call was refused client-side and never reached the daemon, in direct contrast to check (d)'s allowed call above which did. Separately, the renderer also emits a **stricter, per-role** override: read-only reviewer roles (`architecture-enforcer`, `bug-fix-reviewer`, `code-quality-inspector`, `integration-verifier`, and others) carry `permission: {"zabin-worker_*": "deny", "zabin_*": "deny"}` in their own `.opencode/agents/*.md` frontmatter (confirmed present in this same install output), while `implementor` carries `{"zabin-worker_*": "allow", "zabin_*": "deny"}`. That per-role `deny` frontmatter is present-and-correct in the render but was not independently re-invoked live in this probe (doing so needs the two-hop `task`-tool subagent dispatch this file's row 7 already established works on this pinned version); treat it as **DOC-CITED-from-this-render**, not a fresh VERIFIED-BY-RUN claim, until a probe specifically drives a denied subagent through the `task` tool. |

No check failed; nothing here required stopping short or falling back to
the stub-server method. One operational note for anyone repeating this:
`opencode debug config` prints the fully-interpolated bearer token in
plaintext (same caveat as row 5b above) — a scratch copy of that output
containing a real, live daemon credential was captured once during this
probe and deleted immediately after the agent-map keys were extracted from
it; no token value is repeated in this file or was committed anywhere.

## Primary sources

- [OpenCode releases](https://github.com/anomalyco/opencode/releases) —
  pinned: [`v1.18.25`](https://github.com/anomalyco/opencode/releases/tag/v1.18.25)
- [OpenCode install script](https://opencode.ai/install) (fetched and run
  verbatim except for the isolated install-directory override)
- [OpenCode config JSON Schema](https://opencode.ai/config.json) (fetched
  on the audit date; `$defs` keys `McpRemoteConfig`, `PermissionConfig`,
  `ProviderConfig`, `AgentConfig`, `Config` were read directly)
- The `customize-opencode` built-in skill, extracted live from the pinned
  binary via `opencode debug skill` — this is bundled documentation shipped
  inside the exact audited artifact, not a fetched external page, so it is
  cited as DOC-CITED-but-artifact-pinned evidence throughout this file
- [Upstream issue #14410](https://github.com/anomalyco/opencode/issues/14410) —
  the singular `.opencode/agent/` non-loading report this audit's row 4b
  refutes for the pinned version
- [Upstream issue #29616](https://github.com/anomalyco/opencode/issues/29616),
  [#20059](https://github.com/anomalyco/opencode/issues/20059) — the
  subagent programmatic-dispatch reports this audit's row 7 refutes for the
  pinned version
- [Upstream issues #5299](https://github.com/anomalyco/opencode/issues/5299),
  [#13219](https://github.com/anomalyco/opencode/issues/13219) — cited by
  the dispatching task as prior context for MCP header `{env:...}`
  substitution; this audit's row 5b/5c is the live re-verification that
  supersedes citing those issues directly
