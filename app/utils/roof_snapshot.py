"""Fetch a satellite roof snapshot via Google Maps Static API."""

from __future__ import annotations

import base64
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

STATIC_MAP_URL = "https://maps.googleapis.com/maps/api/staticmap"


class RoofSnapshotError(Exception):
    """Raised when the satellite image cannot be fetched."""


def fetch_roof_snapshot_bytes(
    address: str,
    *,
    zoom: int = 20,
    size: str = "640x400",
    scale: int = 2,
    timeout: float = 30.0,
) -> bytes:
    """
    Fetch a satellite image centered on the address string (Static Maps only).

    Static Maps geocodes the address internally — no separate Geocoding call.
    """
    settings = get_settings()
    api_key = (settings.google_api_key or "").strip()
    if not api_key:
        raise RoofSnapshotError("GOOGLE_API_KEY is not configured")

    cleaned = (address or "").strip()
    if not cleaned:
        raise RoofSnapshotError("Address is empty")

    params = {
        "center": cleaned,
        "zoom": zoom,
        "size": size,
        "maptype": "satellite",
        "scale": scale,
        "key": api_key,
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.get(STATIC_MAP_URL, params=params)

    content_type = response.headers.get("content-type", "")
    if response.status_code != 200 or "image" not in content_type:
        logger.warning(
            "Roof snapshot failed status=%s type=%s body=%s",
            response.status_code,
            content_type,
            response.text[:200],
        )
        raise RoofSnapshotError(
            f"Maps Static API failed ({response.status_code}): {response.text[:200]}"
        )
    return response.content


def roof_snapshot_data_uri(address: str, **kwargs) -> str:
    """Return a data:image/png;base64,... URI for embedding in HTML."""
    raw = fetch_roof_snapshot_bytes(address, **kwargs)
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"
