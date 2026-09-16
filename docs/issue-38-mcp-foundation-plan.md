# Issue #38 — MCP foundation implementation plan

This document scopes the first implementation step for issue #38: establish a reusable, read-only MCP foundation in `gway-web` on top of the generic HTTP/discovery work from issue #31.

## Goal

Provide a small MCP adapter that can expose only explicitly agent-approved GWay Web commands as typed MCP tools over Streamable HTTP, without adding logs-specific behavior yet.

The result of this step should be usable as the shared foundation for the later `logs.arthexis.com` and `repo.arthexis.com` integrations.

## Architectural decisions

- Use MCP as the agent-facing protocol. ChatGPT Apps are built on MCP, and the current MCP Python SDK supports Python 3.10+ and Streamable HTTP, matching this project's runtime.
- Reuse the existing `gway-web` API policy, discovery, dispatch, routing, and service layers. Do not create a parallel command execution path.
- Keep MCP exposure stricter than HTTP exposure. A command being available to the CLI or generic HTTP API does not make it MCP-visible.
- V1 is read-only. No mutation, shell execution, arbitrary chain execution, sigil expansion, arbitrary Python functions, or filesystem access.
- Authentication hooks belong at the MCP boundary, but full user OAuth is a later step. This foundation should make authorization injectable/testable without prematurely implementing the final reader identity flow.
- Prefer structured MCP tool results and structured protocol errors. Do not leak Python tracebacks to remote clients.
- Use bounded request/result handling from the start so later log/event tools cannot accidentally become unbounded data channels.

## Proposed module boundary

The exact names may move slightly during implementation, but the intended split is:

- `mcp_config.py`
  - MCP enablement and explicit MCP allowlist policy.
  - read-only defaults and response bounds.
- `mcp_schema.py`
  - transforms already-exposed GWay command metadata into MCP tool names/descriptions/input schemas.
  - contains no transport or execution logic.
- `mcp_dispatch.py`
  - validates MCP visibility, invokes the existing API dispatcher/service path, normalizes results/errors.
- `mcp_server.py`
  - creates the MCP server and Streamable HTTP application/endpoint.
  - thin protocol adapter only.

The adapter should depend inward on the existing API abstractions rather than importing project-specific commands directly.

## Exposure model

The intended hierarchy is:

```text
GWay CLI callable
    └── explicitly HTTP exposed by gway-web
            └── explicitly MCP exposed by gway-web
```

MCP configuration must never widen the canonical HTTP exposure policy. Aliases must resolve to the canonical project before policy evaluation.

## Tool naming

Generate deterministic names from canonical project + command path, with normalization suitable for MCP tool identifiers. The implementation must detect collisions rather than silently overwrite a tool.

Examples are conceptual only:

```text
repo/context      -> repo_context
repo/impact       -> repo_impact
logs/list_runs    -> logs_list_runs
```

Descriptions and parameter metadata should be derived from the same command discovery metadata already used by `/_gway` wherever possible.

## Planned commits

### Commit 1 — `docs: define read-only MCP adapter contract`

Purpose: lock down the boundary before adding dependencies or runtime code.

Changes:

- add this implementation plan;
- document MCP-vs-HTTP exposure semantics;
- document read-only/non-goals and error/size expectations;
- record the dependency direction: MCP -> existing GWay Web API abstractions -> GWay core.

Acceptance:

- no runtime behavior changes;
- plan clearly identifies what belongs in this PR and what is deferred.

### Commit 2 — `build: add MCP server dependency`

Purpose: add the protocol implementation without coupling it to the rest of the package yet.

Changes:

- add the current stable `mcp` Python SDK with an explicit compatible version range;
- keep Python >=3.10 compatibility;
- add any test-only dependency needed for in-memory/HTTP MCP client tests;
- verify existing test/lint configuration remains unchanged unless required.

Acceptance:

- package installs on the supported Python range;
- existing tests still pass before MCP code is introduced.

### Commit 3 — `feat: add MCP exposure policy and schema generation`

Purpose: create the pure/read-only metadata layer.

Changes:

- add MCP config/policy types with deny-by-default behavior;
- require a command to pass both HTTP exposure and MCP exposure checks;
- transform canonical discovery metadata into deterministic MCP tool definitions;
- preserve required/optional parameters, scalar types, safe defaults, descriptions, and boolean semantics where representable;
- reject unsupported/unsafe parameter shapes explicitly;
- detect duplicate normalized tool names;
- add unit tests for allowlisting, aliases, type/schema conversion, unsupported metadata, and collisions.

Acceptance:

- schema generation performs no command execution;
- no MCP-visible tool can exist without matching HTTP exposure;
- tool list ordering is deterministic.

### Commit 4 — `feat: route MCP tools through existing API dispatch`

Purpose: execute MCP calls without creating a second GWay execution mechanism.

Changes:

- add a small MCP dispatcher/adapter that maps a tool invocation back to canonical project/command metadata;
- validate visibility before execution;
- call the existing `gway-web` dispatch/service layer;
- normalize successful results into structured MCP content;
- translate known API errors into stable MCP-safe errors;
- suppress traceback/internal exception details from remote responses;
- enforce initial request/result bounds;
- add tests proving MCP invocation and direct HTTP/API dispatch use the same underlying callable path.

Acceptance:

- no direct shell/Python/arbitrary-chain execution path is introduced;
- a denied or unknown tool cannot reach the dispatcher;
- internal exceptions are logged/test-visible locally but not returned as remote traceback text.

### Commit 5 — `feat: serve read-only tools over MCP Streamable HTTP`

Purpose: provide the actual remote MCP endpoint ChatGPT can connect to later.

Changes:

- create the MCP server factory;
- register generated tools from policy/discovery;
- expose Streamable HTTP through the existing `gway-web` HTTP/service composition rather than a separate deployment stack;
- add a narrow authorization hook/context interface, initially supporting test/dev identities without implementing final OAuth;
- expose minimal server identity/version metadata;
- add MCP protocol tests using the official SDK client/in-memory facilities where practical.

Acceptance:

- MCP initialize/list-tools/call-tool works end to end in tests;
- denied commands are absent from `tools/list`;
- the transport can be mounted behind the existing Nginx/TLS exposure machinery;
- all exposed tools remain read-only.

### Commit 6 — `test: add MCP foundation contract coverage`

Purpose: harden the reusable boundary before logs-specific work begins.

Changes:

- add end-to-end contract tests for discovery -> MCP schema -> invocation -> structured result;
- test unauthenticated/unauthorized hook behavior;
- test malformed arguments and bounded output behavior;
- test alias/canonical-project exposure invariants;
- test traceback suppression;
- run the full repository suite and lint checks;
- update `docs/api.md`/README with the new MCP endpoint and extension points.

Acceptance:

- existing HTTP API behavior remains backward compatible;
- full test suite passes;
- documentation explains how a future service opts individual read-only commands into MCP.

## Deferred to the next steps

The following are intentionally not part of the MCP foundation PR:

- `logs.arthexis.com` run/event models;
- `list_runs`, `get_run`, `get_events` implementations;
- GitHub Actions writer OIDC;
- final ChatGPT reader OAuth/OIDC account linking and refresh tokens;
- repo-specific tools;
- public app-directory publication;
- mutation/approval flows;
- UI components/resources for a rich ChatGPT App experience.

## Verification sequence

Before opening the implementation PR as ready for review:

1. install from a clean environment using the project's supported Python version range;
2. run the existing test suite before and after MCP changes;
3. run Ruff;
4. run MCP unit/contract tests;
5. start the MCP endpoint locally and validate initialize, tools/list, and one synthetic read-only call;
6. confirm an HTTP-exposed-but-not-MCP-exposed command is invisible to MCP;
7. confirm aliases cannot widen canonical policy;
8. confirm an unexpected exception does not expose a traceback to the MCP client.

## Exit condition for this step

The first step is complete when `gway-web` can host a reusable, deny-by-default, read-only MCP endpoint whose tools are derived from existing GWay Web discovery metadata and whose calls are routed through the existing API dispatch path, with no logs-specific code and no mutation capabilities.
