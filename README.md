# gway-web

GWAY capability package for describing, deploying, exposing, and managing web applications through an application-facing interface.

## Direction

`gway web` is the public management layer for web applications such as Arthexis, Odoo, Django, Bottle, static sites, and other HTTP services. Callers should describe the application they want to expose rather than manage a specific reverse proxy directly.

Nginx support belongs inside this package as an implementation backend. It should not require a separate `gway-nginx` project. This keeps the public API centered on web applications while still allowing the implementation to support other backends later if needed.

Core scope rule:

> `gway-web` manages web applications and their exposure. Nginx is one supported exposure backend, not a first-class GWAY domain.

Planned public operations:

```text
gway web sites
gway web status [site]
gway web health [site]
gway web url [site]
gway web serve ...
gway web domain [site]
gway web expose [site]
gway web tls [site]
gway web test
gway web reload
```

Backend-specific implementation details should remain internal wherever possible. An escape hatch may be exposed for advanced cases, but application manifests and normal CLI usage should target `web`, not `nginx`.

## Site model

The package should define a small portable web-application description. A first version can look roughly like:

```python
Site(
    name="arthexis",
    domain="example.com",
    host="127.0.0.1",
    port=8000,
    health="/",
)
```

The model should be usable for applications managed by GWAY as well as external applications such as Odoo. A site may later support an upstream URL or Unix socket, static root, TLS policy, and preferred exposure backend.

The important boundary is that callers describe intent:

```text
application/site
    -> host:port, socket, or static root
    -> domain and health expectations
    -> exposure backend
```

The backend then translates that intent into concrete server configuration.

## Package shape

A likely internal structure is:

```text
gway_web/
├── site.py
├── health.py
├── serve.py
├── domain.py
├── service.py
├── config.py
└── nginx/
    ├── config.py
    ├── sites.py
    ├── proxy.py
    └── tls.py
```

The `nginx` package is internal implementation structure, not a separate GWAY capability package.

## Milestones

### PR1 — minimal web model

Establish the package primitives before touching host configuration.

- Define the `Site` model.
- Implement `url(site)`.
- Implement endpoint reachability/status checks.
- Implement HTTP health checks.
- Provide a basic `serve(...)` facility for simple Python-side serving and development use.
- Add tests and keep CI aligned with `ci-base`.

PR1 should not write Nginx configuration.

### PR2 — service/runtime integration

Represent how a web application is actually running.

- Support host/port, upstream URL, and later Unix sockets.
- Expose application-oriented start/stop/restart/status/log operations where appropriate.
- Delegate generic service/process operations to the relevant GWAY/system facilities rather than duplicating systemd management inside this package.

### PR3 — domains and external URLs

Add the portable concepts needed to expose an application.

- Domain/hostname configuration.
- Canonical HTTP/HTTPS URL generation.
- Expected health endpoint.
- Validation of application reachability before exposure.

DNS-provider mutation remains outside this package. `gway-web` owns the desired hostname, not provider-specific DNS APIs.

### PR4 — Nginx backend

Implement Nginx directly inside `gway-web`.

- Discover Nginx installation and configuration roots.
- Render reverse-proxy and static-site configuration from `Site` intent.
- Keep writes transactional: render first, validate before activation, and never replace a working configuration with an invalid one.
- Support enable/disable/expose operations without requiring callers to know Nginx paths or syntax.
- Add `nginx -t` validation and safe reloads.
- Keep privileged operations explicit and compatible with GWAY admin/service permission handling.
- Use temporary configuration roots in tests rather than modifying the host.

The normal interface remains:

```text
gway web expose odoo
gway web status odoo
gway web reload
```

rather than requiring `gway nginx ...` commands.

### PR5 — TLS

Add TLS as part of exposing a web application.

- Represent TLS intent independently of certificate-provider implementation.
- Generate the appropriate Nginx configuration when Nginx is the selected backend.
- Do not assume certificate issuance is always desired or available.
- Keep certificate issuance/renewal integration separable from site modeling.

### PR6 — Arthexis integration

Use the generic web primitives from Arthexis without making Arthexis dependent on GWAY for normal operation.

Arthexis can expose a site description equivalent to:

```python
Site(
    name="arthexis",
    domain=...,
    host="127.0.0.1",
    port=...,
    health="/health/",
)
```

Then Arthexis diagnostics such as `gway arthexis good` can reuse `gway-web` health/status primitives, while deployment helpers can use the Nginx backend through the same application-facing API.

Arthexis itself must remain independently installable and operable without GWAY.

## External applications

External applications should be first-class `gway-web` use cases. Odoo, for example, should be manageable through a site definition without requiring an Odoo-specific Nginx workflow:

```python
Site(
    name="odoo",
    domain="erp.example.com",
    host="127.0.0.1",
    port=8069,
    health="/web/login",
)
```

The goal is for users and applications to think in terms of `web`, regardless of whether the current exposure implementation is Nginx.

## Future backends

The implementation should keep enough internal separation that Caddy, Apache, or another backend could be added later, but this is not a reason to split Nginx into its own repository now.

If a backend eventually becomes independently useful or large enough to justify extraction, it can be moved to another package without changing the public `gway web` API.
