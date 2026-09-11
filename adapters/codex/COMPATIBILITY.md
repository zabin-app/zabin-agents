# Codex Native Role Compatibility

## Codex 0.154.0

Native role files are deserialized before their configuration is applied. An
`mcp_servers` entry containing only `enabled = false` fails with `invalid
transport`, and Codex ignores the entire role. Disabled entries still require a
valid transport definition.

The parent repository's `src/zabin-agent-tooling/src/render.rs` generates roles
from the canonical [role registry](../../config/agents.json),
[role documents](../../agents/), and [MCP policy](../../config/zabin-mcp.json).
It emits forbidden surfaces with `url = "http://disabled.invalid"` and
`enabled = false`. This reserved placeholder supplies the required HTTP transport
without binding a global role to an active deployment. All roles disable the
conductor surface. Roles without worker capability also disable the worker
surface; the implementor omits its worker entry so the project's endpoint,
credential reference, enabled state, and tool allowlist can be inherited.

## Verification boundary

An isolated native app-server probe on Codex 0.154.0 reproduced the malformed-role
warning with the transport-free entry. Adding the disabled placeholder URL
removed that warning and allowed configuration reads. A separate native
configuration probe applied a whole `mcp_servers` map override containing only
the disabled conductor entry: the omitted worker endpoint and tool allowlist
survived. Both probe servers remained disabled; no model turn or MCP call ran.

The map-merge probe verifies general configuration layering, not AgentControl's
actual role-dispatch path. Worker inheritance during role dispatch therefore
remains an inference, not a separately observed runtime guarantee.

The parent crate's render tests cover generated role transports and include an
ignored native-parser regression requiring `ZABIN_TEST_CODEX`. See
[Development](../../docs/DEVELOPMENT.md) for verification commands. Upstream
references: [subagent configuration](https://learn.chatgpt.com/docs/agent-configuration/subagents)
and [MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
