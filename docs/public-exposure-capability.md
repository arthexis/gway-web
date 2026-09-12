# Dependency-facing public exposure capability

This document defines the Web capability required by application projects such as `gway-wire` to expose an exact public FQDN without giving Web a separate application lifecycle.

## Ownership

The caller owns the application endpoint and decides when it should exist.

`gway-web` owns the mechanics of public HTTP(S) exposure:

- provider-backed public DNS records;
- Nginx reverse-proxy configuration;
- certificate provisioning and renewal;
- Nginx validation/reload;
- read-only DNS, certificate, Nginx, and public-health checks.

Web must not expose a new user-facing `register` or `unregister` command for this dependency operation. A project such as Wire calls the Python capability directly as part of its own deploy/remove lifecycle.

## Endpoint identity

The capability accepts an exact FQDN. Web does not infer or prepend a subdomain.

Example:

```python
ensure(
    fqdn="register.example.com",
    upstream="http://127.0.0.1:8787",
    health_path="/health",
    certbot=True,
    dns_provider="godaddy",
)
```

The FQDN is the public identity of the exposure request. Callers may keep their own logical names internally, but Web does not require a second site name for this dependency-facing operation.

## Ordinary DNS records

The existing DNS module is focused on ACME DNS-01 TXT records. Web needs a provider-neutral ordinary-record capability for public exposure.

The first required record type is A. The abstraction should be extensible to AAAA and CNAME without coupling callers to a provider implementation.

A minimal shape is:

```python
@dataclass(frozen=True, slots=True)
class DNSRecord:
    name: str
    type: str
    value: str
    ttl: int | None = None

class PublicDNSProvider(Protocol):
    def records(self, name: str, record_type: str | None = None) -> Collection[DNSRecord]: ...
    def ensure_record(self, record: DNSRecord) -> DNSRecord: ...
    def delete_record(self, record: DNSRecord) -> None: ...
```

Provider implementations must reconcile the requested record without deleting unrelated values.

For the first implementation, GoDaddy should implement this protocol because it is already the provider used by the live Wire deployment. Provider-specific credentials and APIs stay entirely inside Web/provider configuration.

## `ensure`

`ensure(...)` is idempotent and converges the complete public exposure for an FQDN.

The operation should:

1. validate the FQDN, upstream, certificate mode, provider selection, and provider credentials;
2. determine or accept the intended public address;
3. reconcile the provider-backed DNS record;
4. stage the Nginx site for the upstream;
5. obtain or validate the requested certificate;
6. validate the Nginx configuration;
7. activate/reload the site;
8. verify DNS, certificate, and public HTTP/health state;
9. persist successful managed state only when the requested external state has been established.

If a later step fails, Web should avoid recording the exposure as successfully managed and should roll back state created by the current operation where doing so is safe and unambiguous.

A repeat call with the same desired state should be a no-op apart from reconciliation/checks.

## `check`

The dependency-facing check is strictly read-only.

Conceptually:

```python
check(
    fqdn="register.example.com",
    upstream="http://127.0.0.1:8787",
    health_path="/health",
)
```

With no selectors it should run every applicable check and aggregate failures instead of aborting after the first one.

Checks should cover:

- provider/live DNS resolution for the FQDN;
- managed Nginx site exists and matches the expected upstream;
- Nginx configuration is valid;
- configured certificate exists and is currently valid;
- certificate hostname matches the supplied FQDN;
- the public HTTPS endpoint presents the expected certificate;
- the public health path returns a successful response when configured.

The result should distinguish DNS, Nginx, TLS, HTTP, and application-health failures.

## `release`

A caller-controlled lifecycle may require Web to remove the public exposure.

`release(fqdn=...)` should remove only state that Web can prove it owns for that exposure. It must not delete unrelated DNS values, certificates, or Nginx sites.

The exact cleanup policy should remain conservative: if ownership cannot be established, return a diagnostic rather than deleting ambiguous external state.

`release` is a Python capability, not a new standalone `gway web unregister` command.

## Public command surface

This change does not introduce `gway web register` or `gway web unregister`.

Existing Web commands may continue to serve human-operated Web workflows. The dependency-facing API should be callable directly by other Gway projects so those projects do not shell out to Web commands or duplicate provider/Nginx/Certbot logic.

## Compatibility

- Keep the Python 3.10 runtime floor.
- Do not require application projects to import provider-specific modules.
- DNS-01 TXT support must continue to work.
- Existing declarative sites and Nginx configuration must remain compatible.
- Ordinary DNS reconciliation must preserve unrelated record values.

## Initial implementation chunks

1. Add provider-neutral ordinary DNS record models/protocol and tests, preserving the existing DNS-01 API.
2. Add the GoDaddy ordinary-record implementation and provider validation.
3. Add dependency-facing `ensure` with transactional persistence and existing Nginx/Certbot primitives.
4. Add aggregate read-only `check` for DNS/Nginx/TLS/public health.
5. Add conservative `release` ownership cleanup.
6. Integrate `gway-wire` PR #33 against this stable capability.

## Acceptance criteria

1. A caller can ensure `register.example.com` -> a local upstream without creating a second logical site name.
2. Web does not infer any subdomain from the FQDN.
3. Public DNS is reconciled through a provider-neutral interface, with GoDaddy supported first.
4. A failed provider or public setup does not leave a successful local managed registration.
5. Repeating `ensure` is idempotent.
6. `check` is read-only and aggregates DNS/Nginx/TLS/HTTP/health failures.
7. `release` removes only state known to belong to the exposure.
8. No new user-facing Web register/unregister lifecycle is added.
9. Existing DNS-01, site, serve, certificate, and check behavior remains compatible.
10. Python 3.10 CI remains green.
