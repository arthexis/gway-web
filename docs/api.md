# Single-call GWay HTTP API

`gway-web` exposes GWay projects through an explicit, deny-by-default HTTP policy. One HTTP request maps to exactly one `Dispatcher.invoke()` call; chains, managed expressions, Sigils, and implicit project exposure are not part of this API.

## First integration: gway-repo

The first supported project exposure is the canonical GWay project `repo` from `gway-repo`. Keep the allowlist in the central `gway-web` configuration rather than in `gway-repo` itself:

```toml
[api]
base_domain = "gway.example.com"

[api.projects.repo]
functions = ["context", "impact", "prs"]
```

That policy permits requests such as:

```text
GET https://repo.gway.example.com/context?issue=1
GET https://repo.gway.example.com/impact?issue=1&depth=2
GET https://repo.gway.example.com/prs?issue=1
```

The registered `gway-repo` alias may be used as the host token as well, but exposure is always checked against the resolved canonical project `repo`. Other repository commands such as `reviews`, `checks`, or `workflows` remain hidden unless they are explicitly added to the central allowlist.

`GET /_gway` reports only the exposed command metadata, so this configuration discovers `context`, `impact`, and `prs` and does not reveal the rest of the repository command inventory.

## Argument errors

The HTTP boundary returns `400 invalid_arguments` only for failures that GWay's programmatic invocation boundary explicitly classifies as transport-safe argument binding or conversion errors. Ordinary exceptions raised by the called project, including ordinary `ValueError`, remain server-side failures and their messages are not returned to clients.

This separation is intentional: transports consume GWay's explicit safe-error contract rather than inferring safety from broad Python exception classes or message text.
