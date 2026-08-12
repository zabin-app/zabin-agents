# Goose MCP adapter compatibility

**Status: unsupported (fail closed).** Audited on 2026-08-12 against Goose
1.45.0. This directory intentionally contains no active settings or recipe
template. Do not advertise Goose as a supported Zabin client and do not place
either bearer value in Goose configuration.

Goose is a strong structural match for this repository: it speaks Streamable
HTTP MCP, qualifies remote tools by extension, filters tools with
`available_tools`, reads canonical `AGENTS.md`, and discovers Agent Skills from
`.agents/skills`. Those capabilities are necessary, but they do not close the
credential and trust boundary required by the two authenticated Zabin surfaces.

## Pinned audit

The audit pins official release tag `v1.45.0` and all reviewed source to its
exact commit `4dc0420f5704a92806c6628c8f0a3497d7a88759`. SHA-256 digests for the six
relevant release blobs are recorded in `client-lock.json`; no later branch
source is used. The locally installed Linux x86-64
executable reported `1.45.0` and hashed to
`9ef3ae45d819e41d1b7bcb1533033765d1e1876aba4a35ff0f6e722337512b3b`.
That hash is an observation, not official release-artifact proof; no supported
decision may derive from it without matching immutable upstream integrity.

The machine-readable decision is [client-lock.json](client-lock.json). It pins
the exact Goose semantics and the current conductor/worker inventory counts and
fingerprints without storing URLs containing credentials or bearer values.

## What works

| Requirement | Evidence and decision |
| --- | --- |
| Streamable HTTP | Native `streamable_http` extensions are documented and implemented. Legacy SSE is not required. |
| Dual-surface names | Remote tools are qualified as `<normalized-extension>__<server-tool>`. `zabin-conductor` and `zabin-worker` normalize to distinct keys, so their overlapping public names can coexist. |
| Tool filtering | `available_tools` filters enumeration and is checked again immediately before dispatch. The empty-list meaning is **allow all**, so an adapter must require exact non-empty lists. |
| Shared instructions | Goose reads hierarchical `AGENTS.md` and discovers global/project `.agents/skills`; no Goose-specific instruction fork is needed. |
| Isolated profile | `GOOSE_PATH_ROOT` isolates config, data, and state. A native loopback run proves that a recipe with an explicit extension replaces a configured profile extension and exposes only its allowlisted tool. |
| Per-tool choices | Qualified tools can be Always Allow, Ask Before, or Never Allow in manual/smart modes. These are useful controls, but not an immutable policy boundary. |

## Blocking findings

### Credential release precedes identity

**Blocking.** For Streamable HTTP, Goose resolves secrets into the URI and
headers, creates the authenticated client, and sends MCP `initialize`. Only
afterward does it retain the returned `serverInfo`. No pinned check compares the
expected service, logical surface, protocol, or inventory before the bearer
header reaches the listener. A different local process that acquires the port
can therefore receive a static credential before it is identified. The native
loopback regression observes the bearer on the first `initialize`, before the
hostile fixture returns its `serverInfo`; this is direct evidence of the block.

### Header indirection is not a stable generated-config contract

**Blocking.** The native regression proves `${ENV}` header indirection for the
pinned client: with the probe variable present the recorder receives the
expanded header, while an absent variable prevents every MCP request and Goose
continues without the extension. The expanded probe is absent from ordinary
files under the temporary root. This behavior is fail open at the workflow
level—Goose proceeds without the authenticated surface—so it cannot support
Zabin without a separate startup gate. The repository must never persist either
real bearer value merely to make Goose connect.

### Approval state is mutable and autonomous by default

**Blocking.** Goose defaults to `auto`, which permits tool calls without the
manual permission path. Runtime permission files are user-managed/auto-managed,
not a documented administrator-locked schema. The digest-pinned release source
checks `always_allow`, `ask_before`, then `never_allow`. Both a source-parity
conflict regression and a native `approve`-mode run put the same qualified tool
in all three lists; the native model request invokes it without a prompt. Thus
an inconsistent file resolves to allow, not deny, and cannot prove immutable
conductor human gates or the worker scope boundary.

### Hooks do not provide a fail-closed enforcement boundary

**Blocking.** Goose hooks can explicitly block selected tool calls, but hook
failures and timeouts are logged and execution continues. `SessionStart` is an
observation hook rather than a blocking identity/credential gate. Hooks may add
defense in depth, but cannot authorize startup or enforce the mandatory Zabin
approval boundary.

### Trust and containment are incomplete

**Blocking.** Desktop recipe warnings are not a mandatory CLI/headless trust
contract, and no comparable workspace trust gate is documented. MCP server
instructions enter agent context. Native Developer and stdio extensions run
with the Goose process's host authority; MCP roots are advisory rather than a
filesystem sandbox.

### Integrity, cleanup, and drift evidence are incomplete

**Blocking.** The local binary hash has not been matched to an official
platform asset. The native regression observes that ordinary runs create
session, project, and log artifacts, then removes its exact temporary
`GOOSE_PATH_ROOT` and recorder and proves no expanded bearer residue remains.
No MCP delete operation is emitted. This test cleanup is not an active adapter
uninstall contract, so transactional install, rollback, removal, and
source/target/policy/version/inventory drift must still be implemented before
any later activation decision.

## Executable gate

`tests/test_goose_compatibility.py` closes the decision format and checks:

- exact release/source revision, blob digests, and optional native-binary hash;
- current canonical 52-tool conductor and 17-tool worker fingerprints;
- exact hyphen-preserving normalized identities and qualified collision isolation;
- non-empty allowlists, hidden-tool non-enumeration, and pre-dispatch rejection;
- environment-variable names only, with no token-shaped or literal bearer data;
- digest-pinned permission conflict precedence (`always_allow` wins);
- optional, fully loopback native runs proving missing-secret extension failure
  is fail open overall, credential release precedes hostile `serverInfo`, the
  explicit recipe replaces the profile/default set, allowlisting hides the
  forbidden tool, conflicting permissions allow the tool call, and exact-root
  cleanup leaves no expanded bearer residue;
- identity-before-credential, permission exclusivity, trust, sandbox,
  hook-enforcement, active cleanup, and artifact-integrity gates prevent support;
- the absence of active Goose settings and recipe templates.

Run the repository-only gate with:

```sh
python -m unittest tests.test_goose_compatibility
```

To additionally run the bounded native regressions, provide the executable path
explicitly. Both MCP and OpenAI-compatible endpoints are in-process loopback
fixtures; each run uses a temporary `GOOSE_PATH_ROOT`, has a process timeout,
and neither reads nor mutates production Goose state:

```sh
GOOSE_NATIVE_BINARY=/absolute/path/to/goose \
  python -m unittest tests.test_goose_compatibility
```

The optional native evidence cannot turn the support status to pass. Goose
still exposes the static credential before identity and fails open when the
secret or extension is unavailable.

## Re-evaluation boundary

Native support may be reconsidered only when a pinned client demonstrates all
of the following together:

1. official platform artifact integrity;
2. secret indirection, missing-secret containment, and complete redaction;
3. expected surface/protocol/inventory authentication before credential
   release or exchange;
4. exact non-empty allowlists, collision isolation, direct forbidden-call
   rejection, and zero forbidden server receipts;
5. approve mode and mutually exclusive tool permissions enforced below mutable
   user configuration;
6. startup and authorization enforcement that denies on failure or timeout
   instead of depending on Goose hooks;
7. mandatory recipe/workspace trust plus process and filesystem containment;
8. transactional install, cleanup, rollback, and comprehensive drift checks.

An external authenticated gateway can be evaluated separately if it pins the
upstream surface, rejects redirects and inventory drift, enforces allowlists,
and withholds or exchanges the upstream credential inside that boundary. Until
that entire path passes conformance, Goose remains unsupported and inactive.

## Primary sources

- [Configuration files](https://goose-docs.ai/docs/guides/config-files/)
- [Permission modes](https://goose-docs.ai/docs/guides/goose-permissions/)
- [Tool permissions](https://goose-docs.ai/docs/guides/managing-tools/tool-permissions/)
- [Recipe reference](https://goose-docs.ai/docs/guides/recipes/recipe-reference/)
- [Hooks](https://goose-docs.ai/docs/guides/context-engineering/hooks/)
- [AGENTS.md and hints](https://goose-docs.ai/docs/guides/context-engineering/using-goosehints/)
- [Agent Skills](https://goose-docs.ai/docs/guides/context-engineering/using-skills/)
- [Goose 1.45.0 release](https://github.com/aaif-goose/goose/releases/tag/v1.45.0)
- [Pinned extension manager source](https://github.com/aaif-goose/goose/blob/4dc0420f5704a92806c6628c8f0a3497d7a88759/crates/goose/src/agents/extension_manager.rs)
- [Pinned MCP client source](https://github.com/aaif-goose/goose/blob/4dc0420f5704a92806c6628c8f0a3497d7a88759/crates/goose/src/agents/mcp_client.rs)
- [Pinned extension configuration source](https://github.com/aaif-goose/goose/blob/4dc0420f5704a92806c6628c8f0a3497d7a88759/crates/goose/src/config/extensions.rs)
- [Pinned permission source](https://github.com/aaif-goose/goose/blob/4dc0420f5704a92806c6628c8f0a3497d7a88759/crates/goose/src/config/permission.rs)
- [Pinned recipe extension adapter](https://github.com/aaif-goose/goose/blob/4dc0420f5704a92806c6628c8f0a3497d7a88759/crates/goose/src/recipe/recipe_extension_adapter.rs)
