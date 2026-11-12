"""
Zoho CRM REST client — OAuth refresh + Lead Attachments / Updates / Notes.

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

# Custom Lead field API names (Zoho Setup → Fields)
ZOHO_FIELD_SALE_REVENUE = "Sale_Revenue"
ZOHO_FIELD_SALE_PROFIT = "Sale_profit"  # legacy; prefer pre/post below
ZOHO_FIELD_PRE_SIGHT_PROFIT = "Pre_Sight_Inspection_Profit"
ZOHO_FIELD_POST_INSPECTION_PROFIT = "Post_Inspection_Profit"
ZOHO_FIELD_SALE_DATE = "Sale_Date"


class ZohoCrmError(Exception):
    """Zoho API failure."""


def zoho_crm_configured() -> bool:
    settings = get_settings()
    return bool(
        (settings.zoho_client_id or "").strip()
        and (settings.zoho_client_secret or "").strip()
        and (settings.zoho_refresh_token or "").strip()
    )


def normalize_zoho_lead_id(zoho_lead_id: str) -> str:
    zid = (zoho_lead_id or "").strip()
    if zid.lower().startswith("zoho-"):
        zid = zid[5:]
    return zid.strip()


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


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Zoho-oauthtoken {token}",
        "Content-Type": "application/json",
    }


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
    lead_id = normalize_zoho_lead_id(zoho_lead_id)
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


async def get_lead(zoho_lead_id: str) -> dict[str, Any] | None:
    """GET /crm/v2/Leads/{id}. Returns None if not found (204/404)."""
    lead_id = normalize_zoho_lead_id(zoho_lead_id)
    if not lead_id:
        return None
    token, api_domain = await get_zoho_access_token()
    url = f"{api_domain.rstrip('/')}/crm/v2/Leads/{lead_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            url, headers={"Authorization": f"Zoho-oauthtoken {token}"}
        )
    if resp.status_code in (204, 404):
        return None
    if resp.status_code >= 400:
        raise ZohoCrmError(
            f"Zoho get lead HTTP {resp.status_code} lead={lead_id}: {resp.text[:500]}"
        )
    payload = resp.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


def _pick_lead_id(rows: list[Any], business_unit: str) -> str | None:
    """Prefer the lead whose Business_unit matches, otherwise the first id."""
    wanted = (business_unit or "").strip().lower()
    fallback = ""
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        lead_id = str(row["id"])
        if not fallback:
            fallback = lead_id
        unit = str(row.get("Business_unit") or "").strip().lower()
        if wanted and wanted in unit:
            return lead_id
    return fallback or None


async def find_lead_id_by_email_or_phone(
    *,
    email: str = "",
    phone: str = "",
    business_unit: str = "",
) -> str | None:
    """Search Zoho Leads by email or phone; return the matching brand when set."""
    token, api_domain = await get_zoho_access_token()
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    base = f"{api_domain.rstrip('/')}/crm/v2/Leads/search"
    email = (email or "").strip()
    phone_digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(phone_digits) > 10:
        phone_digits = phone_digits[-10:]
    unit = (business_unit or "").strip()

    async with httpx.AsyncClient(timeout=30.0) as client:
        if email and unit:
            criteria = f"(Email:equals:{email})and(Business_unit:equals:{unit})"
            resp = await client.get(base, headers=headers, params={"criteria": criteria})
            if resp.status_code == 200:
                picked = _pick_lead_id((resp.json() or {}).get("data") or [], unit)
                if picked:
                    return picked
        if email:
            resp = await client.get(base, headers=headers, params={"email": email})
            if resp.status_code == 200:
                picked = _pick_lead_id((resp.json() or {}).get("data") or [], unit)
                if picked:
                    return picked
        if phone_digits and unit:
            criteria = f"(Phone:equals:{phone_digits})and(Business_unit:equals:{unit})"
            resp = await client.get(base, headers=headers, params={"criteria": criteria})
            if resp.status_code == 200:
                picked = _pick_lead_id((resp.json() or {}).get("data") or [], unit)
                if picked:
                    return picked
        if phone_digits:
            resp = await client.get(base, headers=headers, params={"phone": phone_digits})
            if resp.status_code == 200:
                picked = _pick_lead_id((resp.json() or {}).get("data") or [], unit)
                if picked:
                    return picked
    return None


async def update_lead_fields(
    *,
    zoho_lead_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """
    Update custom/standard fields on a Zoho Lead.

    PUT /crm/v2/Leads
    """
    lead_id = normalize_zoho_lead_id(zoho_lead_id)
    if not lead_id:
        raise ZohoCrmError("zoho_lead_id is required")
    clean = {k: v for k, v in (fields or {}).items() if v is not None and k}
    if not clean:
        raise ZohoCrmError("no fields to update")

    token, api_domain = await get_zoho_access_token()
    url = f"{api_domain.rstrip('/')}/crm/v2/Leads"
    body = {"data": [{"id": lead_id, **clean}]}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.put(url, headers=_auth_headers(token), json=body)
    if resp.status_code >= 400:
        raise ZohoCrmError(
            f"Zoho update lead HTTP {resp.status_code} lead={lead_id}: {resp.text[:800]}"
        )
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text[:500]}

    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list) and data:
        first = data[0] if isinstance(data[0], dict) else {}
        code = first.get("code")
        if code and str(code).upper() != "SUCCESS":
            raise ZohoCrmError(f"Zoho update lead failed lead={lead_id}: {first}")

    logger.info("Zoho lead updated lead_id=%s fields=%s", lead_id, list(clean.keys()))
    return payload if isinstance(payload, dict) else {"data": payload}


async def create_lead_note(
    *,
    zoho_lead_id: str,
    note_content: str,
    note_title: str = "Admin note",
) -> dict[str, Any]:
    """
    Create a Note linked to a Lead.

    POST /crm/v2/Notes
    """
    lead_id = normalize_zoho_lead_id(zoho_lead_id)
    content = (note_content or "").strip()
    if not lead_id:
        raise ZohoCrmError("zoho_lead_id is required")
    if not content:
        raise ZohoCrmError("note content is required")

    token, api_domain = await get_zoho_access_token()
    url = f"{api_domain.rstrip('/')}/crm/v2/Notes"
    body = {
        "data": [
            {
                "Note_Title": (note_title or "Admin note").strip()[:100] or "Admin note",
                "Note_Content": content[:32000],
                "Parent_Id": {"id": lead_id},
                "se_module": "Leads",
            }
        ]
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, headers=_auth_headers(token), json=body)
    if resp.status_code >= 400:
        raise ZohoCrmError(
            f"Zoho create note HTTP {resp.status_code} lead={lead_id}: {resp.text[:800]}"
        )
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text[:500]}

    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list) and data:
        first = data[0] if isinstance(data[0], dict) else {}
        code = first.get("code")
        if code and str(code).upper() != "SUCCESS":
            raise ZohoCrmError(f"Zoho create note failed lead={lead_id}: {first}")

    logger.info("Zoho note created lead_id=%s chars=%s", lead_id, len(content))
    return payload if isinstance(payload, dict) else {"data": payload}
