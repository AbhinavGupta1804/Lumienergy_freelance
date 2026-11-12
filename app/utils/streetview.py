"""Fetch an outdoor Street View photo for a street address."""

from __future__ import annotations

import logging
import re

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

STREETVIEW_URL = "https://maps.googleapis.com/maps/api/streetview"
STREETVIEW_METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"


class StreetViewError(Exception):
    """Raised when a home photo cannot be fetched."""


def streetview_object_name(row_key: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", (row_key or "").strip())[:160]
    return safe or "lead"


def fetch_streetview_jpeg(address: str, *, timeout: float = 30.0) -> bytes:
    """
    Download a Street View JPEG for the address.

    Uses the Street View Static API. The key stays on the server.
    """
    settings = get_settings()
    api_key = (settings.google_api_key or "").strip()
    if not api_key:
        raise StreetViewError("GOOGLE_API_KEY is not configured")

    cleaned = (address or "").strip()
    if not cleaned:
        raise StreetViewError("Address is empty")

    meta_params = {
        "location": cleaned,
        "source": "outdoor",
        "key": api_key,
    }
    image_params = {
        "size": "640x400",
        "scale": 2,
        "location": cleaned,
        "fov": 90,
        "pitch": 8,
        "source": "outdoor",
        "return_error_code": "true",
        "key": api_key,
    }
    with httpx.Client(timeout=timeout) as client:
        meta = client.get(STREETVIEW_METADATA_URL, params=meta_params)
        _raise_for_metadata(meta, api_key)
        response = client.get(STREETVIEW_URL, params=image_params)

    content_type = response.headers.get("content-type", "")
    if response.status_code != 200 or "image" not in content_type:
        detail = response.text[:180].replace(api_key, "")
        logger.warning(
            "Street View image failed status=%s type=%s body=%s",
            response.status_code,
            content_type,
            detail,
        )
        if response.status_code == 404:
            raise StreetViewError("Street View has no photo for this address")
        raise StreetViewError(
            f"Street View API failed ({response.status_code})"
        )
    return response.content


def _raise_for_metadata(response: httpx.Response, api_key: str) -> None:
    if response.status_code != 200:
        detail = response.text[:180].replace(api_key, "")
        logger.warning("Street View metadata failed status=%s body=%s", response.status_code, detail)
        raise StreetViewError(f"Street View lookup failed ({response.status_code})")
    try:
        payload = response.json()
    except ValueError as exc:
        raise StreetViewError("Street View lookup returned an unreadable response") from exc
    status = str(payload.get("status") or "")
    if status == "OK":
        return
    if status in {"ZERO_RESULTS", "NOT_FOUND"}:
        raise StreetViewError("Street View has no photo for this address")
    if status == "REQUEST_DENIED":
        raise StreetViewError("Street View API rejected the key. Enable the Street View Static API.")
    if status == "OVER_QUERY_LIMIT":
        raise StreetViewError("Street View API quota is used up")
    raise StreetViewError(f"Street View lookup failed ({status or 'unknown'})")
