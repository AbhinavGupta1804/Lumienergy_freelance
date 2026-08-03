"""Generate a client-facing PDF of current Lumi email templates."""

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

OUT = Path(__file__).resolve().parents[1] / "Lumi_Energy_Email_Templates.pdf"


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def main() -> None:
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
    )

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleCustom",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=HexColor("#111827"),
        spaceAfter=6,
        alignment=TA_LEFT,
        leading=22,
    )
    subtitle = ParagraphStyle(
        "SubCustom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        textColor=HexColor("#6B7280"),
        spaceAfter=16,
        leading=14,
    )
    h1 = ParagraphStyle(
        "H1Custom",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=13,
        textColor=HexColor("#111827"),
        spaceBefore=14,
        spaceAfter=6,
        leading=16,
    )
    meta = ParagraphStyle(
        "MetaCustom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=HexColor("#374151"),
        spaceAfter=4,
        leading=12,
    )
    label = ParagraphStyle(
        "LabelCustom",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=HexColor("#1F2937"),
        spaceBefore=6,
        spaceAfter=2,
        leading=12,
    )
    body = ParagraphStyle(
        "BodyCustom",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=9,
        textColor=HexColor("#111827"),
        leading=13,
        leftIndent=6,
        rightIndent=6,
        spaceBefore=2,
        spaceAfter=8,
        backColor=HexColor("#F3F4F6"),
        borderPadding=10,
    )
    note = ParagraphStyle(
        "NoteCustom",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=9,
        textColor=HexColor("#6B7280"),
        spaceBefore=4,
        spaceAfter=8,
        leading=12,
    )
    footer = ParagraphStyle(
        "FooterCustom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        textColor=HexColor("#9CA3AF"),
        alignment=TA_CENTER,
        spaceBefore=20,
    )

    def email_block(story, heading, when, subject, body_text, note_text=None):
        story.append(Paragraph(heading, h1))
        story.append(Paragraph(f"<b>When:</b> {when}", meta))
        story.append(Paragraph(f"<b>Subject:</b> {subject}", meta))
        if note_text:
            story.append(Paragraph(note_text, note))
        story.append(Paragraph("<b>Body:</b>", label))
        story.append(Paragraph(esc(body_text), body))
        story.append(
            HRFlowable(
                width="100%",
                thickness=0.5,
                color=HexColor("#E5E7EB"),
                spaceBefore=4,
                spaceAfter=4,
            )
        )

    story = []
    story.append(Paragraph("Lumi Energy — Customer Email Templates", title))
    story.append(
        Paragraph(
            "Current email content sent by the Lumi voice-agent system. "
            "Prepared for client review. Bill-upload and confirmation currently go out as SMS "
            "(NOTIFICATION_CHANNEL=sms); those email variants are included for reference.",
            subtitle,
        )
    )
    story.append(
        HRFlowable(
            width="100%",
            thickness=1,
            color=HexColor("#111827"),
            spaceBefore=0,
            spaceAfter=8,
        )
    )

    email_block(
        story,
        "1. Post-call solar report (not booked)",
        "After the call ends, when the lead did <b>not</b> book an appointment. "
        "PDF ROI report is attached.",
        "quick update on your solar report",
        """Hey {first_name},

Just finished running the numbers through our calculator based on the info you dropped.

Long story short: your property actually qualifies for a higher monthly savings tier than average because of the current Arizona utility rates.

I put the full ROI report together in the attachment below

Take a look, if the math makes sense and you want to see how we actually guarantee those numbers on your next bill, you can grab 10 minutes on our calendar here:
Book your free home consult
{cal_booking_page_url}

Or contact our technician Ivan, directly on 4802526872

Talk soon,
Ayden""",
    )

    email_block(
        story,
        "2. Post-call solar report (booked)",
        "After the call ends, when the lead <b>already booked</b> an appointment. "
        "PDF ROI report is attached. No calendar link.",
        "quick update on your solar report",
        """Hey {first_name},

Just finished running the numbers through our calculator based on the info you dropped.

Long story short: your property actually qualifies for a higher monthly savings tier than average because of the current Arizona utility rates.

I put the full ROI report together in the attachment below

Take a look, if the math makes sense and you want to see how we actually guarantee those numbers on your next bill, we'll walk you through everything at your upcoming appointment.

Or contact our technician Ivan, directly on 4802526872

Talk soon,
Ayden""",
    )

    email_block(
        story,
        "3. Follow-up email (unbooked leads)",
        "Scheduled follow-up for leads who received the report but have not booked yet.",
        "following up on your solar report",
        """Hey {first_name},

Ayden here from Lumi — just floating your solar report back to the top of your inbox.

The numbers I ran for your property still stand, and with where Arizona utility rates are headed, the savings tier you qualify for is worth locking in sooner rather than later.

If the math made sense to you, you can grab 10 minutes on our calendar here:
Book your free home consult
{cal_booking_page_url}

Or contact our technician Ivan, directly on 4802526872

Talk soon,
Ayden""",
    )

    story.append(Paragraph("4. Bill-upload email", h1))
    story.append(
        Paragraph(
            "<b>Note:</b> Currently <b>not sent</b> — system uses SMS for this step "
            "(NOTIFICATION_CHANNEL=sms). Included below if switched to email.",
            note,
        )
    )
    story.append(Paragraph("<b>Subject:</b> Upload your energy bill — Lumi Energy", meta))
    story.append(Paragraph("<b>Body:</b>", label))
    story.append(
        Paragraph(
            esc(
                """Hi {first_name},

Thanks for speaking with Lumi Energy! To prepare your personalised savings estimate, please upload a recent energy bill using this secure link:

{upload_link}

— Lumi Energy"""
            ),
            body,
        )
    )
    story.append(
        HRFlowable(
            width="100%",
            thickness=0.5,
            color=HexColor("#E5E7EB"),
            spaceBefore=4,
            spaceAfter=4,
        )
    )

    story.append(Paragraph("5. Consultation confirmation email (after bill upload)", h1))
    story.append(
        Paragraph(
            "<b>Note:</b> Currently <b>not sent</b> — system uses SMS for this step. "
            "Included below if switched to email.",
            note,
        )
    )
    story.append(
        Paragraph("<b>Subject:</b> Your Lumi Energy consultation is confirmed", meta)
    )
    story.append(Paragraph("<b>Body:</b>", label))
    story.append(
        Paragraph(
            esc(
                """Hi {first_name},

Your consultation is confirmed for {appointment_label}.
We received your bill — thank you!

— Lumi Energy"""
            ),
            body,
        )
    )

    story.append(Spacer(1, 12))
    story.append(
        Paragraph(
            "<b>Placeholders:</b> {first_name}, {cal_booking_page_url}, {upload_link}, "
            "{appointment_label} are filled automatically per lead.",
            meta,
        )
    )
    story.append(Paragraph("Lumi Energy — Client Reference", footer))

    doc.build(story)
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
