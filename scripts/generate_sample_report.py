"""Generate a sample preliminary report PDF (design preview)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.config import get_settings  # noqa: E402
from app.services.report_generator import ReportGenerator, ReportInput  # noqa: E402


def main() -> None:
    settings = get_settings()
    calendar_url = (settings.cal_booking_page_url or "").strip() or "https://cal.com"
    out = ROOT / "data" / "reports" / "penny_preliminary_report.pdf"
    inp = ReportInput(
        first_name="Penny",
        last_name="Roberts",
        address="1898 N 141st Ave",
        email="stnba66@gmail.com",
        monthly_bill=250.0,
        calendar_url=calendar_url,
        include_calendar_link=True,
    )
    path = ReportGenerator().generate_pdf_file(inp, out)
    print(f"SUCCESS: wrote {path} ({path.stat().st_size} bytes)")
    print(f"Calendar CTA: {calendar_url}")


if __name__ == "__main__":
    main()
