# gway-web

GWAY capability package for deploying and managing web applications independently of a specific web-server implementation.

## Direction

`gway web` exposes application-facing concepts such as domains, reverse proxies, TLS, static sites, configuration validation, status, and reloads. Backend-specific packages (initially Nginx) provide the implementation so applications do not need to encode Nginx-specific deployment policy.

Planned public operations:

```text
gway web domain example.com
gway web proxy example.com 127.0.0.1:8000
gway web tls example.com
gway web status
gway web test
gway web reload
```

The first backend should support Nginx while keeping room for Caddy, Apache, or other implementations later.

## Initial milestones

1. Define a small backend protocol for domain, proxy, TLS, test, reload, and status operations.
2. Implement Nginx configuration discovery and safe virtual-host generation.
3. Make writes transactional: render first, validate before activation, and avoid replacing a working configuration with an invalid one.
4. Configure reverse proxies without requiring applications to know Nginx paths or syntax.
5. Add TLS support without assuming certificate issuance is always desired or available.
6. Keep privileged operations explicit and compatible with GWAY's service/admin permission handling.
7. Add idempotent tests using temporary configuration roots rather than modifying the host during tests.

## Scope

The package owns portable web deployment intent. Nginx-specific primitives may be exposed as an implementation/escape hatch, but application manifests should target the web capability rather than Nginx directly.
