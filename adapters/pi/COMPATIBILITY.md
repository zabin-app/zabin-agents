# PI MCP adapter compatibility

**Status: unsupported (fail closed).** Audited on 2026-08-12 against PI 0.84.1 and
`pi-mcp-adapter` 2.22.0. `settings.json.template` intentionally contains no
packages. Do not advertise PI as a supported Zabin client and do not turn the
candidate package on by editing that template.

PI deliberately ships without native MCP or native permission prompts. Its
official package documentation also warns that extensions execute arbitrary
code with full system access. A third-party extension therefore has to enforce
Zabin's identity, naming, registration, approval, and secret rules itself,
below model choice. The reviewed candidate enforces part of that contract, but
not all of it.

## Audited artifacts

| Component | Immutable evidence | License |
| --- | --- | --- |
| PI | `@earendil-works/pi-coding-agent@0.84.1`; commit `53fa77ccd8a279eb87e92294ef3687b03ff80112`; registry integrity `sha512-ncAqFrG+iybuPGOhMiZoEHkEzTpJgz3guYD32pD+M7ucc0WeHmauP6wa7qwP8V/KWvsZDVNa5XGsdZ7fkC7w7A==`; Linux x64 release SHA-256 `5634d7ebd18274b63af3371e942f342d74bea012389575c1d1ff15ce6ca80c2f` | MIT |
| Candidate extension | `pi-mcp-adapter@2.22.0`; commit `852a12fa27b42c53d1d455c5937b9101d71af48a`; annotated tag object `aeea26ed7a34bd37cdfedb1259df8f2e11681b71` (unsigned); registry integrity `sha512-59rFNbQ5OBqeDgQhymJtOU9E7pOJ1amh3FAhFdo0bAbo/v2SUWIBeb6gmJpeOBlCHJwgFw/RZSaA9++FKeX4Rw==`; tarball SHA-256 `4c33fe9d2d94b7cedaa34c3f10c9cb9295a1a81e7114921e881a937f7ad85d76` | MIT |

`extension-lock.json` records all 56 resolved package entries, including
platform-optional packages, exact versions, registry URLs, SHA-512 integrity
values, dependency edges, and licenses. The resolved licenses are MIT, ISC,
BSD-3-Clause, and 0BSD. Resolution used the exact PI install command with Node
24.19.0 and npm 11.17.0; none of the resolved entries declares an install
script. The extension does not publish a shrinkwrap, so a PI
first-run install of the exact top-level version can still re-resolve its
semver-ranged transitive dependencies; the repository lock is audit evidence,
not an enforcement hook consumed by PI.

Reviewed source tree: the complete npm tarball (67 files), with focused review
of `index.ts`, `types.ts`, `direct-tools.ts`, `proxy-modes.ts`,
`server-manager.ts`, `metadata-cache.ts`, `tool-metadata.ts`, `ui-server.ts`,
`mcp-code.ts`, `mcp-script-worker.mjs`, `mcp-trace.ts`, `config.ts`, and the
OAuth/configuration modules.

## Policy audit

| Requirement | Evidence and decision |
| --- | --- |
| Streamable HTTP | The candidate constructs `StreamableHTTPClientTransport` first and only falls back to legacy SSE for specific endpoint-incompatibility responses. The isolated proof completed initialize, `tools/list`, and `tools/call` over Streamable HTTP. |
| Protocol negotiation | `protocolVersion: "legacy"` uses the classic initialize path compatible with Zabin's pinned `2025-11-25` revision. `auto` adds a 2026 probe/fallback path and is not acceptable for this policy. The candidate does not independently assert that the returned revision and identity equal Zabin's canonical policy. |
| Header secrets and redaction | Header values support `${ENV_NAME}` interpolation at connection time and the proof observed the expected Authorization header without printing its value. Metadata-only tracing redacts authentication-like text, but trace/debug must remain off. Missing variables in header values interpolate to an empty string rather than failing before the request, unlike missing variables in URLs. Server-side authentication is therefore still needed to fail closed. |
| Server identity | **Blocking.** Configuration binds only a URL/server label. The candidate accepts the connected server's `serverInfo` and has no configuration for expected service name, surface, version, or inventory fingerprint. A different loopback process can impersonate the configured endpoint and receive the bearer header before Zabin identity is established. |
| Canonical names | `toolPrefix: "none"` preserves canonical names (dots normalize to underscores). **Blocking for the full policy:** conductor and worker expose many identical canonical names, and the candidate skips duplicate direct registrations. Loading both surfaces in one PI process either loses one surface or requires client-visible qualification, which the canonical policy forbids. |
| Pre-registration allowlist | `directTools` plus `includeTools` filters cached/live metadata before individual tool registration; `excludeTools` is applied afterward. The normal proxy list/search/describe/call paths use the filtered metadata. The isolated dispatcher proof confirmed a forbidden tool was absent and rejected before transport. |
| Alternate dispatch paths | **Blocking.** `ui-server.ts` handles an MCP App `/proxy/tools/call` against the connection's raw advertised tools and UI visibility, without applying `includeTools`/`excludeTools`. Current Zabin tools do not advertise MCP App UI metadata, but the adapter policy is not structurally complete across every dispatch origin. Disabling the viewer is operational mitigation, not a proof that the call path cannot be reached. |
| Approvals | `approveTools` gates proxy, direct, script, resource, and iframe calls before the ordinary transport call; headless approval-required calls fail closed. Exact patterns could approximate conductor prompts while worker calls remain scope-granted, but this does not repair identity, collision, or UI-filter gaps. |
| Failure behavior | Unknown active tool names are rejected by PI's registered-tool dispatcher. Disabled servers do not connect. Authentication, cancellation, timeout, and server errors do not trigger the Streamable-HTTP-to-SSE compatibility fallback. Reconnect/list-change behavior can mutate registrations unless `freezeDirectTools` is set. |
| Updates and integrity | PI skips an exact top-level npm package during package updates, but does not consume this repository's custom dependency lock. The unsigned upstream Git tag and ranged transitives require an external artifact-verification/install step that the native settings template cannot enforce. |
| Sandbox and arbitrary code | **Blocking.** PI packages execute TypeScript with the PI process's host permissions. PI provides no built-in sandbox boundary. The candidate also registers `mcpScript` by default, which evaluates supplied JavaScript in a worker; `scriptMode: false` removes that tool but cannot sandbox the extension itself. An external container/OS sandbox is still required. |

## Isolated denial proof

The proof used the exact PI 0.84.1 Linux x64 release asset, the exact
`pi-mcp-adapter` 2.22.0 npm artifact, and the resolved dependency set captured
in the lock. A loopback-only MCP server advertised `get_task` and forbidden
`delete_attachment`, validated the Authorization header without persisting its
value, and counted received calls. Candidate configuration used canonical
names, `directTools: ["get_task"]`, `includeTools: ["get_task"]`,
`exposeResources: false`, `scriptMode: false`, `disableProxyTool: true`,
`freezeDirectTools: true`, and the legacy protocol path.

PI enumerated these active tools:

```text
bash edit get_task read write
```

`delete_attachment` was absent from the active registered dispatcher. A direct
dispatcher attempt returned `registered tool not found: delete_attachment`.
The allowed `get_task` call reached the server once. Final server counters were:

```json
{
  "allowed_receipts": 1,
  "authorization_header_valid": true,
  "forbidden_receipts": 0,
  "initialize": 1,
  "list_tools": 1
}
```

This proves the ordinary direct-tool allowlist for the pinned pair; it does not
overrule the blocking findings above. Notably, PI 0.84.1 retained the proxy
tool in its all-tools registry after startup-cache warmup but removed it from
the active dispatcher. The denial attempt traversed the active dispatcher, not
an LLM decision.

## Re-evaluation requirements

Support can be reconsidered only after a pinned PI/extension pair demonstrates
all of the following in a new isolated proof:

1. expected `serverInfo` and protocol/inventory identity are checked before any
   credential-bearing post-initialize operation;
2. canonical conductor and worker names are complete without collisions or
   client-visible qualification (separate, enforced process profiles are
   acceptable only if configuration makes cross-surface loading impossible);
3. one allowlist guard covers direct, proxy, script, resource, MCP App/UI, and
   reconnect/list-change paths before dispatch;
4. the exact transitive lock is enforced during installation and update, not
   merely documented;
5. extension execution is placed inside an enforceable host sandbox; and
6. registered-tool enumeration plus a direct forbidden call again leaves the
   server receipt counter at zero.

## Primary sources

- [PI project and native feature boundary](https://pi.dev/)
- [PI 0.84.1 release](https://github.com/earendil-works/pi/releases/tag/v0.84.1)
- [PI 0.84.1 extension API](https://github.com/earendil-works/pi/blob/v0.84.1/packages/coding-agent/docs/extensions.md)
- [PI 0.84.1 package security, pins, updates, and dependency behavior](https://github.com/earendil-works/pi/blob/v0.84.1/packages/coding-agent/docs/packages.md)
- [Candidate extension at the audited commit](https://github.com/nicobailon/pi-mcp-adapter/tree/852a12fa27b42c53d1d455c5937b9101d71af48a)
- [Candidate npm metadata](https://registry.npmjs.org/pi-mcp-adapter/2.22.0)
- [MCP 2025-11-25 Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- [MCP 2025-11-25 lifecycle and version negotiation](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
