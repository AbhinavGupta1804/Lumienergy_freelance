"""Save a lead's Street View home photo and read it back."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.utils.streetview import (
    StreetViewError,
    fetch_streetview_jpeg,
    streetview_object_name,
)

logger = logging.getLogger(__name__)

_LOCAL_DIR = Path("data/streetview_leads")


def capture_home_streetview(store, *, row_key: str, address: str) -> dict:
    """Fetch the photo, store it, and record the path on the lead."""
    key = (row_key or "").strip()
    if not key:
        raise StreetViewError("Lead is missing")
    image = fetch_streetview_jpeg(address)
    storage_path = _save_jpeg(key, image)
    fetched_at = datetime.now(timezone.utc).isoformat()
    store.set_streetview(
        row_key=key,
        storage_path=storage_path,
        fetched_at=fetched_at,
    )
    return {
        "ok": True,
        "row_key": key,
        "storage_path": storage_path,
        "fetched_at": fetched_at,
    }


def load_streetview_bytes(storage_path: str) -> bytes:
    path = (storage_path or "").strip()
    if not path:
        raise StreetViewError("No home image yet")
    if path.startswith("file:"):
        local = Path(path.removeprefix("file:"))
        if not local.is_file():
            raise StreetViewError("Saved home image is missing")
        return local.read_bytes()

    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise StreetViewError("Supabase storage is not configured")
    from supabase import create_client

    client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    bucket = settings.bill_upload_bucket or "bill_upload"
    data = client.storage.from_(bucket).download(path)
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if hasattr(data, "read"):
        return data.read()
    return bytes(data)


def render_lighting_preview(
    store,
    *,
    row_key: str,
    source_path: str,
    extra_prompt: str = "",
    model: str = "",
) -> dict:
    """Edit the saved Street View photo into a night lighting preview."""
    from app.integrations.openai_images import render_house_lighting

    key = (row_key or "").strip()
    if not key:
        raise StreetViewError("Lead is missing")
    source = load_streetview_bytes(source_path)
    image = render_house_lighting(source, extra_prompt=extra_prompt, model=model)
    name = streetview_object_name(key)
    storage_path = _save_named_jpeg(f"{name}_preview.jpg", image)
    fetched_at = datetime.now(timezone.utc).isoformat()
    store.set_streetview_render(
        row_key=key,
        storage_path=storage_path,
        fetched_at=fetched_at,
    )
    return {
        "ok": True,
        "row_key": key,
        "storage_path": storage_path,
        "fetched_at": fetched_at,
    }


def _save_jpeg(row_key: str, image: bytes) -> str:
    name = streetview_object_name(row_key)
    return _save_named_jpeg(f"{name}.jpg", image)


def _save_named_jpeg(filename: str, image: bytes) -> str:
    settings = get_settings()
    if (settings.database_backend or "sqlite").lower() == "supabase":
        return _save_supabase(f"streetview/{filename}", image)
    _LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    dest = _LOCAL_DIR / filename
    dest.write_bytes(image)
    return f"file:{dest.as_posix()}"


def _save_supabase(object_path: str, image: bytes) -> str:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise StreetViewError("Supabase storage is not configured")
    from supabase import create_client

    client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    bucket = settings.bill_upload_bucket or "bill_upload"
    options = {"content-type": "image/jpeg", "upsert": "true"}
    store = client.storage.from_(bucket)
    try:
        store.upload(object_path, image, options)
    except Exception:
        logger.info("Street View upload exists, replacing %s", object_path)
        store.update(object_path, image, {"content-type": "image/jpeg"})
    return object_path
