"""
Google Sheets integration — reads lead rows via the Sheets API v4.

Uses a Google Cloud service account JSON file (no browser automation).
Expected columns (row 1): first_name | last name | address | phone_no  (A:D)
"""

import hashlib
import logging
from datetime import datetime, timezone

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import get_settings
from app.models.lead import Lead

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


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
        # Always quote the tab name — required for spaces and safest for all names.
        # Example: 'Sheet1'!A:D
        name = self._worksheet_name.strip().replace("'", "''")
        return f"'{name}'!A:D"

    def _list_worksheet_titles(self) -> list[str]:
        """Return tab names in the spreadsheet (for error messages)."""
        meta = (
            self._service.spreadsheets()
            .get(spreadsheetId=self._spreadsheet_id, fields="sheets.properties.title")
            .execute()
        )
        return [s["properties"]["title"] for s in meta.get("sheets", [])]

    @staticmethod
    def _row_key(
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

        # Columns A–D: first_name | last name | address | phone_no
        data_rows = values[1:]
        leads: list[Lead] = []
        now = datetime.now(timezone.utc)

        for idx, row in enumerate(data_rows, start=2):
            cells = (row + ["", "", "", ""])[:4]
            first_name, last_name, address, phone_no = [str(c).strip() for c in cells]

            # Skip completely empty rows
            if not first_name and not last_name and not address and not phone_no:
                continue

            row_key = self._row_key(idx, first_name, last_name, address, phone_no)
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
