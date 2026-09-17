# Issue #38 — MCP foundation implementation plan

This document scopes the first implementation step for issue #38: establish a reusable, read-only MCP foundation in `gway-web` on top of the generic HTTP/discovery work from issue #31.

## Goal

Provide a small MCP adapter that can expose only explicitly agent-approved GWay Web commands as typed MCP tools over Streamable HTTP, without adding logs-specific behavior yet.

The result of this step should be usable as the shared foundation for the later `logs.arthexis.com` and `repo.arthexis.com` integrations.

## Architectural decisions

- Use MCP as the agent-facing protocol. ChatGPT Apps are built on MCP, and the current MCP Python SDK supports Python 3.10+ and Streamable HTTP, matching this project's runtime.
- Reuse the existing `gway-web` API policy, discovery, dispatch, routing, service, Site, Nginx, and TLS layers. Do not create a parallel command execution or reverse-proxy path.
- Keep MCP exposure stricter than HTTP exposure. A command being available to the CLI or generic HTTP API does not make it MCP-visible.
- V1 is read-only. No mutation, shell execution, arbitrary chain execution, sigil expansion, arbitrary Python functions, or filesystem access.
- Reader authentication currently reuses scoped GWay Web bearer tokens at the MCP boundary. Final user OAuth/account linking remains a later connection step.
- Prefer structured MCP tool results and structured protocol errors. Do not leak Python tracebacks to remote clients.
- Use bounded request/result handling from the start so later log/event tools cannot accidentally become unbounded data channels.

## Proposed module boundary

The implementation is split into:

- `mcp_config.py`
  - MCP enablement and explicit MCP allowlist policy.
  - persisted public-host allowlist for Streamable HTTP transport security.
- `mcp_schema.py`
  - transforms already-exposed GWay command metadata into MCP tool names/descriptions/input schemas.
  - contains no transport or execution logic.
- `mcp_dispatch.py`
  - validates MCP visibility, invokes the existing API dispatcher/service path, normalizes results/errors.
- `mcp_server.py`
  - creates the MCP server and Streamable HTTP application/endpoint.
  - applies explicit transport Host protection for reverse-proxy deployment.
- `mcp_service.py`
  - managed loopback service entry point.
  - exposes `/mcp` through the SDK and `/health` for the existing GWay Web exposure orchestrator.

The adapter depends inward on the existing API abstractions rather than importing project-specific commands directly.

## Exposure model

The intended hierarchy is:

```text
GWay CLI callable
    └── explicitly HTTP exposed by gway-web
            └── explicitly MCP exposed by gway-web
                    └── explicitly accepted public MCP host
```

MCP configuration must never widen the canonical HTTP exposure policy. Aliases must resolve to the canonical project before policy evaluation.

The public-host layer is required because the MCP Python SDK protects Streamable HTTP from DNS rebinding. A reverse-proxied deployment must explicitly allow the public `Host` value or the SDK rejects requests before MCP dispatch. `mcp.toml` therefore stores `public_hosts`, and `gway web mcp --host ...` updates that deployment policy.

## Public deployment contract

The managed MCP service binds to `127.0.0.1:8051` by default. Public exposure must continue to use the normal GWay Web Site/Nginx/TLS path rather than special MCP proxy code.

A deployment follows this order:

```text
# 1. Configure the two command allowlists.
gway web api --project web --functions list-runs,get-run,get-events --scope logs:read
gway web mcp --project web --functions list-runs,get-run,get-events

# 2. Declare the public hostname accepted by MCP transport security.
gway web mcp --host mcp.example.com

# 3. Install/restart the managed `mcp` service so it reloads mcp.toml.
#    Select the manifest service with GWAY_SERVICE=mcp when managing it directly.

# 4. Describe the MCP endpoint with the normal web Site model.
gway web site mcp --create \
  --domain mcp.example.com \
  --host 127.0.0.1 \
  --port 8051 \
  --health-path /health \
  --certbot

# 5. Serve it using the normal Nginx/Certbot machinery.
gway web serve mcp --email admin@example.com --agree-tos
```

For an existing `mcp` Site, use `--update` instead of `--create`.

The public protocol URL is then:

```text
https://mcp.example.com/mcp
```

`/health` intentionally does not require an MCP bearer token; it reports only static service health and is used by exposure/readiness checks. Tool discovery and calls remain bearer-authenticated and filtered by the project API scope.

Nginx forwards the normal HTTP method and `Authorization` header to the loopback upstream. The MCP service trusts forwarded proxy metadata only from loopback addresses. Browser CORS is not enabled by default because the initial ChatGPT/agent connection is server-to-server; browser-hosted MCP clients can add a narrow origin policy later if required.

## Tool naming

Generate deterministic names from canonical project + command path, with normalization suitable for MCP tool identifiers. The implementation must detect collisions rather than silently overwrite a tool.

Examples are conceptual only:

```text
repo/context      -> repo_context
repo/impact       -> repo_impact
web/list-runs     -> web_list_runs
```

Descriptions and parameter metadata are derived from the same command discovery metadata already used by `/_gway` wherever possible.

## Implemented foundation

The foundation now includes:

- deny-by-default HTTP and MCP policy intersection;
- deterministic discovery-derived schemas;
- MCP dispatch through the existing API dispatcher;
- bounded structured results and traceback-safe errors;
- explicit read-only log tools (`list-runs`, `get-run`, `get-events`);
- target-specific bearer authorization so a token sees only projects matching its scope;
- persisted MCP public-host policy;
- a managed Streamable HTTP service on loopback;
- `/health` for normal GWay Web exposure/readiness;
- reverse-proxy Host validation using the MCP SDK transport-security settings;
- existing Site/Nginx/Certbot machinery for HTTPS publication.

## Remaining issue #38 work

The generic MCP server/exposure foundation is not the entire issue. Remaining end-to-end work includes:

1. deploy a real MCP endpoint and validate the HTTPS Streamable HTTP handshake;
2. validate repeated live Watchtower log reads using the event cursor without spawning additional workflows;
3. finish writer authentication, preferably GitHub OIDC with repository/workflow allowlisting;
4. complete the current ChatGPT connection/account-linking flow;
5. prove framework reuse with `gway-repo` (`context`, `impact`, `prs`) without repo-specific MCP adapter code;
6. document final OpenAI connection requirements and the two-service adoption pattern.

## Verification sequence

Before the implementation PR is ready for review:

1. install from a clean environment using the project's supported Python version range;
2. run the existing test suite and Ruff;
3. run MCP unit/contract tests;
4. validate `/health` through the public Nginx/TLS endpoint;
5. connect an MCP client to `/mcp` using an allowed public Host and scoped bearer token;
6. confirm a non-allowlisted Host gets rejected before MCP dispatch;
7. validate initialize, tools/list, and one read-only call;
8. confirm an HTTP-exposed-but-not-MCP-exposed command is invisible to MCP;
9. confirm aliases cannot widen canonical policy;
10. confirm an unexpected exception does not expose a traceback to the MCP client.

## Exit condition for the foundation

The foundation is complete when `gway-web` can host a reusable, deny-by-default, read-only MCP endpoint whose tools are derived from existing GWay Web discovery metadata, whose calls are routed through the existing API dispatch path, and whose public endpoint is safely exposed using the same managed Site/Nginx/TLS machinery as other GWay Web services.
