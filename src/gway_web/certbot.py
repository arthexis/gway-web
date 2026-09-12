"""Certbot certificate-provider operations that never mutate Nginx configuration."""

from __future__ import annotations

import configparser
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .nginx.render import DEFAULT_ACME_WEBROOT
from .site import Site
from .tls import LETSENCRYPT_LIVE

LETSENCRYPT_RENEWAL = Path("/etc/letsencrypt/renewal")
DEFAULT_DEPLOY_HOOK = "gway web reload"
CERTBOT_INSTALL_GUIDANCE = (
    "Certbot executable was not found. Install Certbot first "
    "(Debian/Ubuntu: apt install certbot) and retry."
)


@dataclass(frozen=True, slots=True)
class CertificateStatus:
    """Observed Certbot certificate material and renewal metadata for one domain."""

    domain: str
    certificate: Path
    key: Path
    renewal_config: Path
    state: str

    @property
    def ready(self) -> bool:
        return self.certificate.is_file() and self.key.is_file()

    @property
    def managed(self) -> bool:
        return self.state == "managed"


@dataclass(frozen=True, slots=True)
class ChallengeResult:
    """Diagnostic result for an HTTP-01 challenge file and public URL."""

    ok: bool
    url: str
    path: Path
    local_exists: bool
    status_code: int | None
    body_matches: bool | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DNSHooks:
    """External DNS provider commands used by Certbot manual DNS-01 challenges."""

    auth_hook: str
    cleanup_hook: str

    def __post_init__(self) -> None:
        if not self.auth_hook.strip() or not self.cleanup_hook.strip():
            raise ValueError("DNS auth and cleanup hooks cannot be empty")
        if "\n" in self.auth_hook or "\r" in self.auth_hook:
            raise ValueError("DNS auth hook must be a single command line")
        if "\n" in self.cleanup_hook or "\r" in self.cleanup_hook:
            raise ValueError("DNS cleanup hook must be a single command line")


def discover_certbot(executable: str | Path | None = None) -> Path:
    """Locate Certbot or raise with actionable installation guidance."""

    candidate = str(executable) if executable is not None else "certbot"
    resolved = shutil.which(candidate)
    if resolved is None:
        raise FileNotFoundError(CERTBOT_INSTALL_GUIDANCE)
    return Path(resolved)


def certificate_status(
    domain: str,
    *,
    live_root: str | Path = LETSENCRYPT_LIVE,
    renewal_root: str | Path = LETSENCRYPT_RENEWAL,
) -> CertificateStatus:
    """Describe certificate files and Certbot renewal ownership for a domain."""

    _validate_domain(domain)
    live = Path(live_root) / domain
    renewal = Path(renewal_root) / f"{domain}.conf"
    certificate = live / "fullchain.pem"
    key = live / "privkey.pem"

    has_material = certificate.is_file() and key.is_file()
    has_renewal = renewal.is_file()
    if has_material and has_renewal:
        state = "managed"
    elif has_renewal:
        state = "incomplete"
    elif live.exists():
        state = "stale"
    else:
        state = "missing"

    return CertificateStatus(
        domain=domain,
        certificate=certificate,
        key=key,
        renewal_config=renewal,
        state=state,
    )


def obtain(
    site: Site,
    *,
    email: str,
    agree_tos: bool = False,
    webroot: str | Path = DEFAULT_ACME_WEBROOT,
    executable: str | Path | None = None,
    staging: bool = False,
) -> CertificateStatus:
    """Obtain or keep a certificate with Certbot's HTTP-01 webroot authenticator."""

    domain = _site_domain(site)
    _validate_issuance(email, agree_tos)

    before = certificate_status(domain)
    _refuse_stale(before)

    webroot_path = Path(webroot)
    webroot_path.mkdir(parents=True, exist_ok=True)
    command = [
        str(discover_certbot(executable)),
        "certonly",
        "--webroot",
        "--webroot-path",
        str(webroot_path),
        "--domain",
        domain,
        "--cert-name",
        domain,
        "--non-interactive",
        "--agree-tos",
        "--email",
        email,
        "--keep-until-expiring",
    ]
    if staging:
        command.append("--test-cert")
    subprocess.run(command, check=True)

    result = certificate_status(domain)
    _require_ready(result)
    return result


def obtain_dns(
    domain: str,
    *,
    email: str,
    hooks: DNSHooks,
    agree_tos: bool = False,
    cert_name: str | None = None,
    executable: str | Path | None = None,
    staging: bool = False,
) -> CertificateStatus:
    """Obtain a normal or wildcard certificate through external DNS-01 hook commands."""

    _validate_domain(domain)
    _validate_issuance(email, agree_tos)
    certificate_name = _certificate_name(domain, cert_name)
    before = certificate_status(certificate_name)
    _refuse_stale(before)

    command = [
        str(discover_certbot(executable)),
        "certonly",
        "--manual",
        "--preferred-challenges",
        "dns",
        "--manual-auth-hook",
        hooks.auth_hook,
        "--manual-cleanup-hook",
        hooks.cleanup_hook,
        "--domain",
        domain,
        "--cert-name",
        certificate_name,
        "--non-interactive",
        "--agree-tos",
        "--email",
        email,
        "--keep-until-expiring",
    ]
    if staging:
        command.append("--test-cert")
    subprocess.run(command, check=True)

    result = certificate_status(certificate_name)
    _require_ready(result)
    return result


def renew(
    domain: str,
    *,
    executable: str | Path | None = None,
    deploy_hook: str | None = DEFAULT_DEPLOY_HOOK,
    dry_run: bool = False,
    dns_hooks: DNSHooks | None = None,
) -> CertificateStatus:
    """Renew one GWAY-compatible Certbot certificate without using the Nginx plugin."""

    current = certificate_status(domain)
    if current.state != "managed":
        raise RuntimeError(f"cannot renew Certbot certificate in {current.state!r} state")
    authenticator = _renewal_authenticator(current.renewal_config)

    manual_args: list[str] = []
    if authenticator == "webroot":
        pass
    elif authenticator == "manual" and dns_hooks is not None:
        manual_args = [
            "--preferred-challenges",
            "dns",
            "--manual-auth-hook",
            dns_hooks.auth_hook,
            "--manual-cleanup-hook",
            dns_hooks.cleanup_hook,
        ]
    else:
        expected = "'webroot' or 'manual' with dns_hooks"
        raise RuntimeError(
            f"refusing renewal configured with {authenticator!r}; expected {expected}"
        )

    command = [
        str(discover_certbot(executable)),
        "renew",
        "--cert-name",
        domain,
        "--non-interactive",
        *manual_args,
    ]
    if deploy_hook:
        command.extend(["--deploy-hook", deploy_hook])
    if dry_run:
        command.append("--dry-run")
    subprocess.run(command, check=True)

    result = certificate_status(domain)
    if not dry_run:
        _require_ready(result)
    return result


def challenge(
    site: Site,
    token: str,
    *,
    expected: str | None = None,
    webroot: str | Path = DEFAULT_ACME_WEBROOT,
    timeout: float = 5.0,
) -> ChallengeResult:
    """Probe a local ACME challenge file through its public HTTP URL."""

    domain = _site_domain(site)
    _validate_token(token)
    path = Path(webroot) / ".well-known" / "acme-challenge" / token
    local_exists = path.is_file()
    if expected is None and local_exists:
        expected = path.read_text(encoding="utf-8")
    url = f"http://{domain}/.well-known/acme-challenge/{token}"
    request = Request(url, method="GET")

    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            code = response.getcode()
            body_matches = expected is None or body == expected
            return ChallengeResult(
                ok=local_exists and 200 <= code < 300 and body_matches,
                url=url,
                path=path,
                local_exists=local_exists,
                status_code=code,
                body_matches=body_matches,
            )
    except HTTPError as exc:
        return ChallengeResult(
            ok=False,
            url=url,
            path=path,
            local_exists=local_exists,
            status_code=exc.code,
            body_matches=None,
            error=str(exc),
        )
    except (URLError, OSError) as exc:
        return ChallengeResult(
            ok=False,
            url=url,
            path=path,
            local_exists=local_exists,
            status_code=None,
            body_matches=None,
            error=str(exc),
        )


def _site_domain(site: Site) -> str:
    if not site.domain:
        raise ValueError("Certbot HTTP-01 requires a site domain")
    _validate_domain(site.domain)
    if site.domain.startswith("*."):
        raise ValueError("Certbot HTTP-01 does not support wildcard domains")
    return site.domain


def _validate_domain(domain: str) -> None:
    if not domain or domain in {".", ".."} or "/" in domain or "\\" in domain:
        raise ValueError("domain is not safe for Certbot certificate paths")
    if any(character.isspace() for character in domain):
        raise ValueError("domain is not safe for Certbot certificate paths")
    if "*" in domain and (not domain.startswith("*.") or "*" in domain.removeprefix("*.")):
        raise ValueError("wildcard is only allowed as the leading '*.' label")


def _certificate_name(domain: str, cert_name: str | None) -> str:
    name = cert_name or domain.removeprefix("*.")
    _validate_domain(name)
    if "*" in name:
        raise ValueError("Certbot certificate name cannot contain a wildcard")
    return name


def _validate_issuance(email: str, agree_tos: bool) -> None:
    if not agree_tos:
        raise ValueError("Certbot issuance requires explicit agreement to the ACME terms")
    if not email.strip():
        raise ValueError("Certbot issuance requires a contact email")


def _refuse_stale(status: CertificateStatus) -> None:
    if status.state == "stale":
        raise RuntimeError(
            f"refusing to issue over stale Certbot live directory: {status.certificate.parent}"
        )


def _validate_token(token: str) -> None:
    if not token or token in {".", ".."} or "/" in token or "\\" in token:
        raise ValueError("challenge token is not safe for the ACME webroot")


def _renewal_authenticator(path: Path) -> str | None:
    """Read renewalparams while tolerating Certbot metadata before the first section."""

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    first_section = next(
        (index for index, line in enumerate(lines) if line.lstrip().startswith("[")),
        None,
    )
    if first_section is None:
        raise configparser.MissingSectionHeaderError(str(path), 1, lines[0] if lines else "")

    for line_number, line in enumerate(lines[:first_section], start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if "=" not in line:
            raise configparser.MissingSectionHeaderError(str(path), line_number, line)

    parser = configparser.ConfigParser()
    parser.read_string("\n".join(lines[first_section:]), source=str(path))
    if parser.has_option("renewalparams", "authenticator"):
        return parser.get("renewalparams", "authenticator")
    return None


def _require_ready(result: CertificateStatus) -> None:
    if not result.ready:
        raise FileNotFoundError(
            f"Certbot completed without usable certificate material for {result.domain}"
        )
