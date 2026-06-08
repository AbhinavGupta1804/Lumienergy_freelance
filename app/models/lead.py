"""
Data models for leads read from Google Sheets.
"""

from dataclasses import dataclass
from datetime import datetime

from app.utils.phone import normalize_e164


@dataclass(frozen=True)
class Lead:
    """
    One row from the Google Sheet.

    row_key is a stable identifier for deduplication (sheet row number + content hash).
    """

    row_number: int
    first_name: str
    last_name: str
    address: str
    phone_no: str
    row_key: str
    detected_at: datetime

    @property
    def full_name(self) -> str:
        """First + last name for logging."""
        parts = [self.first_name.strip(), self.last_name.strip()]
        return " ".join(p for p in parts if p)

    @property
    def phone_no_e164(self) -> str:
        """Sheet phone_no normalized to E.164 for Cal.com / agent tools."""
        return normalize_e164(self.phone_no)

    @property
    def dial_number(self) -> str:
        """E.164 number to dial (test mode uses fixed test number)."""
        return self.phone_no_e164 or self.phone_no.strip()
