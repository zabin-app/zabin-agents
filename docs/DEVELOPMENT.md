# Portable Agent Contracts - Development Guide

## Prerequisites

- A local clone of this repository.
- A built `zabctl` binary. Rendering, installation, diagnostics, recovery, and conformance are the `zabctl agents` command family, implemented in the zabin repository's `zabin-agent-tooling` crate; build it with `cargo build --release -p zabin-cli` in the zabin workspace, or use an installed `zabctl`.
- Native clients are needed only to install or observe their adapters. Goose 1.45.0 is an optional pinned observation target and remains unsupported.
- Full locked conformance additionally requires the exact Node, client, official runner, transitive lock, and artifact versions recorded in `tests/conformance/runner-lock.json`. The runner downloads nothing.

Run commands from the repository root. Use a disposable directory for examples and replace every `/absolute/...` placeholder with an explicit path you control.

## Credential Setup

The canonical policy uses separate bearer credentials for the conductor and worker surfaces:

```bash
read -rsp 'Conductor token: ' ZABIN_MCP_TOKEN
export ZABIN_MCP_TOKEN
read -rsp 'Worker token: ' ZABIN_MCP_WORKER_TOKEN
export ZABIN_MCP_WORKER_TOKEN
```

Do not place literal values in repository files or generated adapters. Claude configuration interpolates the environment variables; Codex configuration stores their names for runtime lookup. The unsupported Goose target must not consume or persist either value. Live diagnostics may instead read explicit token files, named per surface by their file-path environment variables:

```bash
ZABIN_MCP_TOKEN_FILE=/absolute/restricted/mcp.token \
ZABIN_MCP_WORKER_TOKEN_FILE=/absolute/restricted/mcp-worker.token \
  zabctl agents doctor --mode live --contracts-root "$PWD"
```

Each surface's credential resolves from its raw-token environment variable first, then from the token file above, else from `$HOME/.zabin/mcp.token` / `$HOME/.zabin/mcp-worker.token`. Restrict token files to the current user. Static diagnostics do not read environment values or token files.

Recovery checkpoints default to `.runtime/checkpoints` under the repository root. To keep them elsewhere, set an explicit state directory:

```bash
export ZABIN_RECOVERY_STATE_DIR=/absolute/restricted/checkpoints
```

## Tests

The `zabctl agents` behavior is covered by the `zabin-agent-tooling` crate's
integration tests in the zabin workspace. Run the complete suite:

```bash
cargo test -p zabin-agent-tooling
```

The focused contract and subsystem suites are the per-command test files under
`src/zabin-agent-tooling/tests/`: `contracts.rs`, `render.rs`, `install.rs`,
`doctor.rs`, `recovery.rs`, `conformance.rs`, `cutover.rs`, and `foundation.rs`.
Run one with `cargo test -p zabin-agent-tooling --test <name>` (for example
`--test render`).

These tests use in-tree fixtures and temporary directories and do not require live Zabin endpoints.

## Generate Client Adapters

Rendering requires an explicit target, output directory, and both credential environment variables. It validates policy and schema, renders in memory, and writes deterministic artifacts atomically; missing, empty, or literal placeholder credentials fail before output. `--mode` selects `dry-run`, `write` (the default), or `check`; the supported targets are `claude_code`, `codex`, `goose`, and `opencode` (the authoritative list is `zabctl agents render --help` / INSTALL.md's target section).

Preview without writing:

```bash
zabctl agents render \
  --target claude_code \
  --output-dir /absolute/staging/claude \
  --mode dry-run

zabctl agents render \
  --target codex \
  --output-dir /absolute/staging/codex \
  --mode dry-run
```

Write artifacts, then verify that the destination has no drift (`check` exits 1 on drift):

```bash
zabctl agents render \
  --target claude_code \
  --output-dir /absolute/staging/claude \
  --mode write
zabctl agents render \
  --target claude_code \
  --output-dir /absolute/staging/claude \
  --mode check

zabctl agents render \
  --target codex \
  --output-dir /absolute/staging/codex \
  --mode write
zabctl agents render \
  --target codex \
  --output-dir /absolute/staging/codex \
  --mode check
```

Codex `requirements.toml` is a separate administrator-owned enforcement artifact. Ordinary generation and installation never deploy it. In this build the `codex_admin_requirements` render target is **library-only**: it requires explicit administrator-deployment authorization that the `render` command does not expose (there is no `--admin-deployment` flag), so the CLI refuses to render it. An administrator must deploy that artifact through the supported system policy workflow and verify the effective client policy.

### Audit the inert Goose target

Goose 1.45.0 is lock-gated and unsupported. These commands require no credential values and render or compare only inert status artifacts:

```bash
zabctl agents render --target goose --output-dir /absolute/staging/goose --mode dry-run
zabctl agents render --target goose --output-dir /absolute/staging/goose --mode write
zabctl agents render --target goose --output-dir /absolute/staging/goose --mode check
```

Do not convert the output into an active recipe or settings file. The audited gates and re-evaluation boundary live in [`adapters/goose/COMPATIBILITY.md`](../adapters/goose/COMPATIBILITY.md).

## Install and Check Portable Assets

The installer has no implicit home-directory destination. Always provide an explicit, absolute destination. Begin with a dry run:

```bash
zabctl agents install \
  --mode dry-run \
  --destination /absolute/destination
```

Install copies only after reviewing the plan. Obtaining client workspace trust and server approval remain separate states that installation never grants:

```bash
zabctl agents install \
  --mode copy \
  --destination /absolute/destination
```

Verify the installed state without changing it:

```bash
zabctl agents install \
  --mode check \
  --destination /absolute/destination
```

The installer writes the portable role instructions under `<destination>/agents` and the Agent Skills under `<destination>/.agents/skills`, tracking ownership in `<destination>/.zabin/installer-manifest.json`; it reports an `activation` state that stays `inactive` until a client grants it, and never marks itself active. Check mode exits `1` for drift and `2` for an unsafe or invalid installation. `--mode symlink` is available for locally trusted development destinations; `copy` is the safer default for independent installations.

The unsupported Goose path creates no active Goose configuration. The installer has no per-client target; it plans only the shared portable roles and skills and reports activation `inactive`:

```bash
zabctl agents install --mode dry-run --destination /absolute/destination
zabctl agents install --mode check --destination /absolute/destination
```

An unsupported Goose target must report inactive and must not own `goose/recipe.json` or `goose/settings.json`; those artifacts are produced only by `zabctl agents render --target goose` as inert evidence.

## Static Diagnostics

Static doctor (`--mode static`, the default) validates schemas, role and tier contracts, policy, templates, rendered adapter semantics, conditional client support states, and recovery contracts without network access or credential reads. The human summary prints to stdout; `--report-path` additionally writes the JSON report (mode `0600`):

```bash
zabctl agents doctor
zabctl agents doctor --report-path /absolute/restricted/doctor-report.json
```

A failing check exits nonzero. Static doctor against this repository's own bundle reports overall `DEGRADED`, which is exit **0** — a diagnostic finding, distinguishable from a full failure.

Static doctor reports Goose's unsupported status and blocking gate identifiers as a diagnosis, not as client support: the `goose_compatibility` check reports `DEGRADED` and keeps the overall run at exit 0. Comparing an explicitly selected Goose executable against the pinned observation is a conformance concern — use `zabctl agents conformance --mode live` with `GOOSE_NATIVE_BINARY` / `GOOSE_PATH_ROOT` (see Conformance below); it runs the executable under an isolated temporary `GOOSE_PATH_ROOT`, does not activate the adapter, and cannot upgrade the support decision.

## Opt-in Live Diagnostics

With both canonical endpoints running and credentials available, probe the exact conductor and worker surfaces. `--mode live` reads real credentials, so it **refuses a discovered contracts root** — name the bundle explicitly with `--contracts-root`:

```bash
zabctl agents doctor --mode live --contracts-root "$PWD"
```

The canonical endpoints are `127.0.0.1:50052/mcp` for conductor and `127.0.0.1:50053/mcp-worker` for worker. Port `50051` is the Zabin gRPC listener, not a Streamable HTTP MCP endpoint. This build probes those canonical loopback surfaces directly; there is no CLI URL override.

Live diagnostics are read-only. They verify identity and inventory, credential separation, and authorization boundaries while reporting credential availability rather than values.

## Conformance

The conformance runner is fail closed. Static mode (`--mode static`, the default) checks the runner lock, policy parity, artifact integrity, and prior report evidence offline; against the shipped lock it is an **expected non-pass** (exit 2), naming every unmet requirement rather than assuming it:

```bash
zabctl agents conformance
```

Write the redacted report (mode `0600`) with `--report-path`:

```bash
zabctl agents conformance --report-path /absolute/restricted/conformance.json
```

Evidence for what can be satisfied offline is supplied through the environment variables the lock itself names, not CLI flags — the official artifact set, the per-host reports, and the lifecycle evidence:

```bash
export ZABIN_CONFORMANCE_ARTIFACT=/absolute/verified/conformance/dist/index.js
export ZABIN_CONFORMANCE_TRANSITIVE_LOCK=/absolute/verified/package-lock.json
export ZABIN_CONFORMANCE_TRANSITIVE_ARTIFACT_MANIFEST=/absolute/verified/artifacts.json
export ZABIN_CONFORMANCE_CLAUDE_CODE_REPORT=/absolute/restricted/claude-report.json
export ZABIN_CONFORMANCE_CODEX_REPORT=/absolute/restricted/codex-report.json
export ZABIN_CONFORMANCE_GOOSE_REPORT=/absolute/restricted/goose-report.json
export ZABIN_CONFORMANCE_LIFECYCLE_EVIDENCE=/absolute/restricted/disposable-lifecycle.json
```

For a full live run, add `--mode live`, which launches the pinned clients under isolated roots and therefore **refuses a discovered contracts root** — name it with `--contracts-root`. Goose observation additionally reads `GOOSE_NATIVE_BINARY` and `GOOSE_PATH_ROOT`:

```bash
GOOSE_NATIVE_BINARY=/absolute/path/to/goose \
  zabctl agents conformance --mode live --contracts-root "$PWD" \
    --report-path /absolute/restricted/conformance.json
```

The Goose report must describe an explicit pinned binary, an isolated disposable `GOOSE_PATH_ROOT`, loopback observations, redacted in-memory streams, and complete fixture cleanup. With the committed Goose 1.45.0 lock, its required support gate fails even when all observational fields are valid, so the aggregate conformance result is intentionally non-pass. Report shape and fixture requirements live in [`tests/conformance/README.md`](../tests/conformance/README.md).

Lifecycle evidence must describe a disposable project. Observing a reviewed non-disposable project requires both deliberate evidence and an exact allowlist, supplied through `ZABIN_CONFORMANCE_LIFECYCLE_EVIDENCE` and `ZABIN_CONFORMANCE_PROJECT_ALLOWLIST`:

```bash
ZABIN_CONFORMANCE_LIFECYCLE_EVIDENCE=/absolute/restricted/approved-production-observation.json \
ZABIN_CONFORMANCE_PROJECT_ALLOWLIST=prj_exactly_reviewed \
  zabctl agents conformance --mode live --contracts-root "$PWD"
```

Never substitute another runner lock or point a live lifecycle test at production merely to make the aggregate pass.

## Release Gate

Before releasing contract or adapter changes, run the crate test suite, static diagnostics, deterministic render checks for supported clients, and the static conformance runner with the required observer/lifecycle evidence for the intended claim:

```bash
cargo test -p zabin-agent-tooling
zabctl agents doctor
zabctl agents render --target claude_code --output-dir /absolute/release/claude --mode write
zabctl agents render --target claude_code --output-dir /absolute/release/claude --mode check
zabctl agents render --target codex --output-dir /absolute/release/codex --mode write
zabctl agents render --target codex --output-dir /absolute/release/codex --mode check
zabctl agents render --target goose --output-dir /absolute/release/goose --mode write
zabctl agents render --target goose --output-dir /absolute/release/goose --mode check
ZABIN_CONFORMANCE_CLAUDE_CODE_REPORT=/absolute/restricted/claude-report.json \
ZABIN_CONFORMANCE_CODEX_REPORT=/absolute/restricted/codex-report.json \
ZABIN_CONFORMANCE_LIFECYCLE_EVIDENCE=/absolute/restricted/disposable-lifecycle.json \
  zabctl agents conformance --report-path /absolute/restricted/release-conformance.json
```

Use `--mode live` only when claiming live protocol conformance and all locked prerequisites are present. Release evidence must not contain skipped, stale, unscored, expected-failure, identity, authorization, redaction, or cleanup gaps.

## Troubleshooting

### Renderer rejects policy or templates

Run `zabctl agents doctor` and the crate's focused contract/render tests (`cargo test -p zabin-agent-tooling --test contracts`, `--test render`). Fix canonical policy, its schema, or the selected template rather than hand-editing generated output. Empty allowlists, unknown tools, duplicate entries, identity mismatch, and unexpressive targets fail closed by design.

### Check mode reports drift

Review the reported paths. Re-render or reinstall only from a trusted canonical checkout. Do not overwrite an unmanaged collision or a modified installer-owned component; preserve the destination and investigate ownership first.

### Installation refuses a destination

Use explicit absolute destinations outside the canonical source trees. Remove no files by hand while an installation is running. Unsafe symlinks, non-regular files, overlapping source/destination trees, parse failures, and identity changes are refusal conditions.

### Live doctor cannot connect

Confirm that the two Streamable HTTP gateways—not the gRPC listener—are running, then confirm credential availability by name in static output. Do not print token values while debugging. Authentication, reset, timeout, identity, and inventory failures remain distinct diagnostics.

### Full conformance fails before launch

Compare the installed runtimes and clients with `tests/conformance/runner-lock.json`. Supply the exact regular official artifact, transitive lock, and complete tarball manifest; the runner rejects symlinks, alternate locks, missing digests, unpinned dependencies, version drift, and incomplete observer or lifecycle evidence before starting live clients.

Goose and PI have no active installation command. Their current support boundaries are summarized in [ARCHITECTURE.md](ARCHITECTURE.md) and detailed in `adapters/goose/COMPATIBILITY.md` and `adapters/pi/COMPATIBILITY.md`.

System design lives in [ARCHITECTURE.md](ARCHITECTURE.md); coding and testing conventions live in [CODE_STANDARDS.md](CODE_STANDARDS.md).
