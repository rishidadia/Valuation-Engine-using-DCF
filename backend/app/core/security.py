"""Optional API-key authentication and per-key tenant ownership.

The app is local-first: with no keys configured every route stays open exactly
as before. Setting ``DCF_API_KEYS`` (comma-separated) requires an ``X-API-Key``
header on every ``/api`` route except health, and scopes each key to its own
companies/valuations.

Ownership is stored in the company's JSON metadata rather than a new column so
existing databases keep working without a migration. A key is never stored in
plain text: the tenant id is a truncated SHA-256 of the key.
"""
from __future__ import annotations

import hashlib
import hmac
from contextvars import ContextVar

from .config import settings

PUBLIC_PATHS = frozenset({"/api/health", "/api/company/template"})

_tenant: ContextVar[str | None] = ContextVar("dcf_tenant", default=None)


def configured_keys() -> list[str]:
    return [k.strip() for k in (settings.dcf_api_keys or "").split(",") if k.strip()]


def tenant_for_key(supplied: str) -> str | None:
    """Constant-time key check; returns the hashed tenant id or None."""
    for key in configured_keys():
        if hmac.compare_digest(key, supplied):
            return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return None


def set_tenant(tenant: str | None) -> None:
    _tenant.set(tenant)


def current_tenant() -> str | None:
    return _tenant.get()


def owner_matches(meta: dict | None, tenant: str | None) -> bool:
    """True when the caller may see this resource.

    With authentication disabled (tenant None) everything is visible, matching
    local single-user behaviour. With it enabled, an unowned legacy row is not
    exposed to any key.
    """
    if tenant is None:
        return True
    return (meta or {}).get("owner") == tenant
