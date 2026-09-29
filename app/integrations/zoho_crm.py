"""
Zoho CRM REST client — OAuth refresh + Lead Attachments.

Credentials mirror Apps Script (new.gs): client id/secret + refresh token.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_token_cache: dict[str, Any] = {"access_token": "", "expires_at": 0.0, "api_domain": ""}


class ZohoCrmError(Exception):
    """Zoho API failure."""


def zoho_crm_configured() -> bool:
    settings = get_settings()
    return bool(
        (settings.zoho_client_id or "").strip()
        and (settings.zoho_client_secret or "").strip()
        and (settings.zoho_refresh_token or "").strip()
    )


async def get_zoho_access_token() -> tuple[str, str]:
    """Return (access_token, api_domain). Cached until near expiry."""
    if not zoho_crm_configured():
        raise ZohoCrmError("Zoho CRM OAuth env vars are not configured")

    now = time.time()
    if _token_cache["access_token"] and now < float(_token_cache["expires_at"]) - 60:
        return str(_token_cache["access_token"]), str(_token_cache["api_domain"])

    settings = get_settings()
    accounts = (settings.zoho_accounts_url or "https://accounts.zoho.com").rstrip("/")
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{accounts}/oauth/v2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": settings.zoho_client_id.strip(),
                "client_secret": settings.zoho_client_secret.strip(),
                "refresh_token": settings.zoho_refresh_token.strip(),
            },
        )
    if resp.status_code >= 400:
        raise ZohoCrmError(f"Zoho token refresh HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    token = (data.get("access_token") or "").strip()
    if not token:
        raise ZohoCrmError(f"Zoho token refresh missing access_token: {data}")
    api_domain = (
        (data.get("api_domain") or "").strip()
        or (settings.zoho_api_domain or "https://www.zohoapis.com").rstrip("/")
    )
    ttl = int(data.get("expires_in") or 3600)
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = now + ttl
    _token_cache["api_domain"] = api_domain
    return token, api_domain


async def attach_file_to_lead(
    *,
    zoho_lead_id: str,
    filename: str,
    content: bytes,
    content_type: str = "application/octet-stream",
) -> dict[str, Any]:
    """
    Upload a file onto a Zoho Lead's Attachments.

    POST /crm/v2/Leads/{id}/Attachments  (multipart field name: file)
    """
    lead_id = (zoho_lead_id or "").strip()
    if not lead_id:
        raise ZohoCrmError("zoho_lead_id is required")
    if not content:
        raise ZohoCrmError("empty file content")

    token, api_domain = await get_zoho_access_token()
    url = f"{api_domain.rstrip('/')}/crm/v2/Leads/{lead_id}/Attachments"
    safe_name = (filename or "utility-bill").strip() or "utility-bill"
    mime = (content_type or "application/octet-stream").strip()

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            files={"file": (safe_name, content, mime)},
        )
    if resp.status_code >= 400:
        raise ZohoCrmError(
            f"Zoho attach HTTP {resp.status_code} lead={lead_id}: {resp.text[:800]}"
        )
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text[:500]}
    logger.info(
        "Zoho attachment uploaded lead_id=%s filename=%s bytes=%s",
        lead_id,
        safe_name,
        len(content),
    )
    return payload if isinstance(payload, dict) else {"data": payload}
