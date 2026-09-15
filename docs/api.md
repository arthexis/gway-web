# Authenticated single-call GWay HTTP API

`gway-web` exposes GWay projects through an explicit, deny-by-default HTTP policy. One HTTP request maps to exactly one `Dispatcher.invoke()` call; chains, managed expressions, Sigils, and implicit project exposure are not part of this API.

The API policy is stored separately from the site manifest (`~/.config/gway/api.toml` by default, or `GWAY_WEB_API_CONFIG`). This prevents normal site persistence from replacing API policy tables.

## First integration: gway-repo

`gway-repo` remains HTTP-agnostic. Gway Web owns routing, authentication and public exposure:

```toml
[api]
base_domain = "arthexis.com"

[api.projects.repo]
functions = ["context", "impact", "prs", "map", "files", "symbols", "code"]
scope = "repo:read"
```

Configure the same policy through GWay:

```text
gway web api --base-domain arthexis.com --project repo --functions context,impact,prs,map,files,symbols,code --scope repo:read
```

The API service is a normal managed GWay service:

```text
GWAY_SERVICE=api gway service install web --user root
```

It listens on `127.0.0.1:8050` by default. `/health` is deliberately minimal and unauthenticated so deployment tooling can probe the loopback/public service. Every exposed callable and `/_gway` discovery request requires a scoped bearer token.

## Bearer tokens

Tokens use the existing Gway Web token store. A repository token needs `repo:read`:

```text
gway web token --name repo-api --scope repo:read
```

For automated deployment, a previously issued token can be supplied only through an environment variable and provisioned idempotently. The command output contains metadata but never repeats the bearer secret:

```text
GWAY_REPO_READ_TOKEN='gweb_v1_...' \
  gway web token --name repo-api --scope repo:read --provision-env GWAY_REPO_READ_TOKEN
```

Only the token digest is persisted. Missing, invalid, expired, revoked, or incorrectly scoped credentials receive `401` with `WWW-Authenticate: Bearer`.

## Requests

```text
GET https://repo.arthexis.com/context?issue=1
Authorization: Bearer <repo token>

GET https://repo.arthexis.com/code?path=/opt/arthexis/app&file=apps/example.py
Authorization: Bearer <repo token>
```

`GET /_gway` reports only exposed command metadata and is bearer-protected. Known but unexposed commands remain hidden with `404`.

## Argument errors

The HTTP boundary returns `400 invalid_arguments` only for failures that GWay's programmatic invocation boundary explicitly classifies as transport-safe argument binding or conversion errors. Ordinary exceptions raised by the called project remain server-side failures and their messages are not returned to clients.
