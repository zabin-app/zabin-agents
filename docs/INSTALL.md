# Installation Guide

End-to-end setup for a fresh machine, per client. Every command below was run
against this repository's `zabctl` release binary; output is condensed to the
shape that matters. A claim marked **version-dependent** could not be
executed here — see [R10](#r10-version-dependent-claims) — and must not be
read as a supported-client guarantee.

## Prerequisites

- A built `zabctl` binary (the `zabin-agent-tooling` crate, shipped in the
  `zabctl` binary from the zabin workspace: `cargo build --release -p
  zabin-cli`, or use an installed copy). Confirm it implements the `agents`
  command family:

  ```sh
  zabctl agents capabilities
  ```

  ```text
  zabin-agent-tooling 0.1.0 (capability schema 1)
  ready: yes (8 of 8 commands implemented)
  ```

  `agents` never contacts `zabin-server`; it works with no server, no
  credentials, and no config file.
- Git — only for the fresh-machine `bootstrap` clone path below. Working
  inside a zabin checkout needs the `.agents` submodule initialized: run
  `git submodule update --init` if it is not yet initialized.
- Native clients (Claude Code, Codex, …) are needed only to *use* what gets
  installed, not to run `zabctl agents` itself.

## Source of truth: the zabin-agents repository

The contracts bundle is the **zabin-agents** repository, publicly available at
https://github.com/zabin-app/zabin-agents and is the authoritative source. The
zabin project consumes it as a git submodule at `.agents`, pinned to a specific
commit. `ContractsRoot::discover` walks ancestors from the current directory,
testing each directory and its `.agents` child, and stops at the first bundle it
finds; the walk also stops at the enclosing repository root (so a bundle above
your project is never adopted) and never reaches or adopts `$HOME`. Practically:
run any `zabctl agents <command>` from anywhere inside a zabin checkout and it
finds `.agents` on its own — an uninitialized submodule appears as an empty
directory, and `zabctl agents` discovery fails with a marker-file error (markers
are `config/zabin-mcp.json`, `schemas/mcp-policy.schema.json`, `adapters/`).

### Editing the bundle

Change the bundle in the **zabin-agents** submodule itself, or in a separate
clone of https://github.com/zabin-app/zabin-agents — never by editing the
copy checked out under `<zabin>/.agents` and committing to zabin directly.
Commit and push the change there first, then bump the pinned commit in zabin
by running `git add .agents` from the zabin repository root and committing
the resulting submodule pointer update.

**Cloning zabin with the submodule initialized:**

```sh
git clone --recurse-submodules <zabin-repo-url>
```

If you already have a zabin checkout, initialize the `.agents` submodule:

```sh
git submodule update --init
```

Verified from the repository root and from a nested subdirectory alike:

```sh
zabctl agents doctor
```

```text
Resolved contracts root to /path/to/zabin/.agents (discovered from /path/to/zabin/some/subdir)
Zabin doctor: DEGRADED (static mode)
...
```

The discovery notice above is printed to stderr only when the root was discovered,
never when `--contracts-root` was given explicitly.

**Using the bundle standalone:**

For a machine without a zabin checkout — installing into another project, or
working independently — clone zabin-agents directly or use `zabctl agents
bootstrap`, which defaults to the public zabin-app/zabin-agents repository on
a first run:

```sh
zabctl agents bootstrap
```

Pass `--repo <git-url>` to bootstrap from a fork or mirror instead.

Outside a zabin checkout, name the bundle explicitly:

```sh
zabctl agents install --contracts-root /path/to/zabin-agents \
  --mode copy --destination /absolute/destination
```

`doctor`, `render`, `install`, `validate`, and `conformance` all accept
`--contracts-root`; an explicit path is validated as given and is never
silently substituted with a discovered one.

### Selecting client targets

`install` lays every *default* client adapter unless told otherwise. `--target`
replaces the default selection with a comma-separated list from
`claude_code`, `codex`, `goose`, `opencode` (default `claude_code,codex`);
`opencode` is opt-in — it is never installed unless named explicitly:

```sh
zabctl agents install --contracts-root /path/to/zabin/.agents \
  --mode copy --destination /absolute/destination --target claude_code
```

An unknown target — and `codex_admin_requirements`, which is never installable —
is refused (exit 2) naming the allowed set. Verified:

```text
error: usage: ordinary installation target is forbidden: bogus_target (allowed targets: claude_code, codex, goose, opencode)
```

A subset install never touches an
unselected target's files or manifest entries (a later full-set `--mode check`
still reports them clean), and the shared families — role instructions under
`<destination>/agents`, portable skills under `<destination>/.agents/skills`,
and the ownership manifest — install regardless of the selection.

### Isolated, relocatable destinations

Everything an install writes — adapters, shared families, and the ownership
manifest at `<destination>/.zabin/installer-manifest.json` — lives under
`--destination`, so an isolated tree such as
`--destination ~/.claude-zabin --target claude_code` touches nothing in the
operator's real `~/.claude`, `~/.codex`, `~/.agents`, or `~/.mcp.json`. Skill
bridges (`.claude/skills/<name>`) are written as **relative** symlinks whenever
the skills root sits under the destination (the default layout), so the
installed tree keeps working if it is moved; a re-install over a pre-change
absolute link migrates it to the relative form, and an explicitly-outside
skills root keeps an absolute target.

## Quick start: one-command bootstrap

`zabctl agents bootstrap` is for a machine that does **not** already have a
zabin checkout and wants its own portable copy of the bundle. It acquires
(clones or fast-forwards) a contracts-bundle-shaped repository, runs static
diagnostics, and — only when told where — installs and renders adapters, in
one flow. If you already have a zabin checkout with the submodule initialized, skip this section and use
`--contracts-root <zabin>/.agents` directly, or run `zabctl agents <command>` from anywhere in the checkout for auto-discovery.

A bare invocation clones the public zabin-app/zabin-agents repository (or, on
a later run, whichever repository an earlier run recorded in
`~/.zabin/agents.toml`):

```sh
zabctl agents bootstrap
```

Pass `--repo <git-url>` to bootstrap from a fork or mirror instead:

```sh
zabctl agents bootstrap --repo <git-url>
```

**Verified, exact current behavior:** a bare bootstrap (no `--install-into`)
only clones/updates and diagnoses; it does **not** install anything. Run
against a scratch `file://` remote:

```text
Contracts bundle: <dest> (cloned from file://<remote>.git)
  commit 604e4f3234d97c99d04746387cb4093cdb6eded5
Diagnostics: degraded (goose_compatibility)
Installation: skipped — no --install-into was given, so only the bundle at <dest> was
  acquired and diagnosed; name a project root to install the adapters, skills and role
  instructions into
Recorded in ~/.zabin/agents.toml
```

This is intentional, not a bug: there is deliberately no default
`--install-into`, because the home layout that would pair naturally with the
default `--destination ~/.agents` **overlaps the bundle itself** — the
installer would try to write the bundle's own `agents/` and `.agents/skills/`
sources back on top of themselves. Verified directly:

```sh
zabctl agents bootstrap --repo <git-url> --destination ~/.agents --install-into ~/.agents
```

```text
error: usage: the install root ~/.agents would place the role instructions at
  ~/.agents/agents, which is the bundle's own ~/.agents/agents — the bundle cannot be
  installed into a tree that contains it; name an install root outside ~/.agents
```

The same refusal fires for `--install-into "$HOME"` while `--destination`
stays at its default `~/.agents`, because `$HOME` *contains* `~/.agents`:

```text
error: usage: the install root $HOME would place the skills at $HOME/.agents/skills,
  which is the bundle's own $HOME/.agents/skills — the bundle cannot be installed into a
  tree that contains it; name an install root outside $HOME/.agents
```

### Recommended follow-up: project-level install (the common case)

Most setups install into the project you are actually working in, which
never overlaps the bundle clone:

```sh
zabctl agents bootstrap --repo <git-url> --install-into /absolute/path/to/your/project
```

Verified: this produces a full Claude Code + Codex adapter set inside the
project (artifact list in [Coverage matrix](#coverage-matrix) below) and
records the repo/destination/install-into triple in `~/.zabin/agents.toml`.

A later **bare** `zabctl agents bootstrap` re-run fast-forwards the bundle
and then runs the installer in **check mode only** — it reports drift and
writes nothing. Naming `--install-into` on an invocation is consent to
write for that run; on a record-driven re-run, consent is the new
`--apply` flag:

```text
$ zabctl agents bootstrap
Contracts bundle: <dest> (already_current from file://<remote>.git)
  commit b119e693... (was b119e693...)
Diagnostics: degraded (goose_compatibility)
Installation: checked (nothing written) — verified in <project> for claude_code, codex
Recorded in ~/.zabin/agents.toml
```

When upstream moved, the check reports what an `--apply` would change;
`zabctl agents bootstrap --apply` then performs the recorded install
(`Installation: unchanged into <project> …` when nothing drifted). Both
transcripts above are verified output of the current binary against a
scratch `file://` remote.

### Recommended follow-up: a Claude Code *home* (user-level) setup

To make the rendered `.claude/agents`, `.mcp.json`, and `.codex/config.toml`
available to every project (not just one), install into `$HOME` — but the
bundle clone must live **outside** `$HOME`'s default `~/.agents` first, or
you hit the exact overlap refusal shown above. Verified working pattern:

```sh
zabctl agents bootstrap --repo <git-url> \
  --destination ~/.local/share/zabin-agents \
  --install-into "$HOME"
```

With the bundle clone relocated, `$HOME/.agents/skills` and `$HOME/agents`
are freshly-created installed output, not the bundle's own source tree, so
the install proceeds normally (verified against scratch stand-ins for both
paths). If you don't need a global install, prefer the project-level form
above — it needs no relocation and is the pattern most users want.

`--target` (default `claude_code,codex`) selects which client adapters
`bootstrap` installs; `--apply` is the consent flag that lets a
record-driven re-run write (a bare re-run always runs the installer in
check mode and reports instead); `--backup-and-replace` is the only way to reuse an
existing, non-matching destination — it moves the old directory to a
timestamped backup (verified: `<dest>.backup-<UTC-timestamp>`, never
deleted) and clones fresh. A destination that exists, isn't a git repository,
or tracks a different remote is refused otherwise (verified: exit 2, "exists
but is not a git repository; nothing was changed").

## Manual flow: doctor / install / render

For finer control than `bootstrap` gives you, run the commands directly
against the `.agents` submodule inside the zabin checkout — no clone or `cd`
required beyond having the zabin checkout:

```sh
# From anywhere inside the checkout; offline, no network/credential reads:
zabctl agents doctor
```

Verified against this repository's own bundle — the two dummy `mcp.token` /
`mcp-worker.token` files under `~/.zabin` are what `env=false` falls back to:

```text
Resolved contracts root to /path/to/zabin/.agents (discovered from /path/to/zabin)
Zabin doctor: DEGRADED (static mode)
Credentials (availability only):
  - conductor: ZABIN_MCP_TOKEN env=false; mcp.token file=true
  - worker: ZABIN_MCP_WORKER_TOKEN env=false; mcp-worker.token file=true
Checks:
  - [PASS] contracts_bundle: policy, schemas, roles, tiers, templates, and client locks validate
  - [PASS] credential_boundary: ...
  - [PASS] agent_and_model_contracts: ...
  - [PASS] recovery_compatibility: ...
  - [PASS] adapter_readiness: ...
  - [DEGRADED] goose_compatibility: Goose 1.45.0 is unsupported; active artifacts are disabled
  - [PASS] pi_extension_lock: ...
  - [PASS] canonical_surface_fingerprints: ...
```

`DEGRADED` here exits **0** — it is the expected, honest steady state (Goose
stays unsupported by design), not a failure to fix.

Then install the shared roles, skills, and every default client adapter in
one step. Add `--contracts-root <zabin>/.agents` when the working directory
isn't inside the checkout — for example installing into `~` for a global
Claude Code setup:

```sh
zabctl agents install --contracts-root <zabin>/.agents --mode dry-run --destination /absolute/destination
zabctl agents install --contracts-root <zabin>/.agents --mode copy --destination /absolute/destination
zabctl agents install --contracts-root <zabin>/.agents --mode check --destination /absolute/destination
```

**Verified, and a correction to older assumptions:** `install` has no
`--target` flag and needs no credential environment variables to run — it
always lays out **both** `claude_code` and `codex` adapters, plus the
portable `agents/` sources and `.agents/skills/`, and it succeeds even with
`ZABIN_MCP_TOKEN`/`ZABIN_MCP_WORKER_TOKEN` unset (the credential headers it
writes are the literal `${ZABIN_MCP_TOKEN}` / `${ZABIN_MCP_WORKER_TOKEN}`
reference strings a client resolves at its own runtime, never a value). One
`install --mode copy` run against a scratch destination produced:

```text
<dest>/agents/<13 role>.md
<dest>/.agents/skills/{conductor,docs-sync,doc-validate}/...
<dest>/.claude/agents/<13 role, kebab-case>.md
<dest>/.claude/settings.json
<dest>/.claude/skills/{conductor,docs-sync,doc-validate} (symlinks -> <dest>/.agents/skills/...)
<dest>/.claude/workflows/<6 program>.js
<dest>/.codex/config.toml
<dest>/.mcp.json
<dest>/.zabin/installer-manifest.json
```

The `.claude/skills/<name>` entries are manifest-tracked symlinks — one per
bundle skill, bridging the portable `.agents/skills/<name>` sources into the
tree Claude Code discovers skills from — recorded in the manifest as
`skill_link` entries alongside the `instruction`, `skill`, and `adapter`
kinds already tracked there.

**Collision rule:** any pre-existing, unmanaged file or directory at a path
the installer would write is refused outright, for both adapter files and
skill-bridge symlinks — verified:

```text
error: contract: adapter collision at <dest>/.claude/agents/doc-maintainer.md: [{"current":"<unmanaged>","expected":"sha256:...", ...}]
error: contract: skill_link collision at <dest>/.claude/skills/conductor: [{"current":"<unmanaged>","expected":"sha256:...", ...}]
```

Move hand-maintained content at any adapter or skill destination aside before
installing; the installer never overwrites something it does not already own
in the manifest.

`check` compares against the manifest and reports drift (`changes: []` and
`"installation": "verified"` on a clean tree; exit 1 on drift, exit 2 on an
unsafe/invalid installation).

`render` is for regenerating or auditing **one** target's artifacts in
isolation — for example the inert Goose evidence — and, unlike `install`,
*does* require both credential environment variables to be set (non-empty,
non-placeholder) before it will write anything, even though it embeds only
the `${VAR}` reference string, never a value:

```sh
export ZABIN_MCP_TOKEN=... ZABIN_MCP_WORKER_TOKEN=...
zabctl agents render --target claude_code --output-dir /absolute/staging/claude --mode write
zabctl agents render --target claude_code --output-dir /absolute/staging/claude --mode check
zabctl agents render --target codex --output-dir /absolute/staging/codex --mode write
zabctl agents render --target goose --output-dir /absolute/staging/goose --mode write
```

Verified: `render --target claude_code` alone reproduces the same 20 files
`install` lays into `.claude/` + `.mcp.json`; `render --target goose`
produces exactly `goose/recipe.json` and `goose/settings.json`, both
`{"active": false, "artifacts": [], "support_status": "unsupported"}` — inert
evidence, never an activatable recipe. Full command reference, `--mode live`
diagnostics, and the conformance runner live in
[docs/DEVELOPMENT.md](DEVELOPMENT.md).

## OpenCode

OpenCode is a rendered, **opt-in** installer/render target, pinned to and
audited against OpenCode `v1.18.25` — see
[`adapters/opencode/COMPATIBILITY.md`](../adapters/opencode/COMPATIBILITY.md)
for the full per-claim audit, including a shipped acceptance probe that ran
the real installer's output against a live daemon. It is not part of
`DEFAULT_TARGETS` (`claude_code,codex`), so name it explicitly:

```sh
zabctl agents install --contracts-root /path/to/zabin/.agents \
  --mode copy --destination /absolute/destination --target opencode
```

Verified — one `install --mode copy --target opencode` run against a scratch
destination produced:

```text
<dest>/agents/<13 role>.md
<dest>/.agents/skills/{conductor,docs-sync,doc-validate}/...
<dest>/.opencode/agents/<13 role, kebab-case>.md
<dest>/opencode.json
<dest>/.zabin/installer-manifest.json
```

Unlike the Claude Code target, there is no bridge or symlink step: OpenCode
reads the portable `.agents/skills` directory and project-root `AGENTS.md`
natively (`adapters/opencode/COMPATIBILITY.md` rows 2 and 3), so no
`.opencode/skills` copy is written. Combine `opencode` with the default
targets in one run — `--target claude_code,codex,opencode` — to install all
three adapters together; `zabctl agents install` with no `--target` still
only lays out `DEFAULT_TARGETS`, unchanged by OpenCode's addition to the
allowed target set.

**Home-destination blast radius:** unlike the project-scoped skills bridge
Claude Code uses, OpenCode auto-loads `$HOME/.agents/skills` as an external
skill root for *every* project it opens, not just the one being installed
into (`adapters/opencode/COMPATIBILITY.md` row 3b). Installing the
`opencode` target with `--destination "$HOME"` therefore makes this
bundle's skills globally visible to every OpenCode session on the machine;
use a project-scoped destination unless a machine-wide install is actually
intended.

**Credentials:** the same two environment variables as every other target —
`ZABIN_MCP_TOKEN` (conductor) and `ZABIN_MCP_WORKER_TOKEN` (worker) — bound
into `opencode.json` as `{env:VAR}` header references, never a literal
value:

```text
"headers": {"Authorization": "Bearer {env:ZABIN_MCP_TOKEN}"}
```

`{env:...}` header interpolation reaching the wire is VERIFIED-BY-RUN in the
compatibility audit (row 5b). **Loopback is not auth-exempt for either MCP
mount** — both mounts' bearer-token check runs unconditionally regardless of
peer address; confirmed directly by the audit's acceptance probe (a bare,
unauthenticated `initialize` against the worker mount returned `401 Missing
bearer token`). **`opencode debug config` prints the fully-interpolated
bearer token in plaintext** (`adapters/opencode/COMPATIBILITY.md` row 5b) —
never run or capture that command's output with a real `ZABIN_MCP_TOKEN` or
`ZABIN_MCP_WORKER_TOKEN` value in the environment; unset both first or use a
scratch value.

**Collision rule:** `opencode.json` is a whole-file owned artifact — unlike
`.mcp.json`, `.claude/settings.json`, and `.codex/config.toml`, which the
installer structurally merges into existing content — so a pre-existing,
unmanaged `opencode.json` at the destination is refused outright rather than
merged; verified:

```text
error: contract: adapter collision at <dest>/opencode.json: [{"current":"<unmanaged>","expected":"sha256:...", ...}]
```

Move a hand-authored `opencode.json` aside before installing; the installer
never overwrites something it does not already own in the manifest.

## Coverage matrix

| Client | Status | Rendered/installed artifacts | Verified against |
| --- | --- | --- | --- |
| Claude Code | Supported, fully rendered | `.mcp.json`; `.claude/settings.json`; `.claude/agents/<role>.md` × 13 (kebab-case names, pinned `model:` per capability tier, semantic tool allowlists); `.claude/workflows/*.js` × 6 | Rendered and diffed directly (below) |
| Codex | Supported, fully rendered | `.codex/config.toml` (`mcp_servers."zabin"` / `"zabin-worker"`, per-tool `approval_mode`, bearer-env-var binding) | Rendered directly |
| Goose 1.45.0 | Unsupported; fail-closed | `goose/recipe.json`, `goose/settings.json` — both inert (`active: false`, empty `artifacts`); no active artifact ever produced | Repo's own [`adapters/goose/COMPATIBILITY.md`](../adapters/goose/COMPATIBILITY.md) + [`client-lock.json`](../adapters/goose/client-lock.json), pinned to 1.45.0 |
| Pi | Unsupported; fail-closed | None — there is no `pi` render target; only a conformance lock | [`adapters/pi/COMPATIBILITY.md`](../adapters/pi/COMPATIBILITY.md) + [`extension-lock.json`](../adapters/pi/extension-lock.json), pinned to PI 0.84.1 / `pi-mcp-adapter` 2.22.0 |
| OpenCode | Supported, with documented limitations (opt-in target) | `opencode.json`; `.opencode/agents/<role>.md` × 13 (kebab-case names, `mode: subagent`, per-role per-server permission wildcard pair — e.g. `zabin-worker_*`/`zabin_*`: allow/deny — not a per-tool map); native `.agents/skills` consumption, no bridge or copy written; consumes project-root `AGENTS.md` if present (not itself an installed artifact) | [`adapters/opencode/COMPATIBILITY.md`](../adapters/opencode/COMPATIBILITY.md), pinned to `v1.18.25`, incl. a shipped acceptance probe against the real installer and a live daemon |

### The 13 rendered `.claude/agents` files

```text
architecture-enforcer   code-quality-inspector   external-researcher   logic-reasoning-checker   security-reviewer
bug-fix-reviewer        codebase-researcher      git-historian         risks-tradeoffs-analyzer  task-validator
doc-maintainer          implementor              integration-verifier
```

### The 6 rendered `.claude/workflows/*.js` programs

```text
docs-explore.js  followup-investigate.js  implement-wave.js  plan-verify.js  research-sweep.js  review-diff.js
```

Verified by running `zabctl agents render --target claude_code` against this
repository's bundle to a scratch output directory and listing the result;
the same 19 files (13 agents + 6 workflows) plus `.claude/settings.json` and
`.mcp.json` appear whether they come from `render` alone or from `install`.

### Goose: native consumption, still fail-closed

Goose speaks Streamable HTTP MCP, reads canonical `AGENTS.md`, and discovers
Agent Skills from `.agents/skills` without any Goose-specific fork — but
native consumption of those shared contracts does **not** clear its audited
blockers, restated from
[`adapters/goose/COMPATIBILITY.md`](../adapters/goose/COMPATIBILITY.md):

- **Credential release precedes identity** — Goose sends the bearer header
  on `initialize` before checking the returned `serverInfo` against the
  expected service/surface/protocol/inventory.
- **Header indirection fails open** — a missing `${ENV}` variable makes
  Goose continue *without* the MCP extension rather than refusing to start.
- **Approval state is mutable and defaults to `auto`** — a conflicting
  permission-file entry resolves to *allow*, not deny.
- **Hooks are not a fail-closed enforcement boundary** — hook failures and
  timeouts are logged, and execution continues.
- **Trust, containment, and cleanup evidence are incomplete** — no locked
  workspace/recipe trust gate, no filesystem sandbox for native
  Developer/stdio extensions, and no MCP-visible uninstall contract.

`zabctl agents doctor` reports this as `[DEGRADED] goose_compatibility`
(exit 0, a diagnosis, not a failure); `zabctl agents conformance` keeps the
aggregate result non-pass with the committed 1.45.0 lock even when every
observational field is valid. Do not place either Zabin bearer value in a
Goose recipe, settings file, or profile.

### Pi: fail-closed, no render target

Pi ships without native MCP or native permission prompts, so a third-party
extension (`pi-mcp-adapter`) would have to enforce Zabin's identity, naming,
approval, and secret rules itself — see
[`adapters/pi/COMPATIBILITY.md`](../adapters/pi/COMPATIBILITY.md) for the
full, pinned audit (blocking findings: no expected-`serverInfo` identity
check before credential release; conductor and worker canonical names
collide in one PI process; the MCP-App proxy dispatch path bypasses the
tool allowlist; no enforceable extension sandbox). There is no `pi` render
target — `adapters/pi/settings.json.template` intentionally ships with an
empty `{"packages": []}` and is never activated by this tooling. Whether Pi
consumes the shared `AGENTS.md` / Agent Skills the same way Goose does is
**unaudited** in this repository; treat it as unverified.

### OpenCode: supported, with documented limitations

Unlike Goose and Pi, OpenCode has a real adapter and render target — see
[OpenCode](#opencode) above for the install walkthrough. It is a strong
structural match for Zabin: it reads project-root `AGENTS.md` automatically,
discovers Agent Skills from `.agents/skills` with no adapter-specific fork,
speaks Streamable-HTTP remote MCP with `{env:VAR}`/`{file:path}` header
interpolation, and qualifies MCP tools per-server (`<serverkey>_<tool>`) so
Zabin's two surfaces coexist without name collisions — all
VERIFIED-BY-RUN in
[`adapters/opencode/COMPATIBILITY.md`](../adapters/opencode/COMPATIBILITY.md).
The audit's own live acceptance probe (dated section at the bottom of that
file) additionally rendered and installed the real `zabctl agents install`
output into a real OpenCode sandbox pointed at a live Zabin daemon: MCP
connect and the qualified tool list (83 real Zabin tools + 10 built-ins)
were exercised live and matched the render exactly. The permission map was
only partly exercised: the rendered top-level `opencode.json`'s `ask` rule
on `zabin_create_board` was refused client-side, before the call ever
reached the daemon (VERIFIED-BY-RUN). The per-role `deny` frontmatter in
`.opencode/agents/*.md` was confirmed present-and-correct in the render but
was **not** exercised through the `task`-tool subagent-dispatch path that
would actually invoke it — the audit labels this
**DOC-CITED-from-this-render**, not a fresh VERIFIED-BY-RUN claim
(`adapters/opencode/COMPATIBILITY.md:273`). The top-level `opencode.json`
itself contains no `deny` rules at all: its policy-derived approvals map to
`allow`/`allow`/`ask`.

The documented limitation is **version-pinned audit coverage**: OpenCode
ships multiple releases per week (the audit's own install-script check
observed the ambient system package already 21 patch versions ahead of the
pinned tag at audit time), so every VERIFIED-BY-RUN claim in the audit is
pinned to `v1.18.25` and must be re-run — the audit documents each probe's
exact, reproducible repro shape — before being relied on against a newer
release. A narrower, independently-verified limitation that does hold on
the pinned version: a custom `mode: subagent` agent (which is what this
bundle's rendered `.opencode/agents/*.md` roles are) cannot be launched as
the top-level session agent via `--agent`; it falls back to the default
agent. That agent remains fully dispatchable programmatically through the
`task` tool end to end — this refutes, for the pinned version, an assumed
upstream dispatch-breakage premise that must not be restated as current
fact.

A further documented limitation, separate from audit-version staleness: the
rendered top-level `opencode.json` opens each configured MCP server with a
`<serverkey>_*: allow` wildcard permission entry, so a Zabin tool the daemon
adds after the last render is auto-allowed with no prompt until the adapter
is re-rendered — re-render `opencode.json` after any daemon tool-inventory
change. The audit's row 6a shows the inverse case, a `<serverkey>_*: deny`
wildcard, is honored and hides the denied server's tools from the model
entirely, so a fail-closed variant of this wildcard is available if a
stricter default is ever wanted; deriving the wildcard's default from the
policy automatically is a separate, ledgered follow-up and is not
implemented by the current renderer.

Two further areas remain **unverified, not cleared**: OpenCode's own
tool-execution containment/sandboxing (`bash`, `edit`, arbitrary file
writes) was not assessed (`adapters/opencode/COMPATIBILITY.md`, "What was
not tested"), and no row of the audit probes the adapter's behavior when a
bearer credential is entirely unset — whether it fails open (continues
without the MCP extension, as Goose does) or fails closed (refuses to
start). Neither should be read as cleared.

### R10: version-dependent claims

Per this project's plan risk **R10**: external-harness claims that are not
backed by this repository's own compatibility audit and lock file — any
Goose, Pi, or OpenCode detail *not* traceable to
`adapters/goose/COMPATIBILITY.md`, `adapters/pi/COMPATIBILITY.md`, or
`adapters/opencode/COMPATIBILITY.md` — came from general research and may
age or drift with client releases. This guide states exactly which client
versions were verified — 1.45.0 for Goose, 0.84.1 / `pi-mcp-adapter` 2.22.0
for Pi, `v1.18.25` for OpenCode — and marks everything else version-dependent
rather than implying universal or current support. OpenCode's aging caveat
is sharper than Goose's or Pi's: given its release cadence, re-run
`adapters/opencode/COMPATIBILITY.md`'s reproducible probes before relying on
any of its verdicts against a release newer than `v1.18.25`.

## Credentials

Two independent bearer credentials, one per Zabin MCP surface — never place
either as a literal value in a repository file, generated adapter, recipe,
or command line:

| Surface | Environment variable | Default token-file name |
| --- | --- | --- |
| `conductor` | `ZABIN_MCP_TOKEN` | `~/.zabin/mcp.token` |
| `worker` | `ZABIN_MCP_WORKER_TOKEN` | `~/.zabin/mcp-worker.token` |

```sh
read -rsp 'Conductor token: ' ZABIN_MCP_TOKEN
export ZABIN_MCP_TOKEN
read -rsp 'Worker token: ' ZABIN_MCP_WORKER_TOKEN
export ZABIN_MCP_WORKER_TOKEN
```

Live diagnostics (`zabctl agents doctor --mode live`) resolve each surface's
credential from its raw-token environment variable first, then from an
explicit token-file path environment variable
(`ZABIN_MCP_TOKEN_FILE` / `ZABIN_MCP_WORKER_TOKEN_FILE`), else from the
default file above under `~/.zabin/`. Verified in place on this machine:
both `~/.zabin/mcp.token` and `~/.zabin/mcp-worker.token` exist at mode
`0600` (owner read/write only); a wider mode is refused, matching the
server's own token-file discipline. Static diagnostics (`--mode static`, the
default) never read either environment variable or token file.

[`config/zabin-mcp.json`](../config/zabin-mcp.json) is the single owner of
both surfaces' URLs, identities, transport, and credential *bindings* (names,
never values) — do not restate endpoint or port numbers anywhere else;
correct them there and re-render.

## The single-conductor model

[`skills/conductor`](../skills/conductor/README.md) is **the** conductor
contract — the one portable, MCP-based pipeline skill, installed by
`zabctl agents install`/`bootstrap` into `<destination>/.agents/skills`, and
bridged for the `claude_code` target as a manifest-tracked symlink at
`<destination>/.claude/skills/conductor` (see [Manual flow](#manual-flow-doctor--install--render)
above) so Claude Code discovers it without a forked copy. Any host-specific
translation belongs in an adapter note beside it, never in a forked copy: for
Claude Code that note is
[`skills/conductor/references/claude.md`](../skills/conductor/references/claude.md).

[`adapters/claude`](../adapters/claude) carries only the Claude-only extras
that don't belong in the portable skill: the six Workflow-tool payload
programs at `adapters/claude/workflows/` (installed to
`<destination>/.claude/workflows/`) and the capability-mapping /
vocabulary-translation reference above. Nothing in `adapters/claude` is a
portable requirement — a host without Claude's Workflow-tool primitive runs
the same pipeline states through whatever it does provide.

See the conductor skill's own README for the **conductor-mcp retirement
preconditions** — the project-local `conductor-mcp` skill some checkouts
still carry is redundant with this installed one, and its retirement is a
separate, deliberate, user-triggered step with its own backlog-triage and
deployment-specifics preconditions; it is not automatic on install.

## Upgrading a stale `zabctl`

`doctor`'s `contracts_bundle` check fails outright against a binary built
before the bundle's current schema — for example a `pathPattern` addition an
older build has no matcher for:

```text
Zabin doctor: FAIL (static mode)
  - [FAIL] contracts_bundle: #/$defs/pathPattern: pattern '...' has no code-owned matcher
error: contract: agent workflow diagnostics failed: contracts_bundle
```

Rebuild or reinstall `zabctl` (`cargo install --path src/zabin-cli` from the
zabin workspace, or copy the current release artifact) before doing anything
else. Before adopting a rendered `.claude/{agents,skills,workflows}` set over
a hand-maintained one, back it up first — `install`/`render` treat those
paths as installer-owned once adopted, and the collision rule above refuses
to run until pre-existing unmanaged content is moved aside.

Full command reference and live-mode diagnostics:
[docs/DEVELOPMENT.md](DEVELOPMENT.md). System design and trust boundaries:
[docs/ARCHITECTURE.md](ARCHITECTURE.md).
