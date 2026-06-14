"""
Map Google Sheet rows to lead fields by header name (row 1).

Default headers match the "Landing page forms" spreadsheet layout.
Override via SHEETS_COL_* env vars if headers change.
"""

from app.config import get_settings


def _normalize_header(header: str) -> str:
    return str(header).strip().lower()


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
    return {
        "first_name": cell(names["first_name"]),
        "last_name": cell(names["last_name"]),
        "address": cell(names["address"]),
        "phone_no": cell(names["phone_no"]),
    }
