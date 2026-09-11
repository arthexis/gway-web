# gway-web

GWAY capability package for describing, deploying, exposing, and managing web applications through an application-facing interface.

## Direction

`gway web` is the public management layer for web applications such as Arthexis, Odoo, Django, Bottle, static sites, and other HTTP services. Callers should describe the application they want to expose rather than manage a specific reverse proxy directly.

Nginx support belongs inside this package as an implementation backend. It should not require a separate `gway-nginx` project. This keeps the public API centered on web applications while still allowing the implementation to support other backends later if needed.

Core scope rule:

> `gway-web` manages web applications and their exposure. Nginx is one supported exposure backend, not a first-class GWAY domain.

Planned public operations:

```text
gway web site <name> [--domain ...] [--host ...] [--port ...]
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

The package defines a small portable web-application description:

```python
Site(
    name="arthexis",
    domain="example.com",
    host="127.0.0.1",
    port=8000,
    health_path="/health/",
)
```

The GWAY-style `site` command constructs the same portable description from command arguments:

```text
gway web site arthexis --domain example.com --host 127.0.0.1 --port 8000 --health-path /health/
```

Managed applications may expose their own `site` command and forward to `gway web site` after enriching these arguments from application-owned state. For example, Arthexis may read its own Site model and supply the resolved domain, bind address, port, scheme, and health path. `gway-web` must not import or depend on the application's model layer.

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
    ├── discovery.py
    └── render.py
```

The `nginx` package is internal implementation structure, not a separate GWAY capability package.

## Roadmap

The active implementation roadmap is tracked in issue #6. The key ownership rule is that GWAY owns generated Nginx configuration. Certificate providers such as Certbot may issue and renew certificate material, but they must not rewrite GWAY-managed Nginx files.

Current staged plan:

1. Nginx discovery and pure rendering.
2. Transactional activation and host operations.
3. TLS intent and existing certificate attachment.
4. Certbot `certonly` integration.
5. DNS-01 provider boundary.
6. Existing-site adoption and Arthexis cutover.

## External applications

External applications should be first-class `gway-web` use cases. Odoo, for example, should be manageable through a site definition without requiring an Odoo-specific Nginx workflow:

```python
Site(
    name="odoo",
    domain="erp.example.com",
    host="127.0.0.1",
    port=8069,
    health_path="/web/login",
)
```

The goal is for users and applications to think in terms of `web`, regardless of whether the current exposure implementation is Nginx.

## Future backends

The implementation should keep enough internal separation that Caddy, Apache, or another backend could be added later, but this is not a reason to split Nginx into its own repository now.

If a backend eventually becomes independently useful or large enough to justify extraction, it can be moved to another package without changing the public `gway web` API.
