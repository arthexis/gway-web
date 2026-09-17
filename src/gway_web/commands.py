"""Small command surface exposed to GWAY."""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .api_config import APIConfig, APIProjectExposure, api_config_path, read_api_config, write_api_config
from .certbot import DNSHooks, certificate_status
from .certbot import obtain as certbot_obtain
from .certbot import obtain_dns as certbot_obtain_dns
from .certbot import renew as certbot_renew
from .config import read_sites, write_sites
from .health import health as probe_health
from .health import status as probe_reachability
from .log_query import list_log_runs, read_log_events
from .nginx import disable as nginx_disable
from .nginx import expose as nginx_expose
from .nginx import reload as nginx_reload
from .nginx import test as nginx_test
from .nginx.discovery import discover_nginx
from .registry import clear as clear_registry
from .site import Site
from .tls import certificate_paths
from .tokens import issue_token, list_tokens, provision_token, revoke_token


def _one_name(values: tuple[str, ...], *, required: bool = False) -> str | None:
    if len(values) > 1:
        raise ValueError("expected at most one site name")
    if not values:
        if required:
            raise ValueError("site name is required")
        return None
    return values[0]


def _configured_sites() -> list[Site]:
    return sorted(read_sites(), key=lambda item: item.name)


def _configured_site(name: str) -> Site:
    for item in _configured_sites():
        if item.name == name:
            return item
    raise KeyError(f"unknown site: {name}")


def _provider(
    cert_provider: str | None, certificate_provider: str | None, certbot: bool
) -> str | None:
    if cert_provider and certificate_provider and cert_provider != certificate_provider:
        raise ValueError("--cert-provider and --certificate-provider disagree")
    provider = cert_provider or certificate_provider
    if certbot:
        if provider and provider != "certbot":
            raise ValueError("--certbot conflicts with another certificate provider")
        provider = "certbot"
    if provider in {"none", "off"}:
        return None
    return provider


def _with_provider(item: Site, provider: str | None) -> Site:
    if provider is None:
        return replace(item, cert_provider=None)
    if provider != "certbot":
        return replace(item, cert_provider=provider, tls=True)
    if not item.domain:
        raise ValueError("Certbot requires a site domain")
    root = Path("/etc/letsencrypt/live") / item.domain
    return replace(
        item,
        cert_provider="certbot",
        tls=True,
        tls_certificate=root / "fullchain.pem",
        tls_certificate_key=root / "privkey.pem",
    )


def site(
    *name: str,
    create: bool = False,
    update: bool = False,
    url: bool = False,
    upstream: bool = False,
    certbot: bool = False,
    cert_provider: str | None = None,
    certificate_provider: str | None = None,
    domain: str | None = None,
    host: str | None = None,
    port: int | None = None,
    scheme: str | None = None,
    health_path: str | None = None,
    tls: bool | None = None,
    redirect_http: bool | None = None,
    tls_certificate: Path | None = None,
    tls_certificate_key: Path | None = None,
) -> Site | str | list[Site]:
    """List, inspect, create, or update declarative web sites."""
    selected = _one_name(name)
    if create and update:
        raise ValueError("--create and --update are mutually exclusive")
    if (url or upstream) and (create or update):
        raise ValueError("URL views cannot be combined with site mutation")
    if url and upstream:
        raise ValueError("--url and --upstream are mutually exclusive")

    changes = {
        key: value
        for key, value in {
            "domain": domain,
            "host": host,
            "port": port,
            "scheme": scheme,
            "health_path": health_path,
            "tls": tls,
            "redirect_http": redirect_http,
            "tls_certificate": tls_certificate,
            "tls_certificate_key": tls_certificate_key,
        }.items()
        if value is not None
    }
    provider_requested = certbot or cert_provider is not None or certificate_provider is not None
    provider = _provider(cert_provider, certificate_provider, certbot)

    if not create and not update:
        if changes or provider_requested:
            raise ValueError("configuration changes require --create or --update")
        if selected is None:
            return _configured_sites()
        item = _configured_site(selected)
        if url:
            return item.url
        if upstream:
            return item.upstream_url
        return item

    if selected is None:
        raise ValueError("site name is required for --create or --update")
    items = _configured_sites()
    existing = next((item for item in items if item.name == selected), None)
    if create:
        if existing is not None:
            raise ValueError(f"site already exists: {selected}")
        item = Site(name=selected, **changes)
        if provider_requested:
            item = _with_provider(item, provider)
        items.append(item)
    else:
        if existing is None:
            raise KeyError(f"unknown site: {selected}")
        item = replace(existing, **changes)
        if provider_requested:
            item = _with_provider(item, provider)
        items = [item if value.name == selected else value for value in items]

    write_sites(items)
    clear_registry()
    return item


def serve(
    name: str,
    *,
    certbot: bool = False,
    email: str | None = None,
    agree_tos: bool = False,
    dns: bool = False,
    auth_hook: str | None = None,
    cleanup_hook: str | None = None,
) -> Path:
    """Make a configured site fully served and exposed through Nginx."""
    if certbot:
        site(name, update=True, certbot=True)
    target = _configured_site(name)
    if target.cert_provider == "certbot":
        if not target.domain:
            raise ValueError("Certbot requires a site domain")
        status = certificate_status(target.domain)
        if not status.ready:
            if not email or not agree_tos:
                raise ValueError(
                    "missing Certbot certificate; provide --email and --agree-tos to obtain it"
                )
            if dns:
                if not auth_hook or not cleanup_hook:
                    raise ValueError("DNS issuance requires --auth-hook and --cleanup-hook")
                certbot_obtain_dns(
                    target.domain,
                    email=email,
                    hooks=DNSHooks(auth_hook, cleanup_hook),
                    agree_tos=True,
                )
            else:
                bootstrap = replace(
                    target,
                    tls=False,
                    cert_provider=None,
                    tls_certificate=None,
                    tls_certificate_key=None,
                )
                nginx_expose(bootstrap)
                certbot_obtain(bootstrap, email=email, agree_tos=True)
    return nginx_expose(target)


def stop(name: str) -> Path:
    """Stop serving a site publicly without stopping its application process."""
    return nginx_disable(_configured_site(name))


def _api_payload(policy: APIConfig) -> dict[str, object]:
    return {
        "path": str(api_config_path()),
        "base_domain": policy.base_domain,
        "projects": [
            {
                "name": project.name,
                "functions": ["/".join(path) for path in sorted(project.functions)],
                "scope": project.scope,
            }
            for project in policy.projects
        ],
    }


def api(
    *,
    base_domain: str | None = None,
    project: str | None = None,
    functions: str | None = None,
    scope: str | None = None,
) -> dict[str, object]:
    """Inspect or idempotently configure one project in the GWAY Web API policy."""
    policy = read_api_config()
    if base_domain is None and project is None and functions is None and scope is None:
        return _api_payload(policy)
    if project is None and (functions is not None or scope is not None):
        raise ValueError("--functions and --scope require --project")

    projects = {item.name: item for item in policy.projects}
    if project is not None:
        key = project.strip().casefold()
        existing = projects.get(key)
        if functions is None:
            selected_functions = existing.functions if existing is not None else frozenset()
        else:
            selected_functions = frozenset(
                value.strip() for value in functions.split(",") if value.strip()
            )
        selected_scope = scope or (existing.scope if existing is not None else None)
        projects[key] = APIProjectExposure(
            name=key,
            functions=selected_functions,
            scope=selected_scope,
        )

    updated = APIConfig(
        base_domain=base_domain or policy.base_domain,
        projects=tuple(sorted(projects.values(), key=lambda item: item.name)),
    )
    write_api_config(updated)
    return _api_payload(updated)


def token(
    *token_id: str,
    name: str | None = None,
    scope: str = "logs:read",
    ttl: int = 90 * 24 * 60 * 60,
    list: bool = False,
    revoke: bool = False,
    provision_env: str | None = None,
) -> dict[str, object] | list[dict[str, object]]:
    """Issue, provision, list, or revoke scoped GWAY Web bearer tokens."""
    if len(token_id) > 1:
        raise ValueError("expected at most one token id")
    selected = token_id[0] if token_id else None
    modes = sum(bool(value) for value in (list, revoke, provision_env))
    if modes > 1:
        raise ValueError("--list, --revoke, and --provision-env are mutually exclusive")
    if list:
        if selected is not None:
            raise ValueError("token id cannot be combined with --list")
        return list_tokens()
    if revoke:
        if selected is None:
            raise ValueError("token id is required with --revoke")
        return revoke_token(selected)
    if provision_env:
        if selected is not None:
            raise ValueError("token id cannot be combined with --provision-env")
        bearer = os.environ.get(provision_env, "")
        if not bearer:
            raise ValueError(f"token environment variable is empty: {provision_env}")
        return provision_token(bearer, name=name, scopes=scope, ttl=ttl)
    if selected is not None:
        raise ValueError("token id is only valid with --revoke")
    return issue_token(name=name, scopes=scope, ttl=ttl)


def logs(
    run: str | None = None,
    *,
    source: str = "[logs.source]",
    after: int | None = None,
    limit: int = 100,
) -> dict[str, object]:
    """List GWAY log runs or read a bounded page of events from one run."""
    if run is None:
        if after is not None:
            raise ValueError("--after requires a run id")
        return {"runs": list_log_runs(source, limit=limit)}
    return read_log_events(run, source, after=after, limit=limit)


def _public_check(target: Site, timeout: float) -> tuple[bool, str]:
    url = f"{target.url}{target.health_path}"
    try:
        with urlopen(Request(url, method="GET"), timeout=timeout) as response:
            code = response.getcode()
            return 200 <= code < 400, f"HTTP {code} {url}"
    except HTTPError as exc:
        return False, f"HTTP {exc.code} {url}"
    except (URLError, OSError) as exc:
        return False, str(exc)


def check(
    *name: str,
    reachability: bool = False,
    health: bool = False,
    public: bool = False,
    certificate: bool = False,
    nginx: bool = False,
    timeout: float = 5.0,
) -> list[dict[str, object]]:
    """Check one or all sites; with no check flags, run every applicable check."""
    selected = _one_name(name)
    targets = [_configured_site(selected)] if selected else _configured_sites()
    explicit = any((reachability, health, public, certificate, nginx))
    if not explicit:
        reachability = health = public = certificate = nginx = True

    results: list[dict[str, object]] = []
    layout = None
    nginx_ok: bool | None = None
    nginx_detail = ""
    if nginx:
        try:
            layout = discover_nginx()
            nginx_test(layout)
            nginx_ok, nginx_detail = True, "nginx configuration valid"
        except (subprocess.SubprocessError, OSError) as exc:
            nginx_ok, nginx_detail = False, str(exc)

    for target in targets:
        if reachability:
            ok = probe_reachability(target, timeout=timeout)
            results.append({"site": target.name, "check": "reachability", "ok": ok})
        if health:
            result = probe_health(target, timeout=timeout)
            results.append(
                {
                    "site": target.name,
                    "check": "health",
                    "ok": result.ok,
                    "detail": result.error or f"HTTP {result.status_code}",
                }
            )
        if public and target.domain:
            ok, detail = _public_check(target, timeout)
            results.append({"site": target.name, "check": "public", "ok": ok, "detail": detail})
        if certificate and target.tls and target.domain:
            if target.cert_provider == "certbot":
                result = certificate_status(target.domain)
                ok, detail = result.ready, result.state
            else:
                cert, key = certificate_paths(target)
                ok = cert.is_file() and key.is_file()
                detail = f"certificate={cert}; key={key}"
            results.append(
                {"site": target.name, "check": "certificate", "ok": ok, "detail": detail}
            )
        if nginx:
            enabled = None if layout is None else layout.sites_enabled / f"gway-{target.name}.conf"
            is_enabled = enabled is not None and (enabled.exists() or enabled.is_symlink())
            ok = bool(nginx_ok) and is_enabled
            detail = nginx_detail if ok else f"{nginx_detail}; enabled={is_enabled}"
            results.append({"site": target.name, "check": "nginx", "ok": ok, "detail": detail})
    return results


def certificate(
    name: str,
    *,
    obtain: bool = False,
    renew: bool = False,
    dns: bool = False,
    certbot: bool = False,
    email: str | None = None,
    agree_tos: bool = False,
    auth_hook: str | None = None,
    cleanup_hook: str | None = None,
    dry_run: bool = False,
):
    """Inspect, obtain, or renew the certificate for a configured site."""
    if certbot:
        site(name, update=True, certbot=True)
    target = _configured_site(name)
    if not target.domain:
        raise ValueError("certificate operations require a site domain")
    if obtain and renew:
        raise ValueError("--obtain and --renew are mutually exclusive")
    hooks = None
    if auth_hook or cleanup_hook:
        if not auth_hook or not cleanup_hook:
            raise ValueError("both --auth-hook and --cleanup-hook are required")
        hooks = DNSHooks(auth_hook, cleanup_hook)
    if obtain:
        if not email:
            raise ValueError("certificate issuance requires --email")
        if dns:
            if hooks is None:
                raise ValueError("DNS issuance requires auth and cleanup hooks")
            return certbot_obtain_dns(
                target.domain,
                email=email,
                hooks=hooks,
                agree_tos=agree_tos,
            )
        return certbot_obtain(target, email=email, agree_tos=agree_tos)
    if renew:
        return certbot_renew(target.domain, dns_hooks=hooks, dry_run=dry_run)
    return certificate_status(target.domain)


def reload() -> None:
    """Validate and reload the active Nginx configuration."""
    nginx_reload()
