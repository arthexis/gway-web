"""Dependency-facing public exposure orchestration.

The caller owns the application lifecycle. Gway Web owns public DNS, Nginx,
certificate lifecycle, and public reachability for the exact FQDN requested.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import ssl
from pathlib import Path
from urllib.parse import urlsplit

from .certbot import certificate_status, obtain as certbot_obtain, renew as certbot_renew
from .commands import check as site_check
from .config import read_sites, write_sites
from .nginx import disable as nginx_disable
from .nginx import expose as nginx_expose
from .nginx import restore as nginx_restore
from .nginx import snapshot as nginx_snapshot
from .public_dns import DNSRecord, GoDaddyPublicDNSProvider, PublicDNSProvider
from .registry import clear as clear_registry
from .site import Site

_FQDN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def _fqdn(value: str) -> str:
    normalized = value.strip().lower().rstrip(".")
    if not _FQDN_RE.fullmatch(normalized):
        raise ValueError(f"invalid FQDN: {value!r}")
    return normalized


def _upstream(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("upstream must be an http(s) URL with a host")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("upstream must not include a path, query, or fragment")

    host = parsed.hostname
    if host != "localhost":
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("dependency-facing exposure requires a loopback upstream") from exc
        if not address.is_loopback:
            raise ValueError("dependency-facing exposure requires a loopback upstream")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.scheme, host, port


def _secret(direct: str, file_var: str) -> str:
    value = os.environ.get(direct, "").strip()
    if value:
        return value
    path = os.environ.get(file_var, "").strip()
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8").strip()


def _provider(name: str | None, zone: str | None) -> PublicDNSProvider | None:
    if name is None or name.strip().lower() in {"", "none", "disabled"}:
        return None
    selected = name.strip().lower()
    if selected != "godaddy":
        raise ValueError(f"unsupported public DNS provider: {name}")
    configured_zone = (zone or os.environ.get("GWAY_GODADDY_DOMAIN", "")).strip()
    key = _secret("GWAY_GODADDY_KEY", "GWAY_GODADDY_KEY_FILE")
    secret = _secret("GWAY_GODADDY_SECRET", "GWAY_GODADDY_SECRET_FILE")
    return GoDaddyPublicDNSProvider(zone=configured_zone, key=key, secret=secret)


def _site_for(
    fqdn: str,
    upstream: str,
    health_path: str,
    *,
    tls: bool,
) -> Site:
    scheme, host, port = _upstream(upstream)
    cert = Path("/etc/letsencrypt/live") / fqdn / "fullchain.pem"
    key = Path("/etc/letsencrypt/live") / fqdn / "privkey.pem"
    return Site(
        name=fqdn,
        domain=fqdn,
        host=host,
        port=port,
        scheme=scheme,
        health_path=health_path,
        tls=tls,
        cert_provider="certbot" if tls else None,
        tls_certificate=cert if tls else None,
        tls_certificate_key=key if tls else None,
    )


def _persist(target: Site) -> None:
    sites = read_sites()
    sites = [item for item in sites if item.name != target.name and item.domain != target.domain]
    sites.append(target)
    write_sites(sites)
    clear_registry()


def _http_status(stream, *, fqdn: str, path: str) -> int:
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {fqdn}\r\n"
        "Connection: close\r\n"
        "User-Agent: gway-web/0.1\r\n\r\n"
    ).encode("ascii")
    stream.sendall(request)
    response = bytearray()
    while b"\r\n" not in response and len(response) < 8192:
        chunk = stream.recv(1024)
        if not chunk:
            break
        response.extend(chunk)
    first_line = bytes(response).split(b"\r\n", 1)[0]
    parts = first_line.split()
    if len(parts) < 2 or not parts[0].startswith(b"HTTP/"):
        raise OSError("public endpoint returned an invalid HTTP response")
    try:
        return int(parts[1])
    except ValueError as exc:
        raise OSError("public endpoint returned an invalid HTTP status") from exc


def _public_health(
    target: Site,
    timeout: float,
    public_address: str | None = None,
) -> dict[str, object]:
    fqdn = target.domain or target.host
    connect_host = public_address or fqdn
    port = 443 if target.tls else 80
    url = f"{target.url}{target.health_path}"
    try:
        with socket.create_connection((connect_host, port), timeout=timeout) as raw:
            if target.tls:
                context = ssl.create_default_context()
                with context.wrap_socket(raw, server_hostname=fqdn) as wrapped:
                    status = _http_status(wrapped, fqdn=fqdn, path=target.health_path)
            else:
                status = _http_status(raw, fqdn=fqdn, path=target.health_path)
        return {
            "ok": 200 <= status < 400,
            "url": url,
            "address": public_address,
            "status": status,
        }
    except (OSError, ssl.SSLError, ssl.CertificateError) as exc:
        return {
            "ok": False,
            "url": url,
            "address": public_address,
            "status": None,
            "error": str(exc),
        }


def _public_tls(
    fqdn: str,
    timeout: float,
    public_address: str | None = None,
) -> dict[str, object]:
    """Verify the live HTTPS certificate chain, expiry, and hostname."""
    context = ssl.create_default_context()
    connect_host = public_address or fqdn
    try:
        with socket.create_connection((connect_host, 443), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=fqdn) as wrapped:
                certificate = wrapped.getpeercert()
                return {
                    "ok": True,
                    "fqdn": fqdn,
                    "address": public_address,
                    "subject": certificate.get("subject"),
                    "not_after": certificate.get("notAfter"),
                }
    except (OSError, ssl.SSLError, ssl.CertificateError) as exc:
        return {
            "ok": False,
            "fqdn": fqdn,
            "address": public_address,
            "error": str(exc),
        }


def ensure(
    *,
    fqdn: str,
    upstream: str,
    health_path: str = "/health",
    certbot: bool = True,
    dns_provider: str | None = None,
    dns_zone: str | None = None,
    public_address: str | None = None,
    email: str | None = None,
    agree_tos: bool = True,
    timeout: float = 5.0,
) -> dict[str, object]:
    """Idempotently expose one exact FQDN and persist only successful state."""
    target_fqdn = _fqdn(fqdn)
    if not health_path.startswith("/"):
        raise ValueError("health_path must start with '/'")

    # Validate all local input and capture the pre-transaction Nginx state before
    # mutating any external provider state.
    bootstrap = _site_for(target_fqdn, upstream, health_path, tls=False)
    provider = _provider(dns_provider, dns_zone)
    previous_nginx = nginx_snapshot(bootstrap)
    previous_records: list[DNSRecord] | None = None
    address = public_address.strip() if public_address else None
    nginx_changed = False

    try:
        if provider is not None:
            previous_records = list(provider.records(target_fqdn, "A"))
            if address is None:
                if not previous_records:
                    raise ValueError(
                        "public_address is required when the FQDN has no existing A record"
                    )
                address = previous_records[0].value
            provider.ensure_record(DNSRecord(target_fqdn, "A", address))

        if certbot:
            # HTTP first so HTTP-01 can work even when the previous/default HTTPS
            # certificate is expired or belongs to another virtual host.
            nginx_expose(bootstrap)
            nginx_changed = True
            status = certificate_status(target_fqdn)
            if status.state == "managed":
                status = certbot_renew(target_fqdn, deploy_hook=None)
            elif status.state == "missing":
                if not email:
                    raise ValueError("certificate issuance requires an email address")
                status = certbot_obtain(bootstrap, email=email, agree_tos=agree_tos)
            else:
                raise RuntimeError(
                    f"refusing certificate mutation in {status.state!r} state for {target_fqdn}"
                )
            if not status.ready:
                raise RuntimeError(f"certificate is not ready for {target_fqdn}")
            target = _site_for(target_fqdn, upstream, health_path, tls=True)
        else:
            target = bootstrap

        nginx_expose(target)
        nginx_changed = True
        tls_result = (
            _public_tls(target_fqdn, timeout, address) if target.tls else {"ok": True}
        )
        if not tls_result["ok"]:
            raise RuntimeError(f"public TLS check failed: {tls_result}")
        public = _public_health(target, timeout, address)
        if not public["ok"]:
            raise RuntimeError(f"public health check failed: {public}")
        _persist(target)
        return {
            "success": True,
            "fqdn": target_fqdn,
            "upstream": upstream,
            "dns_provider": dns_provider,
            "public_address": address,
            "tls": tls_result,
            "public": public,
        }
    except Exception:
        if nginx_changed:
            try:
                nginx_restore(previous_nginx)
            except Exception:
                pass
        if provider is not None and previous_records is not None:
            try:
                provider.replace_records(target_fqdn, "A", previous_records)
            except Exception:
                pass
        raise


def check(
    *,
    fqdn: str,
    dns_provider: str | None = None,
    dns_zone: str | None = None,
    public_address: str | None = None,
    timeout: float = 5.0,
) -> dict[str, object]:
    """Read-only aggregate check for one exact public FQDN."""
    target_fqdn = _fqdn(fqdn)
    configured = next(
        (item for item in read_sites() if item.name == target_fqdn or item.domain == target_fqdn),
        None,
    )
    results: list[dict[str, object]] = []
    provider = _provider(dns_provider, dns_zone)
    address = public_address.strip() if public_address else None
    if provider is not None:
        records = list(provider.records(target_fqdn, "A"))
        values = [item.value for item in records]
        ok = bool(values) and (address is None or address in values)
        results.append({"check": "dns", "ok": ok, "values": values, "expected": address})
    if configured is None:
        results.append({"check": "managed", "ok": False, "detail": "FQDN is not managed"})
    else:
        tls_result = (
            _public_tls(target_fqdn, timeout, address) if configured.tls else None
        )
        for item in site_check(configured.name, timeout=timeout):
            observed = {"check": item["check"], **item}
            if item["check"] == "certificate" and tls_result is not None:
                observed["ok"] = bool(item.get("ok")) and bool(tls_result.get("ok"))
                observed["live_tls"] = tls_result
            results.append(observed)
        if tls_result is not None:
            results.append(tls_result | {"check": "tls"})
        results.append(
            _public_health(configured, timeout, address) | {"check": "public_health"}
        )
    return {
        "fqdn": target_fqdn,
        "ok": bool(results) and all(bool(item.get("ok")) for item in results),
        "checks": results,
    }


def release(
    *,
    fqdn: str,
    dns_provider: str | None = None,
    dns_zone: str | None = None,
    public_address: str | None = None,
) -> dict[str, object]:
    """Conservatively release only state provably owned by this exact FQDN."""
    target_fqdn = _fqdn(fqdn)
    sites = read_sites()
    target = next(
        (item for item in sites if item.name == target_fqdn and item.domain == target_fqdn),
        None,
    )
    if target is None:
        return {"fqdn": target_fqdn, "released": False, "reason": "not-managed"}

    provider = _provider(dns_provider, dns_zone)
    address = public_address.strip() if public_address else None
    previous_nginx = nginx_snapshot(target)
    remaining = [item for item in sites if item != target]

    try:
        nginx_disable(target)
    except Exception as exc:
        return {
            "fqdn": target_fqdn,
            "released": False,
            "stage": "nginx",
            "error": str(exc),
        }

    try:
        write_sites(remaining)
        clear_registry()
    except Exception as exc:
        restored = True
        try:
            nginx_restore(previous_nginx)
        except Exception:
            restored = False
        return {
            "fqdn": target_fqdn,
            "released": False,
            "stage": "manifest",
            "nginx_restored": restored,
            "error": str(exc),
        }

    dns_removed = False
    if provider is not None and address:
        try:
            provider.delete_record(DNSRecord(target_fqdn, "A", address))
            dns_removed = True
        except Exception as exc:
            return {
                "fqdn": target_fqdn,
                "released": False,
                "partial": True,
                "local_released": True,
                "dns_removed": False,
                "stage": "dns",
                "error": str(exc),
            }

    return {"fqdn": target_fqdn, "released": True, "dns_removed": dns_removed}
