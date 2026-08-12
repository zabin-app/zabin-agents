# Portable Agent Contracts - Code Standards

## Portable Prompt Contracts

- Write roles against repository-relative evidence and registered semantic capabilities such as filesystem inspection, git inspection, host dispatch, or an MCP call. The host adapter owns concrete tool spelling and qualification.
- Use provider-neutral capability tiers. Never put a provider, concrete model identifier, or client-specific dispatch command into a portable workflow.
- Declare the exact input and output object expected by a role. Reject undeclared top-level fields and return only the registered output fields.
- Separate authority, permissions, and failure behavior explicitly. A prompt must not infer mutation rights from tool availability or treat missing evidence as success.
- Keep prompts independent of home directories, checkout names, branch names, fixed task-file layouts, and host-specific artifact locations.
- Require evidence-backed outcomes. Never claim execution, inspection, or external state that the role did not observe.

**BAD:**

```text
Spawn a particular client subagent with a vendor model and call its qualified server tool.
```

**GOOD:**

```text
Dispatch the registered role at its capability tier, then invoke the canonical public operation through the host's MCP-call capability.
```

## Closed JSON Contracts

- Use JSON Schema Draft 2020-12 and a versioned schema identity for persisted or generated contracts.
- Set `additionalProperties: false` at every security- or workflow-significant object boundary. List required fields explicitly and constrain identifiers, enums, versions, digests, timestamps, and paths.
- Keep runtime validation aligned with schema validation. Enforce semantic invariants that JSON Schema cannot express, including canonical order, cross-field identity, safe path composition, and exact inventory parity.
- Evolve persisted formats through explicit version migrations. Unknown versions fail closed; retired fields leave structured tombstones when recovery meaning would otherwise be ambiguous.
- Serialize deterministically: stable key order, stable array order where order is not semantic, UTF-8, and one trailing newline.

**BAD:**

```python
if isinstance(payload, dict):
    return payload
```

**GOOD:**

```python
required = {"status", "summary"}
if set(payload) != required:
    raise ContractError("result has missing or unexpected fields")
```

## Python Idioms

- Support Python 3.11 or newer and use the standard library unless a reviewed contract explicitly adds a dependency.
- Use `pathlib.Path` for filesystem paths, `Mapping`/`Sequence` for read-only inputs, and concrete mutable collections for owned results.
- Prefer small pure validation, normalization, rendering, and redaction functions around typed immutable records (`dataclass(frozen=True, slots=True)`) for reports and planned operations.
- Accept injected environment mappings, transports, paths, clocks, and subprocess boundaries where tests need isolation. Do not reach into ambient state when a caller can supply it.
- Parse JSON and TOML as data structures. Never modify structured configuration with textual substitution outside the deliberately bounded template renderer.
- Use explicit encodings, bounded subprocess timeouts, exact argument arrays, and `check=False` when return codes are part of the reported contract.
- Canonicalize before hashing or comparing semantically equivalent structured values.

## Error Handling

- Define domain exceptions for safe caller-facing failures. Preserve the cause with `raise ... from exc` when it is useful and cannot disclose sensitive values; suppress the cause when library text may reflect a secret.
- Reject invalid, incomplete, ambiguous, or unsupported state before mutation. Errors identify the failed contract or credential name, never a credential value.
- Convert expected CLI failures into a concise `error:` diagnostic and a nonzero result. Reserve uncaught exceptions for programming defects.
- Distinguish failure from degraded or partial evidence. A required failure, skip, stale baseline, unscored result, or expected failure cannot be normalized into a pass.
- Treat MCP JSON-RPC error objects, HTTP failures, malformed results, identity mismatch, inventory drift, authentication rejection, timeout, and connection reset as typed failures. Never retry a mutating operation unless its contract proves the retry safe.

**BAD:**

```python
raise RuntimeError(f"request failed with token {token}: {error}")
```

**GOOD:**

```python
raise TransportError("worker authentication failed") from None
```

## Naming Conventions

| Element | Convention | Example |
| --- | --- | --- |
| Python modules and functions | lowercase `snake_case` | `recovery_checkpoint` |
| Classes and exceptions | `PascalCase`; errors end in `Error` | `InvalidCheckpointError` |
| Constants | uppercase `SNAKE_CASE` | `SCHEMA_VERSION` |
| Portable role and capability ids | lowercase semantic `snake_case` | `task_validator` |
| Public MCP tools | canonical unqualified `snake_case` | `get_task` |
| Server and client keys | lowercase kebab-case where required by native configuration | `zabin-worker` |
| Environment credentials | uppercase names that identify the surface, not the value | `ZABIN_MCP_WORKER_TOKEN` |
| JSON fields | lowercase `snake_case` | `failure_policy` |
| Schema versions | semantic versions; protocol revisions use their specified date form | `1.0.0` |

Names in portable prompts describe intent. Client qualification, executable names, concrete model ids, and transport bindings belong to adapters or locked conformance evidence.

## Atomic and Defensive File Handling

- Resolve all source and destination paths from an explicit trusted root. Reject absolute or traversal-bearing contract paths, unsafe symlinks, unexpected file kinds, and identity changes between inspection and replacement.
- Build and validate the complete output set in memory before writing. Stage sibling temporary files with restrictive modes, flush and sync content, replace atomically, and sync the containing directory when durability matters.
- For multi-file installation, recheck observed identities before every replacement, retain collision-safe backups, roll back the transaction on failure, and remove temporary/backup artifacts.
- Preserve unmanaged native configuration. Track only installer-owned components in the sidecar manifest and reject modified or missing owned components rather than guessing ownership.
- A dry run and a check must be side-effect free. Check mode reports drift; it never repairs it.

## Secret Handling

- Store credential names and bindings in policy; obtain values only at the runtime boundary that explicitly requires them. Never render literal bearer values into adapters, checkpoints, manifests, reports, argv, or persisted raw streams.
- Conductor and worker credentials are distinct. Test missing, empty, placeholder, swapped, and wrong-surface values as denial cases.
- Redact recursively by sensitive key and credential-bearing text, headers, URLs, and query parameters. Apply known-value replacement before pattern redaction and verify the serialized result contains no canary.
- Diagnostic output may report a credential's name, source, and availability. It must not print the value, a digest of the value, or exception text that may contain it.
- Run external tools with a closed environment when ambient preload, package, credential, or execution variables could alter the result.

## Anti-patterns

Avoid these repository-specific failure modes:

- copying canonical policy into templates, prompts, docs, or tests instead of deriving or fixture-checking it;
- accepting unknown JSON fields for forward compatibility;
- treating a loopback URL, process label, installed file, or model response as proof of server identity or user approval;
- enabling a partially conformant client adapter;
- hand-writing a looser recovery file or resolving checkpoint conflicts by last-write-wins;
- textual merges into native JSON/TOML, following unmanaged symlinks, or overwriting collisions;
- downloading dependencies during a locked conformance run;
- persisting raw subprocess streams and attempting redaction afterward;
- weakening a failed or skipped security check into a warning to obtain a passing aggregate.

## Testing Patterns

- Use dependency-free `unittest`, temporary directories, fixtures, and mocks for the default suite. Tests must not need network access, installed clients, credentials, or a writable home directory.
- Pair valid-contract tests with mutation tests for missing, extra, duplicate, empty, malformed, reordered, mismatched, and unsupported values.
- Compare generated artifacts byte-for-byte and parse them with native JSON/TOML readers. Prove deterministic output across input order and independent destinations.
- Exercise every mutation mode: clean install, unchanged repeat, drift check, unmanaged collision, modified owned component, rename/removal, rollback failure, symlink substitution, and check/use race.
- Use secret canaries and assert absence from artifacts, reports, errors, representations, and persisted files.
- For MCP boundaries, assert exact enumerated names and identities, one receipt for the allowed operation, zero receipts for forbidden and missing-secret attempts, separate surfaces, bounded timeout, and cleanup.
- Keep live tests opt-in and fail closed on absent prerequisites. A full conformance pass requires static, native-host, lifecycle, official protocol, identity, authorization, redaction, and cleanup evidence.

Commands for running these checks live only in [DEVELOPMENT.md](DEVELOPMENT.md).
