# Portable Agent Contracts

This repository is the source of truth for portable role instructions, skills,
client adapters, schemas, and the policy for two Zabin MCP surfaces. It renders
and installs configuration for supported clients without embedding credentials,
and validates the same contracts with the `zabctl agents` command family. For
the full per-client, end-to-end setup walkthrough, see
[docs/INSTALL.md](docs/INSTALL.md). The project-manager skill under `pm/` at
the repository root is deliberately outside this bundle and is never
installed by `zabctl agents install`.

## Client support

| Client | Status | Adapter output |
| --- | --- | --- |
| Claude Code | Supported, fully rendered | `.mcp.json`, `.claude/settings.json`, `.claude/agents/<role>.md` × 13, `.claude/workflows/*.js` × 6 |
| Codex | Supported, fully rendered | `.codex/config.toml` |
| Goose 1.45.0 | Unsupported; fail closed | Inert inspection output only (`goose/recipe.json`, `goose/settings.json`); no active artifact |
| PI | Unsupported; fail closed | Disabled template (`{"packages": []}`); no render target |
| OpenCode v1.18.25 | Supported, with documented limitations | `opencode.json`, `.opencode/agents/<role>.md` × 13; native `.agents/skills` consumption (no bridge); consumes project-root `AGENTS.md` if present (not itself an installed artifact) |

Goose is an explicit renderer and installer target so its fail-closed behavior
can be audited, but it is not a supported or activatable Zabin client. Its
[compatibility audit](adapters/goose/COMPATIBILITY.md) and
[client lock](adapters/goose/client-lock.json) pin version 1.45.0 and authorize
no active recipe or settings artifact. PI is neither an installer nor renderer
target; its decision is recorded in [PI compatibility](adapters/pi/COMPATIBILITY.md),
the [extension lock](adapters/pi/extension-lock.json), and the
[disabled settings template](adapters/pi/settings.json.template). The
[conformance lock](tests/conformance/runner-lock.json) independently keeps both
clients unsupported. OpenCode is a rendered, **opt-in** installer/render
target — name it explicitly with `--target opencode`, it is not part of the
default target set — pinned to and audited against OpenCode `v1.18.25`; see
its [compatibility audit](adapters/opencode/COMPATIBILITY.md) for the full
per-claim evidence, including a shipped acceptance probe that ran the real
installer's output against a live daemon. Unlike Goose and PI, OpenCode
carries no client-lock/extension-lock file and no entry in the
[conformance lock](tests/conformance/runner-lock.json) — its `v1.18.25` pin
is documentary only, not mechanically enforced; re-verifying it means
manually re-running the audit's own probes
([compatibility audit](adapters/opencode/COMPATIBILITY.md)), not
`zabctl agents conformance`. It consumes the portable `AGENTS.md` and
`.agents/skills` layout natively, with no adapter-specific fork or bridge
required. Its documented limitation is version-pinned audit coverage:
OpenCode ships multiple releases per week, so every verified-by-run claim in
the audit is pinned to `v1.18.25` and must be re-run before being relied on
against a newer release; a narrower, independently-verified limitation is
that a custom `mode: subagent` agent cannot be launched as the top-level
session agent via `--agent` (it falls back to the default agent) — it
remains fully dispatchable programmatically through the `task` tool, as
verified for a synthetic, project-defined subagent probe
(`adapters/opencode/COMPATIBILITY.md` row 7) — not a claim about how
Zabin's own worker roles are invoked, since this bundle's workflow programs
are `claude_code`-only. See
[docs/INSTALL.md](docs/INSTALL.md#r10-version-dependent-claims).

## Quick start

The agent-contracts tooling is the `zabctl agents` command family, implemented
in the zabin repository's `zabin-agent-tooling` crate and shipped in the
`zabctl` binary. `zabctl agents bootstrap --repo <git-url>` clones (or
fast-forwards) this repository and runs static diagnostics in one step;
name `--install-into <dir>` to also install and render adapters in the same
call. A record-driven bare re-run checks and reports without writing; pass
`--apply` to perform the recorded install. See
[docs/INSTALL.md](docs/INSTALL.md) for the full walkthrough, including the
exact behavior when `--install-into`, `--apply`, or neither is given.

From a trusted checkout, the offline static diagnostics alone:

```sh
zabctl agents doctor
```

Static diagnostics do not access the network or read credential values;
`--report-path <PATH>` additionally writes the JSON report (mode `0600`). The
contract, render, install, recovery, and conformance behavior is covered by the
zabin workspace test suites (`cargo test -p zabin-agent-tooling`) and by
`zabctl agents conformance`. See [Development](docs/DEVELOPMENT.md) for the
maintained setup and verification workflow.

## Safe installation

The installer has no implicit home-directory destinations. Use a trusted,
absolute destination and inspect a dry run before copying:

```sh
zabctl agents install \
  --mode dry-run \
  --destination /absolute/path/to/destination

zabctl agents install \
  --mode copy \
  --destination /absolute/path/to/destination

zabctl agents install \
  --mode check \
  --destination /absolute/path/to/destination
```

The installer lays out the portable role instructions under `<destination>/agents`
and the Agent Skills under `<destination>/.agents/skills`, recording ownership in
`<destination>/.zabin/installer-manifest.json`; it also renders and installs
every default client adapter (`claude_code` and `codex` — `.mcp.json`,
`.claude/settings.json`, `.claude/agents/*.md`, `.claude/workflows/*.js`,
`.codex/config.toml`) in the same run, needing no credential environment
variables to do so (the headers it writes are `${VAR}` reference strings, not
values). `zabctl agents render --target <name>` regenerates or audits one
target's artifacts in isolation instead — for example the inert Goose
evidence below — and, unlike `install`, does require both credential
environment variables to be set before it writes anything. `--mode symlink`
links a locally trusted development destination at the source instead of
copying. File installation does not grant workspace trust, approve MCP
servers, or activate them; those remain separate client-controlled states.

## Goose audit workflow

Use only disposable, explicit destinations when inspecting the Goose 1.45.0
target. Rendering produces credential-free, inactive evidence; it does not
produce configuration that may be activated:

```sh
zabctl agents render \
  --target goose \
  --output-dir /absolute/disposable/goose-render \
  --mode dry-run
zabctl agents render \
  --target goose \
  --output-dir /absolute/disposable/goose-render \
  --mode write
zabctl agents render \
  --target goose \
  --output-dir /absolute/disposable/goose-render \
  --mode check
```

The installer never produces an active Goose recipe or settings artifact. Its
copy and check modes synchronize only the shared portable role instructions and
Agent Skills, reporting activation `inactive`:

```sh
zabctl agents install \
  --mode dry-run \
  --destination /absolute/disposable/goose-dest
zabctl agents install \
  --mode copy \
  --destination /absolute/disposable/goose-dest
zabctl agents install \
  --mode check \
  --destination /absolute/disposable/goose-dest
```

Goose can reuse the canonical project `AGENTS.md` hierarchy and Agent Skills in
`.agents/skills`; do not fork those contracts into a Goose-specific prompt.
That reuse does not clear the native-client blockers: Goose can release an HTTP
credential before trusted MCP identity is established, continue without an
extension when a secret is absent, resolve conflicting mutable permissions to
allow, and lacks the required trust, containment, official-artifact, and active
cleanup evidence. Native observations therefore cannot change the unsupported
status.

## MCP surfaces and credentials

[The canonical policy](config/zabin-mcp.json) defines separate Streamable HTTP
surfaces:

- `conductor` exposes the broader policy-controlled surface, including operations
  that require explicit approval or a human gate.
- `worker` exposes a smaller task-scoped allowlist and denies durable,
  destructive, and human-interaction classes.

Use the URLs in `config/zabin-mcp.json`; HTTP endpoint addresses are
configuration-driven. Port `50051` is the gRPC listener, not an HTTP endpoint.

| Surface | Environment variable | Default diagnostic file name |
| --- | --- | --- |
| `conductor` | `ZABIN_MCP_TOKEN` | `mcp.token` |
| `worker` | `ZABIN_MCP_WORKER_TOKEN` | `mcp-worker.token` |

Do not commit credential files or values. Live diagnostics are opt-in with
`zabctl agents doctor --mode live`; each surface's credential is resolved from
its environment variable (above), then from a token file — the path in
`ZABIN_MCP_TOKEN_FILE` / `ZABIN_MCP_WORKER_TOKEN_FILE`, else the default file
above under `~/.zabin/`. These environment-variable and default file names are
the complete credential information documented here; never place either value
in a Goose recipe, settings file, command line, report, or repository file.

## Verification and reference

- [Installation guide](docs/INSTALL.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Code standards](docs/CODE_STANDARDS.md)
- [Development](docs/DEVELOPMENT.md)
- [Review focus](docs/REVIEW_FOCUS.md)
- [Conformance guide](tests/conformance/README.md)
