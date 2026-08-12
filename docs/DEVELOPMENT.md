# Portable Agent Contracts - Development Guide

## Prerequisites

- A local clone of this repository.
- Python 3.11 or newer for rendering, installation, diagnostics, recovery support, and the dependency-free unit suite.
- No Python package installation is required for ordinary development.
- Supported native clients are needed only to install and observe their adapters.
- Full locked conformance additionally requires the exact Python, Node, client, official runner, transitive lock, and artifact versions recorded in `tests/conformance/runner-lock.json`. The runner downloads nothing.

Run commands from the repository root. Use a disposable directory for examples and replace every `/absolute/...` placeholder with an explicit path you control.

## Credential Setup

The canonical policy uses separate bearer credentials for the conductor and worker surfaces:

```bash
read -rsp 'Conductor token: ' ZABIN_MCP_TOKEN
export ZABIN_MCP_TOKEN
read -rsp 'Worker token: ' ZABIN_MCP_WORKER_TOKEN
export ZABIN_MCP_WORKER_TOKEN
```

Do not place literal values in repository files or generated adapters. Claude configuration interpolates the environment variables; Codex configuration stores their names for runtime lookup. Live diagnostics may instead read explicit token files:

```bash
python scripts/zabin_doctor.py --live \
  --conductor-token-file /absolute/restricted/mcp.token \
  --worker-token-file /absolute/restricted/mcp-worker.token
```

Restrict token files to the current user. Static diagnostics do not read environment values or token files.

Recovery checkpoints default to `.runtime/checkpoints` under the repository root. To keep them elsewhere, set an explicit state directory:

```bash
export ZABIN_RECOVERY_STATE_DIR=/absolute/restricted/checkpoints
```

## Dependency-Free Tests

Run the complete default suite:

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

Run focused contract and subsystem suites:

```bash
python -m unittest tests.test_contract_schemas
python -m unittest tests.test_render_adapters
python -m unittest tests.test_install_adapters
python -m unittest tests.test_recovery_checkpoint
python -m unittest tests.test_zabin_doctor
python -m unittest discover -s tests/conformance -p 'test_*.py'
```

These tests use standard-library fixtures and mocks and do not require live Zabin endpoints.

## Generate Client Adapters

Rendering requires an explicit target, output directory, and both credential environment variables. It validates policy and schema, renders in memory, and writes deterministic artifacts atomically; missing, empty, or literal placeholder credentials fail before output.

Preview without writing:

```bash
python scripts/render_adapters.py \
  --target claude_code \
  --output-dir /absolute/staging/claude \
  --dry-run

python scripts/render_adapters.py \
  --target codex \
  --output-dir /absolute/staging/codex \
  --dry-run
```

Write artifacts, then verify that the destination has no drift:

```bash
python scripts/render_adapters.py \
  --target claude_code \
  --output-dir /absolute/staging/claude
python scripts/render_adapters.py \
  --target claude_code \
  --output-dir /absolute/staging/claude \
  --check

python scripts/render_adapters.py \
  --target codex \
  --output-dir /absolute/staging/codex
python scripts/render_adapters.py \
  --target codex \
  --output-dir /absolute/staging/codex \
  --check
```

Codex `requirements.toml` is a separate administrator-owned enforcement artifact. Ordinary generation and installation never deploy it:

```bash
python scripts/render_adapters.py \
  --target codex_admin_requirements \
  --output-dir /absolute/admin-staging \
  --admin-deployment
```

An administrator must deploy that staged file through the supported system policy workflow and verify the effective client policy.

## Install and Check Portable Assets

The installer has no implicit home-directory destination. Always provide the project, skills, and role-instruction destinations. Begin with a dry run:

```bash
python scripts/install_adapters.py \
  --mode dry-run \
  --project-destination /absolute/project \
  --skills-destination /absolute/client/skills \
  --instructions-destination /absolute/client/agents \
  --target claude_code \
  --target codex
```

Install copies only after reviewing the plan and obtaining client workspace trust and server approval separately:

```bash
python scripts/install_adapters.py \
  --mode copy \
  --project-destination /absolute/project \
  --skills-destination /absolute/client/skills \
  --instructions-destination /absolute/client/agents \
  --target claude_code \
  --target codex \
  --workspace-trust approved \
  --server-approval approved \
  --activation active
```

Verify the installed state without changing it:

```bash
python scripts/install_adapters.py \
  --mode check \
  --project-destination /absolute/project \
  --skills-destination /absolute/client/skills \
  --instructions-destination /absolute/client/agents \
  --target claude_code \
  --target codex \
  --workspace-trust approved \
  --server-approval approved \
  --activation active
```

Check mode exits `1` for drift and `2` for an unsafe or invalid installation. Symlink mode is available for locally trusted development destinations; copy mode is the safer default for independent installations.

## Static Diagnostics

Static doctor validates schemas, role and tier contracts, policy, templates, rendered adapter semantics, PI support state, and recovery contracts without network access or credential reads:

```bash
python scripts/zabin_doctor.py
python scripts/zabin_doctor.py --json
```

A failing check exits nonzero. A degraded live result remains distinguishable from a full failure.

## Opt-in Live Diagnostics

With both canonical endpoints running and credentials available, probe the exact conductor and worker surfaces:

```bash
python scripts/zabin_doctor.py --live --json
```

The canonical endpoints are `127.0.0.1:50052/mcp` for conductor and `127.0.0.1:50053/mcp-worker` for worker. Port `50051` is the Zabin gRPC listener, not a Streamable HTTP MCP endpoint. Use URL overrides only for an explicitly configured Streamable HTTP gateway:

```bash
python scripts/zabin_doctor.py --live \
  --conductor-url http://127.0.0.1:61052/mcp \
  --worker-url http://127.0.0.1:61053/mcp-worker
```

Live diagnostics are read-only. They verify identity and inventory, credential separation, and authorization boundaries while reporting credential availability rather than values.

## Conformance

The local conformance runner is fail closed and normally exits nonzero until all required native-host and lifecycle evidence is supplied:

```bash
python scripts/run_conformance.py
```

Its default redacted mode-0600 report is written beneath `/tmp/codex-artifacts/<checkout-name>/conformance/`; choose another output explicitly when needed:

```bash
python scripts/run_conformance.py --output /absolute/restricted/conformance.json
```

Run the opt-in read-only live unit probe:

```bash
ZABIN_RUN_LIVE_CONFORMANCE=1 \
  python -m unittest discover -s tests/conformance -p 'test_live_mcp.py'
```

For a full live run, provision the exact already-downloaded official artifact set from the lock and export only its paths:

```bash
export ZABIN_CONFORMANCE_ARTIFACT=/absolute/verified/conformance/dist/index.js
export ZABIN_CONFORMANCE_TRANSITIVE_LOCK=/absolute/verified/package-lock.json
export ZABIN_CONFORMANCE_TRANSITIVE_ARTIFACT_MANIFEST=/absolute/verified/artifacts.json

python scripts/run_conformance.py --live \
  --host-report claude_code=/absolute/restricted/claude-report.json \
  --host-report codex=/absolute/restricted/codex-report.json \
  --lifecycle-evidence /absolute/restricted/disposable-lifecycle.json
```

Lifecycle evidence must describe a disposable project. Observing a reviewed non-disposable project requires both deliberate evidence and an exact allowlist:

```bash
python scripts/run_conformance.py \
  --lifecycle-evidence /absolute/restricted/approved-production-observation.json \
  --allow-project prj_exactly_reviewed
```

Never add expected-failure flags, substitute another runner lock, or point a live lifecycle test at production merely to make the aggregate pass.

## Release Gate

Before releasing contract or adapter changes, run the dependency-free suite, static diagnostics, deterministic render checks for supported clients, and the static conformance runner with the required observer/lifecycle evidence for the intended claim:

```bash
python -m unittest discover -s tests -p 'test_*.py'
python scripts/zabin_doctor.py --json
python scripts/render_adapters.py --target claude_code --output-dir /absolute/release/claude
python scripts/render_adapters.py --target claude_code --output-dir /absolute/release/claude --check
python scripts/render_adapters.py --target codex --output-dir /absolute/release/codex
python scripts/render_adapters.py --target codex --output-dir /absolute/release/codex --check
python scripts/run_conformance.py \
  --host-report claude_code=/absolute/restricted/claude-report.json \
  --host-report codex=/absolute/restricted/codex-report.json \
  --lifecycle-evidence /absolute/restricted/disposable-lifecycle.json \
  --output /absolute/restricted/release-conformance.json
```

Use `--live` only when claiming live protocol conformance and all locked prerequisites are present. Release evidence must not contain skipped, stale, unscored, expected-failure, identity, authorization, redaction, or cleanup gaps.

## Troubleshooting

### Renderer rejects policy or templates

Run static doctor and the focused contract/render tests. Fix canonical policy, its schema, or the selected template rather than hand-editing generated output. Empty allowlists, unknown tools, duplicate entries, identity mismatch, and unexpressive targets fail closed by design.

### Check mode reports drift

Review the reported paths. Re-render or reinstall only from a trusted canonical checkout. Do not overwrite an unmanaged collision or a modified installer-owned component; preserve the destination and investigate ownership first.

### Installation refuses a destination

Use explicit absolute destinations outside the canonical source trees. Remove no files by hand while an installation is running. Unsafe symlinks, non-regular files, overlapping source/destination trees, parse failures, and identity changes are refusal conditions.

### Live doctor cannot connect

Confirm that the two Streamable HTTP gateways—not the gRPC listener—are running, then confirm credential availability by name in static output. Do not print token values while debugging. Authentication, reset, timeout, identity, and inventory failures remain distinct diagnostics.

### Full conformance fails before launch

Compare the installed runtimes and clients with `tests/conformance/runner-lock.json`. Supply the exact regular official artifact, transitive lock, and complete tarball manifest; the runner rejects symlinks, alternate locks, missing digests, unpinned dependencies, version drift, and incomplete observer or lifecycle evidence before starting live clients.

PI has no installation command. Its current support boundary and evidence are documented in [ARCHITECTURE.md](ARCHITECTURE.md#mcp-surfaces-and-authority) and `adapters/pi/COMPATIBILITY.md`.

System design lives in [ARCHITECTURE.md](ARCHITECTURE.md); coding and testing conventions live in [CODE_STANDARDS.md](CODE_STANDARDS.md).
