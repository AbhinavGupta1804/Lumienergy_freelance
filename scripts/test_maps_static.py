"""One-off test: fetch a satellite roof snapshot via Google Maps Static API."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
STATIC_MAP_URL = "https://maps.googleapis.com/maps/api/staticmap"


def geocode_address(client: httpx.Client, address: str, api_key: str) -> tuple[float, float, str]:
    """Return rooftop lat/lng and Google's formatted address."""
    response = client.get(GEOCODE_URL, params={"address": address, "key": api_key})
    response.raise_for_status()
    payload = response.json()
    status = payload.get("status")
    if status != "OK" or not payload.get("results"):
        raise RuntimeError(f"Geocoding failed: {status} — {payload.get('error_message', '')}")

    result = payload["results"][0]
    location = result["geometry"]["location"]
    formatted = result.get("formatted_address", address)
    location_type = result["geometry"].get("location_type", "")
    print(f"Geocoded: {formatted}")
    print(f"Location type: {location_type}")
    return location["lat"], location["lng"], formatted


def fetch_roof_snapshot(
    client: httpx.Client,
    *,
    lat: float,
    lng: float,
    api_key: str,
    zoom: int = 22,
    size: str = "420x420",
    scale: int = 2,
) -> bytes:
    """
    Fetch a tight satellite crop centered on one rooftop.

    Square size + max zoom keeps neighboring homes out of frame.
    """
    params = {
        "center": f"{lat},{lng}",
        "zoom": zoom,
        "size": size,
        "maptype": "satellite",
        "scale": scale,
        "key": api_key,
    }
    response = client.get(STATIC_MAP_URL, params=params)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "image" not in content_type:
        raise RuntimeError(f"Expected image, got {content_type}: {response.text[:300]}")
    return response.content


def main() -> None:
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        print("FAIL: GOOGLE_API_KEY not found in .env")
        sys.exit(1)

    # Include city/state so Google centers on the correct rooftop, not the street.
    address = "1898 N 141st Ave, Goodyear, AZ 85395"
    out = ROOT / "data" / "test_roof_snapshot.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=30.0) as client:
        lat, lng, formatted = geocode_address(client, address, api_key)
        image_bytes = fetch_roof_snapshot(client, lat=lat, lng=lng, api_key=api_key)

    out.write_bytes(image_bytes)
    print(f"HTTP status: 200")
    print(f"Body size: {len(image_bytes)} bytes")
    print(f"SUCCESS: saved satellite image to {out}")
    print(f"Settings: zoom=22, size=420x420, scale=2, center={lat},{lng}")


if __name__ == "__main__":
    main()
