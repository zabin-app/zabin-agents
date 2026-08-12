# Portable Agent Contracts

This repository is the source of truth for portable role instructions, skills,
client adapters, schemas, and the policy for two Zabin MCP surfaces. It renders
and installs configuration for supported clients without embedding credentials,
and validates the same contracts with dependency-free Python tooling.

## Client support

| Client | Status | Adapter output |
| --- | --- | --- |
| Claude Code | Supported | `.mcp.json` and `.claude/settings.json` |
| Codex | Supported | `.codex/config.toml` |
| Goose 1.45.0 | Unsupported; fail closed | Inert inspection output only; no active artifact |
| PI | Unsupported; fail closed | Disabled template (`{"packages": []}`) |

Goose is an explicit renderer and installer target so its fail-closed behavior
can be audited, but it is not a supported or activatable Zabin client. Its
[compatibility audit](adapters/goose/COMPATIBILITY.md) and
[client lock](adapters/goose/client-lock.json) pin version 1.45.0 and authorize
no active recipe or settings artifact. PI is neither an installer nor renderer
target; its decision is recorded in [PI compatibility](adapters/pi/COMPATIBILITY.md),
the [extension lock](adapters/pi/extension-lock.json), and the
[disabled settings template](adapters/pi/settings.json.template). The
[conformance lock](tests/conformance/runner-lock.json) independently keeps both
clients unsupported.

## Quick start

Python 3.11 or newer is required; the repository has no runtime dependencies.
From a trusted checkout, run the offline static diagnostics and unit tests:

```sh
python scripts/zabin_doctor.py --json
python -m unittest discover -s tests -p 'test_*.py'
```

Static diagnostics do not access the network or read credential files. See
[Development](docs/DEVELOPMENT.md) for the maintained setup and verification
workflow.

## Safe installation

The installer has no implicit home-directory destinations. Use trusted,
absolute, non-overlapping paths and inspect a dry run before copying:

```sh
python scripts/install_adapters.py \
  --mode dry-run \
  --project-destination /absolute/path/to/project \
  --skills-destination /absolute/path/to/client-skills \
  --instructions-destination /absolute/path/to/client-instructions

python scripts/install_adapters.py \
  --mode copy \
  --project-destination /absolute/path/to/project \
  --skills-destination /absolute/path/to/client-skills \
  --instructions-destination /absolute/path/to/client-instructions

python scripts/install_adapters.py \
  --mode check \
  --project-destination /absolute/path/to/project \
  --skills-destination /absolute/path/to/client-skills \
  --instructions-destination /absolute/path/to/client-instructions
```

By default both supported client adapters are included. Repeat `--target` with
`claude_code` and/or `codex` to select targets. File installation does not grant
workspace trust, approve MCP servers, or activate them; those remain separate
client-controlled states.

## Goose audit workflow

Use only disposable, explicit destinations when inspecting the Goose 1.45.0
target. Rendering produces credential-free, inactive evidence; it does not
produce configuration that may be activated:

```sh
python scripts/render_adapters.py \
  --target goose \
  --output-dir /absolute/disposable/goose-render \
  --dry-run
python scripts/render_adapters.py \
  --target goose \
  --output-dir /absolute/disposable/goose-render
python scripts/render_adapters.py \
  --target goose \
  --output-dir /absolute/disposable/goose-render \
  --check
```

The installer target remains inert under the unsupported lock. Its copy and
check modes may synchronize the shared portable instructions and skills, but
must create no active Goose recipe or settings artifact:

```sh
python scripts/install_adapters.py \
  --mode dry-run \
  --project-destination /absolute/disposable/goose-project \
  --skills-destination /absolute/disposable/goose-client/.agents/skills \
  --instructions-destination /absolute/disposable/goose-client/agents \
  --target goose
python scripts/install_adapters.py \
  --mode copy \
  --project-destination /absolute/disposable/goose-project \
  --skills-destination /absolute/disposable/goose-client/.agents/skills \
  --instructions-destination /absolute/disposable/goose-client/agents \
  --target goose
python scripts/install_adapters.py \
  --mode check \
  --project-destination /absolute/disposable/goose-project \
  --skills-destination /absolute/disposable/goose-client/.agents/skills \
  --instructions-destination /absolute/disposable/goose-client/agents \
  --target goose
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
`--live`; alternate files can be selected with `--conductor-token-file` and
`--worker-token-file`. These environment-variable and default file names are
the complete credential information documented here; never place either value
in a Goose recipe, settings file, command line, report, or repository file.

## Verification and reference

- [Architecture](docs/ARCHITECTURE.md)
- [Code standards](docs/CODE_STANDARDS.md)
- [Development](docs/DEVELOPMENT.md)
- [Review focus](docs/REVIEW_FOCUS.md)
- [Conformance guide](tests/conformance/README.md)
