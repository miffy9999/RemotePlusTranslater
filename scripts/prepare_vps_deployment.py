from __future__ import annotations

import argparse
import ipaddress
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote, urlparse

from translator_app import __version__

ROOT = Path(__file__).resolve().parent.parent
DOMAIN = re.compile(
    r"(?=^.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PLACEHOLDER = re.compile(r"(?:_HERE\b|\bREPLACE(?:_|\s+WITH\b))", re.IGNORECASE)


def _clean_text(value: object, label: str) -> str:
    text = str(value).strip()
    if not text or any(ord(char) < 32 for char in text):
        raise ValueError(f"{label} is empty or contains control characters")
    if PLACEHOLDER.search(text):
        raise ValueError(f"{label} still contains a placeholder")
    return text


def _domain(value: object, label: str) -> str:
    domain = _clean_text(value, label).casefold().rstrip(".")
    if DOMAIN.fullmatch(domain) is None:
        raise ValueError(f"{label} must be a fully-qualified domain name")
    reserved = ("example.com", "example.net", "example.org")
    if domain.endswith(".example") or any(
        domain == value or domain.endswith(f".{value}") for value in reserved
    ):
        raise ValueError(f"{label} must use the actual deployment domain")
    return domain


def _email(value: object, label: str) -> str:
    email = _clean_text(value, label)
    if EMAIL.fullmatch(email) is None:
        raise ValueError(f"{label} is invalid")
    return email


def _https_url(value: object, label: str) -> str:
    url = _clean_text(value, label)
    parsed = urlparse(url)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} has an invalid port") from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(f"{label} must be a clean absolute HTTPS URL")
    return url


def render_deployment(profile: dict, output: Path) -> dict:
    required = {
        "site_domain",
        "download_domain",
        "admin_email",
        "allowed_cidrs",
        "privacy_url",
        "publisher_name",
        "support_email",
    }
    missing = required - profile.keys()
    if missing:
        raise ValueError(f"Deployment profile is missing: {sorted(missing)}")
    site_domain = _domain(profile["site_domain"], "site_domain")
    download_domain = _domain(profile["download_domain"], "download_domain")
    if site_domain == download_domain:
        raise ValueError("site_domain and download_domain must be different")
    admin_email = _email(profile["admin_email"], "admin_email")
    support_email = _email(profile["support_email"], "support_email")
    privacy_url = _https_url(profile["privacy_url"], "privacy_url")
    publisher_name = _clean_text(profile["publisher_name"], "publisher_name")
    cidr_values = profile["allowed_cidrs"]
    if not isinstance(cidr_values, list) or not cidr_values:
        raise ValueError("allowed_cidrs must contain at least one hotel or VPN network")
    cidrs = []
    for value in cidr_values:
        try:
            network = ipaddress.ip_network(str(value).strip(), strict=False)
        except ValueError as exc:
            raise ValueError(f"Invalid allowed CIDR: {value}") from exc
        if network.prefixlen == 0:
            raise ValueError("allowed_cidrs cannot expose the service to the entire internet")
        cidrs.append(network.with_prefixlen)
    cidrs = list(dict.fromkeys(cidrs))

    installer_name = f"RemotePlusTranslator-Setup-{__version__}.exe"
    download_url = (
        f"https://{download_domain}/releases/{__version__}/{quote(installer_name)}"
    )
    caddy_template = (
        ROOT / "deploy/vps/Caddyfile.internal.example"
    ).read_text(encoding="utf-8")
    caddy = (
        caddy_template.replace("ADMIN_EMAIL_HERE", admin_email)
        .replace("REMOTEPLUS_DOMAIN_HERE", site_domain)
        .replace("DOWNLOAD_DOMAIN_HERE", download_domain)
        .replace("ALLOWED_CIDRS_HERE", " ".join(cidrs))
    )
    site_template = (ROOT / "deploy/vps/site/index.html").read_text(encoding="utf-8")
    site = (
        site_template.replace("DOWNLOAD_URL_HERE", download_url)
        .replace("PRIVACY_URL_HERE", privacy_url)
        .replace("PUBLISHER_NAME_HERE", publisher_name)
        .replace("SUPPORT_EMAIL_HERE", support_email)
    )
    if PLACEHOLDER.search(caddy) or PLACEHOLDER.search(site):
        raise ValueError("Rendered deployment still contains a placeholder")

    output.mkdir(parents=True, exist_ok=False)
    (output / "site").mkdir()
    (output / "Caddyfile").write_text(caddy, encoding="utf-8", newline="\n")
    (output / "site/index.html").write_text(site, encoding="utf-8", newline="\n")
    for name in ("activate_release.sh", "rollback_channel.sh", "check_capacity.sh"):
        shutil.copy2(ROOT / "deploy/vps" / name, output / name)
    summary = {
        "schema": 1,
        "version": __version__,
        "site_domain": site_domain,
        "download_domain": download_domain,
        "allowed_cidrs": cidrs,
        "manifest_url": f"https://{download_domain}/channels/stable/manifest.json",
        "download_url": download_url,
    }
    (output / "deployment.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a fail-closed internal VPS bundle")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    summary = render_deployment(profile, args.output)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
