"""Extract bill-upload tokens from personalized URLs."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

_UUID_RE = re.compile(
    r"/upload/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)
_PATH_TOKEN_RE = re.compile(r"/upload/([^/?#]+)")


def extract_upload_token(url_or_token: str) -> str:
    """
    Accept a raw token or a full upload URL.

    Supported shapes:
      - bare UUID / token
      - https://host/upload/{token}
      - https://host/?token={token}
    """
    raw = (url_or_token or "").strip()
    if not raw:
        return ""
    if "://" not in raw and "/" not in raw and "?" not in raw:
        return raw

    parsed = urlparse(raw)
    qs = parse_qs(parsed.query)
    for key in ("token", "upload_token"):
        vals = qs.get(key) or []
        if vals and str(vals[0]).strip():
            return str(vals[0]).strip()

    match = _UUID_RE.search(parsed.path or "")
    if match:
        return match.group(1)
    match = _PATH_TOKEN_RE.search(parsed.path or "")
    if match:
        return match.group(1).strip()
    return ""
