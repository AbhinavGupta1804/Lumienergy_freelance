"""
Generate a branded preliminary solar analysis PDF for a customer.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.utils.chart_builder import utility_chart_data_uri
from app.utils.roof_snapshot import RoofSnapshotError, roof_snapshot_data_uri
from app.utils.solar_projection import build_projection, format_savings_range

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
FONTS_DIR = Path(__file__).resolve().parents[1] / "static" / "fonts"


@lru_cache(maxsize=8)
def _font_data_uri(filename: str) -> str:
    path = FONTS_DIR / filename
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:font/woff2;base64,{b64}"


def _inter_font_faces() -> dict[str, str]:
    """Self-hosted Inter faces so PDF generation works offline."""
    return {
        "font_regular": _font_data_uri("Inter-Regular.woff2"),
        "font_medium": _font_data_uri("Inter-Medium.woff2"),
        "font_semibold": _font_data_uri("Inter-SemiBold.woff2"),
        "font_bold": _font_data_uri("Inter-Bold.woff2"),
        "font_extrabold": _font_data_uri("Inter-ExtraBold.woff2"),
        "font_italic": _font_data_uri("Inter-Italic.woff2"),
    }


@dataclass
class ReportInput:
    first_name: str
    last_name: str = ""
    address: str = ""
    email: str = ""
    monthly_bill: float = 250.0
    report_date: date | None = None
    calendar_url: str = ""
    include_calendar_link: bool = False


class ReportGenerator:
    """Render the preliminary analysis HTML and convert it to a PDF."""

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def render_html(self, inp: ReportInput) -> str:
        report_date = inp.report_date or date.today()
        first = (inp.first_name or "").strip() or "Customer"
        last = (inp.last_name or "").strip()
        full_name = f"{first} {last}".strip()
        address = (inp.address or "").strip()
        email = (inp.email or "").strip()

        projection = build_projection(inp.monthly_bill)

        roof_uri = ""
        try:
            roof_uri = roof_snapshot_data_uri(address)
        except RoofSnapshotError as exc:
            logger.warning("Roof snapshot skipped: %s", exc)

        # Full 20-year series for the gradient bar chart (matches sample PDF)
        all_annuals = [row.annual for row in projection.years]
        chart_uri = utility_chart_data_uri(all_annuals)

        address_short = address.split(",")[0].strip() if address else address

        calendar_url = (inp.calendar_url or "").strip()
        show_calendar_cta = bool(inp.include_calendar_link and calendar_url)

        template = self._env.get_template("preliminary_report.html")
        return template.render(
            full_name=full_name,
            first_name=first,
            address=address,
            address_short=address_short,
            email=email,
            report_date=report_date.strftime("%B %d, %Y"),
            analysis_month=report_date.strftime("%B %Y").upper(),
            years=projection.years,
            milestone_years={5, 10, 15, 20},
            total_20yr=projection.total_20yr,
            solar_payments=projection.solar_payments_20yr,
            savings_range=format_savings_range(
                projection.savings_low, projection.savings_high
            ),
            roof_image_uri=roof_uri,
            chart_uri=chart_uri,
            show_calendar_cta=show_calendar_cta,
            calendar_url=calendar_url,
            **_inter_font_faces(),
        )

    def generate_pdf_bytes(self, inp: ReportInput) -> bytes:
        html = self.render_html(inp)
        return self._html_to_pdf(html)

    def generate_pdf_file(self, inp: ReportInput, output_path: Path | str) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.generate_pdf_bytes(inp))
        return path

    @staticmethod
    def _html_to_pdf(html: str) -> bytes:
        """Convert HTML to PDF via Playwright Chromium (reliable CSS on Windows)."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright is required for PDF generation. "
                "Run: pip install playwright && playwright install chromium"
            ) from exc

        with sync_playwright() as p:
            # --no-sandbox / shm: required in Docker & Cloud Run containers
            browser = p.chromium.launch(
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle")
            page.evaluate("() => document.fonts.ready")
            pdf_bytes = page.pdf(
                format="Letter",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
            browser.close()
        return pdf_bytes
