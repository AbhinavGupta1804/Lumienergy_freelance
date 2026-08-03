"""
Map Google Sheet rows to lead fields by header name (row 1).

Default headers match the "Landing page forms" spreadsheet layout.
Override via SHEETS_COL_* env vars if headers change.
"""

from app.config import get_settings


def _normalize_header(header: str) -> str:
    return str(header).strip().lower()


def parse_yes_no_consent(value: str | None) -> bool:
    """True when sheet consent column is Yes (case-insensitive)."""
    return (value or "").strip().lower() in {"yes", "y", "true", "1"}


def normalize_offer_page(value: str | None) -> str:
    """
    Normalize Offer Page / Form Source cells to a slug.

    Handles URLs and paths from the main site (e.g. ``/getquote``,
    ``https://…/aps-hike``) so eligibility checks stay consistent.
    """
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    if "://" in raw:
        from urllib.parse import urlparse

        path = urlparse(raw).path or ""
        raw = path.strip() or raw
    raw = raw.strip("/")
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1]
    return raw.split("?", 1)[0].strip()


# Sheet bucket labels → dollar amount used for solar projections / report PDF.
_MONTHLY_BILL_BUCKETS: dict[str, float] = {
    "under_100": 100.0,
    "100_150": 150.0,
    "150_200": 200.0,
    "200_300": 250.0,
    "300_400": 350.0,
    "400_plus": 500.0,
}


def parse_monthly_bill(value: str | float | int | None) -> float:
    """
    Map sheet Monthly Bill cell to a numeric bill for report math.

    Sheet sends buckets like ``200_300`` (not a literal float). Underscores
    must not be treated as thousands separators.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value) if float(value) > 0 else 0.0

    raw = str(value).strip()
    if not raw:
        return 0.0

    # Normalize: spaces/hyphens → underscores (e.g. 300-400 → 300_400)
    key = raw.lower().replace(" ", "_").replace("-", "_")
    if key in _MONTHLY_BILL_BUCKETS:
        return _MONTHLY_BILL_BUCKETS[key]

    # Plain number from sheet (e.g. "250" or "$250")
    cleaned = raw.replace("$", "").replace(",", "").strip()
    try:
        amount = float(cleaned)
        return amount if amount > 0 else 0.0
    except (ValueError, TypeError):
        return 0.0


def build_header_index(headers: list[str]) -> dict[str, int]:
    """Map normalized header text → zero-based column index."""
    index: dict[str, int] = {}
    for i, header in enumerate(headers):
        key = _normalize_header(header)
        if key:
            index[key] = i
    return index


def required_header_names() -> dict[str, str]:
    """Internal field name → expected sheet header (from settings)."""
    settings = get_settings()
    return {
        "first_name": settings.sheets_col_first_name,
        "last_name": settings.sheets_col_last_name,
        "address": settings.sheets_col_address,
        "phone_no": settings.sheets_col_phone,
    }


def validate_headers(header_index: dict[str, int]) -> list[str]:
    """Return missing required header names (empty if all present)."""
    missing: list[str] = []
    for _field, header_name in required_header_names().items():
        if _normalize_header(header_name) not in header_index:
            missing.append(header_name)
    return missing


def extract_lead_fields(row: list[str], header_index: dict[str, int]) -> dict[str, str]:
    """Pull first_name, last_name, address, phone_no from a data row."""

    def cell(header_name: str) -> str:
        idx = header_index.get(_normalize_header(header_name))
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx]).strip()

    names = required_header_names()
    settings = get_settings()
    email_header = settings.sheets_col_email
    consent_header = settings.sheets_col_sms_consent
    offer_page_header = settings.sheets_col_offer_page
    monthly_bill_header = settings.sheets_col_monthly_bill
    return {
        "first_name": cell(names["first_name"]),
        "last_name": cell(names["last_name"]),
        "address": cell(names["address"]),
        "phone_no": cell(names["phone_no"]),
        "email": cell(email_header),
        "sms_consent": cell(consent_header),
        "offer_page": cell(offer_page_header),
        "monthly_bill": cell(monthly_bill_header),
    }
