# Zabin MCP conformance

This suite is deliberately fail closed. Static assessment is the default; live
MCP probes, the official conformance run, native-host observation, and lifecycle
evidence are separate required checks for a full-pass claim. A required expected
failure, unscored check, skipped check, stale baseline, missing binary, missing
digest, or missing evidence makes the overall result `fail`.

Conformance is run by `zabctl agents conformance`, implemented in the zabin
repository's `zabin-agent-tooling` crate. This directory is the evidence policy
the command enforces; it is no longer executed by an interpreter of its own.

```sh
zabctl agents conformance --help
```

## Pinned boundary

`zabctl agents conformance` reads the bundle's runner lock (schema version
`2.0.0`) as the sole invocation lock. Alternate paths and symlink substitution
are rejected, and a code-owned digest binds the complete lock contents so a
well-formed edit cannot silently replace any security pin. Because orchestration
now lives in the Rust command rather than an interpreted script, the lock
records `retired_runtimes: ["python"]`: Python is no longer a runtime, so no
interpreter version is pinned. Every genuine pin the boundary depends on is
preserved:

- the official `modelcontextprotocol/conformance` action/package version and
  immutable Git commit digest;
- the exact locked Node runtime the official conformance artifact runs under;
- installed Claude Code and Codex versions and exact noninteractive argv;
- the exact Goose 1.45.0 compatibility-lock and observed-binary digests, its
  explicit binary-path input, and disposable `GOOSE_PATH_ROOT` boundary;
- PI as unsupported, linked to the audited extension lock;
- exact canonical endpoints, build/protocol identity, inventory counts, and
  SHA-256 inventory fingerprints;
- the only accepted official server arguments:
  `server --url {url} --requirements 2025-11-25`.

The command downloads nothing. Before a live launch, supply paths to an already
installed official artifact, its transitive lock, and the staged dependency
tarballs through the environment:

```sh
export ZABIN_CONFORMANCE_ARTIFACT=/absolute/path/to/conformance/dist/index.js
export ZABIN_CONFORMANCE_TRANSITIVE_LOCK=/absolute/path/to/package-lock.json
export ZABIN_CONFORMANCE_TRANSITIVE_ARTIFACT_MANIFEST=/absolute/path/to/artifacts.json
```

The environment supplies paths only. The expected artifact and transitive-lock
SHA-256 values live in the runner lock beside the immutable official tag and
commit anchor. Supplying a digest through the environment cannot alter trust.

The artifact manifest is `{"schema_version":"1.0.0","artifacts":[...]}`.
Each record supplies the exact `package_path`, `integrity`, and local `artifact`
tarball for one registry entry in `package-lock.json`. The command requires an
exact record set and recomputes every `sha512-...` integrity value; checking only
the lockfile digest is not treated as dependency verification. Every non-root
dependency must resolve through `https://registry.npmjs.org/` and carry an exact
version and SHA-512 integrity; unresolved, local, Git, or integrity-free entries
fail rather than disappearing from the verification set.

Startup compares every pinned version, digest, command, argument, Goose/PI
compatibility lock, server identity, and policy fingerprint. Goose is required:
`GOOSE_NATIVE_BINARY` must name the exact absolute, non-symlink executable in
the lock, and its version probe runs with an isolated temporary
`GOOSE_PATH_ROOT`. Its missing official release-artifact proof is a required
failure, so local version and binary observations cannot create support. An
unverified artifact is a failure, not a skipped prerequisite. The current
repository host has Claude Code 2.1.220 and Codex CLI 0.147.0, but no `node`,
`npm`, or `pi`; therefore it cannot honestly produce a full native/live
conformance pass until the exact pinned Node runtime and verified official
artifact are provisioned.

Node is resolved exactly once and must be the locked absolute, non-symlink,
regular executable. That same absolute path is retained for both official
launches. Node version probes and official processes receive a closed child
environment containing only an isolated `HOME`/`TMPDIR`, the code-owned safe
`PATH`, and explicitly allowlisted locale/timezone values. Ambient
`NODE_OPTIONS`, `NODE_PATH`, preload, npm configuration, credentials, and
unrelated variables are never inherited.

## Unit tests (default)

Unit-level coverage lives in the `zabin-agent-tooling` crate's Rust tests:

```sh
cargo test -p zabin-agent-tooling
```

These tests use in-crate fixtures and mocks. They cover strict startup and
policy parity; exact host commands and configuration source; separate trust,
approval, activation, and connectivity states; raw/qualified tool names; allowed
and forbidden receipts; pre-launch missing-secret failure; redaction canaries;
restricted artifacts; lifecycle ordering and allowlisting; checkpoint
reconciliation; stale baselines; cleanup; and required pass/fail/skip behavior.
Goose cases additionally close both qualified inventories, hidden/direct
forbidden calls with zero server receipts, missing and swapped credentials,
pre-credential identity/inventory/redirect drift, approve mode, mutually
exclusive permissions, empty default extensions, `AGENTS.md` and Agent Skills
discovery markers, bounded timeout/cancellation, redaction, and cleanup.

## Static assessment (default mode)

```sh
zabctl agents conformance --contracts-root /absolute/path/to/.agents
```

The default `--mode static` performs no network activity and launches no native
host. It assesses the runner lock, policy parity, artifact integrity, and any
supplied evidence documents offline. With `--report-path`, it writes only a
redacted mode-`0600` JSON report to the given path; raw stdout/stderr is never
written to disk. Missing native-host and lifecycle evidence is reported as
required `skip`, so this mode normally exits nonzero outside a prepared
conformance environment.

```sh
zabctl agents conformance \
  --contracts-root /absolute/path/to/.agents \
  --report-path /restricted/conformance-report.json
```

## Native-host observer reports

Claude Code, Codex, and Goose must be tested separately by a deterministic
observer, not by asking a model whether setup worked. Supply each redacted
report through the environment; the runner reads the paths the lock names:

```sh
export ZABIN_CONFORMANCE_CLAUDE_CODE_REPORT=/restricted/claude-report.json
export ZABIN_CONFORMANCE_CODEX_REPORT=/restricted/codex-report.json
export ZABIN_CONFORMANCE_GOOSE_REPORT=/restricted/goose-report.json
```

Each report must prove the installed configuration source, user/project trust
evidence, server approval, activation, connected build identity, exact
enumerated names, one receipt for a direct allowed call, zero receipts for a
forbidden call, and zero enumeration or invocation when the secret is absent. It
must also report complete cleanup and that no raw streams were persisted.

The Goose observer must run the pinned native executable
(`GOOSE_NATIVE_BINARY`) only with an explicit disposable `GOOSE_PATH_ROOT` and
instrumented loopback conductor/worker fixtures. Its report (format
`zabin-conformance/goose-external-report-v1`) has a separate closed surface
record for every identity, qualified inventory, allowed/forbidden receipt,
auth-denial, and drift case. Both shared-context discovery markers,
permission/no-default state, timeout/cancellation, cleanup, and redaction are
independently scored. Even a complete observer report cannot pass while the
compatibility lock remains `unsupported`; skipped observation, a missing binary
or artifact, or partial evidence is also a required failure.

Claude's interactive workspace-trust prompt is a separate check. Claude Code
documents that `--print` skips that dialog, so headless activation is never used
as evidence of user approval. The lock currently marks interactive trust as not
automatable; the report is `skip`/untested rather than a fabricated native-host
pass.

PI is likewise not a native-host pass. The audited PI 0.84.1 and
`pi-mcp-adapter` 2.22.0 pair remains unsupported by repository policy.

## Lifecycle evidence and production guard

Lifecycle coverage must use a disposable project. A non-disposable project is
rejected unless its exact id is supplied via both deliberate evidence and an
explicit allowlist. Both are provided through the environment:

```sh
export ZABIN_CONFORMANCE_LIFECYCLE_EVIDENCE=/restricted/disposable-lifecycle.json

# A reviewed non-disposable project additionally needs its exact id allowlisted:
export ZABIN_CONFORMANCE_LIFECYCLE_EVIDENCE=/restricted/approved-production-observation.json
export ZABIN_CONFORMANCE_PROJECT_ALLOWLIST=prj_exactly_reviewed
```

`ZABIN_CONFORMANCE_PROJECT_ALLOWLIST` may hold a comma-separated allowlist for
controlled automation. Evidence must cover project scoping, incremental plan
construction, human approval observation, overlap computation, sized worker
lease, `in_review`, verdict, `validated`, wave gates, completion, release, and
checkpoint reconciliation. Every stage needs an authoritative reference. A
checkpoint conflict or an absent/unscored/skipped stage fails. The evidence
object and each stage use closed schemas; stages must appear exactly once in the
locked order, with release preceding the terminal checkpoint outcome
(`consistent` or `zabin_only`). Duplicates, reordering, and extra fields fail.

## Opt-in live probes

`--mode live` is an explicit opt-in to launching client processes. It performs
read-only canonical probes against conductor `127.0.0.1:50052/mcp` and worker
`127.0.0.1:50053/mcp-worker`, and it requires all startup, host, lifecycle,
artifact, and transitive-lock checks to pass before it launches any client or
the official runner:

```sh
export ZABIN_CONFORMANCE_ARTIFACT=/absolute/path/to/conformance/dist/index.js
export ZABIN_CONFORMANCE_TRANSITIVE_LOCK=/absolute/path/to/package-lock.json
export ZABIN_CONFORMANCE_TRANSITIVE_ARTIFACT_MANIFEST=/absolute/path/to/artifacts.json
export ZABIN_CONFORMANCE_CLAUDE_CODE_REPORT=/restricted/claude-report.json
export ZABIN_CONFORMANCE_CODEX_REPORT=/restricted/codex-report.json
export ZABIN_CONFORMANCE_GOOSE_REPORT=/restricted/goose-report.json
export ZABIN_CONFORMANCE_LIFECYCLE_EVIDENCE=/restricted/disposable-lifecycle.json

zabctl agents conformance --mode live \
  --contracts-root /absolute/path/to/.agents \
  --report-path /restricted/conformance-report.json
```

Readiness and every subprocess have bounded timeouts. Temporary official results
use distinct disposable conductor and worker directories, cleanup is reported,
and only redacted summaries are persisted. Each surface must independently emit
exactly one closed-schema `checks.json`; unknown fields/statuses, inconsistent
nested summaries, skipped/unscored/expected-failure counts, or one surface's
output standing in for the other all fail. Credential environment variables are
removed from the official runner's child environment; synthetic canaries detect
reflection. Identity and readiness must both pass before either official runner
is launched. Never point the lifecycle portion at a production project merely
to make a test pass.
