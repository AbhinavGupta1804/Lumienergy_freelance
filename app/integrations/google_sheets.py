"""
Google Sheets integration — reads lead rows via the Sheets API v4.

Uses a Google Cloud service account JSON file (no browser automation).
Row 1 must include headers; lead fields are mapped by name (see settings SHEETS_COL_*).
"""

import hashlib
import logging
from datetime import datetime, timezone

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import get_settings
from app.integrations.sheet_columns import (
    build_header_index,
    extract_lead_fields,
    validate_headers,
)
from app.models.lead import Lead

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# Read through column Z so extra form fields (email, zip, etc.) are included.
_SHEET_DATA_RANGE_SUFFIX = "A:Z"


def build_row_key(
    row_number: int,
    first_name: str,
    last_name: str,
    address: str,
    phone_no: str,
) -> str:
    """Stable key: row number + hash of content (detects edits on same row)."""
    payload = f"{row_number}|{first_name}|{last_name}|{address}|{phone_no}".strip().lower()
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"row_{row_number}_{digest}"


class GoogleSheetsClient:
    """Fetch rows from the configured spreadsheet worksheet."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.google_service_account_json:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON path is not set")
        if not settings.google_sheets_spreadsheet_id:
            raise ValueError("GOOGLE_SHEETS_SPREADSHEET_ID is not set")

        creds = Credentials.from_service_account_file(
            settings.google_service_account_json,
            scopes=SCOPES,
        )
        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self._spreadsheet_id = settings.google_sheets_spreadsheet_id
        self._worksheet_name = settings.google_sheets_worksheet_name

    def _sheet_range(self) -> str:
        name = self._worksheet_name.strip().replace("'", "''")
        return f"'{name}'!{_SHEET_DATA_RANGE_SUFFIX}"

    def _list_worksheet_titles(self) -> list[str]:
        """Return tab names in the spreadsheet (for error messages)."""
        meta = (
            self._service.spreadsheets()
            .get(spreadsheetId=self._spreadsheet_id, fields="sheets.properties.title")
            .execute()
        )
        return [s["properties"]["title"] for s in meta.get("sheets", [])]

    def fetch_leads(self) -> list[Lead]:
        """
        Read all data rows from the sheet (skips header row).

        Returns leads with row_number >= 2.
        """
        try:
            result = (
                self._service.spreadsheets()
                .values()
                .get(spreadsheetId=self._spreadsheet_id, range=self._sheet_range())
                .execute()
            )
        except HttpError as exc:
            if exc.resp.status == 400:
                tabs = self._list_worksheet_titles()
                logger.error(
                    "Invalid sheet range %r. Tabs in this spreadsheet: %s. "
                    "Set GOOGLE_SHEETS_WORKSHEET_NAME to the exact tab name (bottom of Google Sheets).",
                    self._sheet_range(),
                    tabs,
                )
            raise
        values = result.get("values", [])
        if not values:
            logger.debug("Sheet is empty")
            return []

        headers = [str(h) for h in values[0]]
        header_index = build_header_index(headers)
        missing = validate_headers(header_index)
        if missing:
            raise ValueError(
                f"Sheet is missing required column header(s): {', '.join(missing)}. "
                f"Found headers: {headers}"
            )

        data_rows = values[1:]
        leads: list[Lead] = []
        now = datetime.now(timezone.utc)

        for idx, row in enumerate(data_rows, start=2):
            fields = extract_lead_fields(row, header_index)
            first_name = fields["first_name"]
            last_name = fields["last_name"]
            address = fields["address"]
            phone_no = fields["phone_no"]

            if not first_name and not last_name and not address and not phone_no:
                continue

            row_key = build_row_key(idx, first_name, last_name, address, phone_no)
            leads.append(
                Lead(
                    row_number=idx,
                    first_name=first_name,
                    last_name=last_name,
                    address=address,
                    phone_no=phone_no,
                    row_key=row_key,
                    detected_at=now,
                )
            )

        logger.info("Fetched %s lead(s) from Google Sheets", len(leads))
        return leads
