"""
Stage 1 + Stage 2 SMS copy from Lumi Energy Email & Text Automation Content.

Placeholders: {first_name}, {rep_name}, {company_phone}, {google_reviews_url},
{founder_video_url}, {website_url}, {bill_upload_url}, {calendar_url}
"""

from __future__ import annotations

# Days from sequence start. Touch 1 (day 0) sends immediately on Stage 2 activate;
# touches 2–10 are scheduled as deltas between these entries (quiet hours applied).
STAGE2_CADENCE_DAYS: tuple[float, ...] = (
    0,
    1,
    2,
    4,
    6,
    8,
    11,
    14,
    18,
    22,
)

_STOP_FOOTER = "\nReply STOP to unsubscribe."

# Stage 1 — appointment booked (Option B shorter)
STAGE1_APPOINTMENT_SMS = (
    "Great talking with you, {first_name}! 🌞 Check your email — we sent a link "
    "to add your appointment to your calendar and a quick link to upload your "
    "electric bill so we're ready to go. See you soon! — Lumi Energy"
)

# Stage 2 — 10-touch no-answer (1-based index in dict)
STAGE2_SMS: dict[int, str] = {
    1: (
        "Hey {first_name}, this is {rep_name} with Lumi Energy — tried giving you "
        "a call! No worries if you missed it, what's a good time to catch you today? 🌞"
    ),
    2: (
        "{first_name}, quick question — do you know what your electric company "
        "doesn't want you finding out about solar? We'll tell you for free, no "
        "strings attached. Just reply INFO 👀"
    ),
    3: (
        "{first_name}, don't just take our word for it — here's what homeowners "
        "in your area are saying about going solar with us: {google_reviews_url} 🌟 "
        "Want us to run your numbers next?"
    ),
    4: (
        "Quick myth-bust, {first_name}: solar does NOT mean giant upfront costs "
        "or a busted roof. Most homeowners are surprised how simple it actually is. "
        "Want the real breakdown? 🔆"
    ),
    5: (
    "{first_name}, random question — if you could see exactly what solar would "
    "cost for your home and what your monthly savings could look like, would "
    "you want to see the numbers? 👀"
    ),
    6: (
        "{first_name}, electric rates have been climbing again this year. We're "
        "helping homeowners in your area lock in predictable energy costs — want "
        "us to check what you could save? 📉"
    ),
    7: (
        "{first_name}, heads up — solar incentives and rebate programs shift "
        "throughout the year and aren't guaranteed to stick around. Want us to "
        "check what you currently qualify for? ⏳"
    ),
    8: (
        "Hey {first_name} — quick one: on a scale of 1-10, how curious are you "
        "about solar right now? Just reply with a number, no wrong answer 😊"
    ),
    9: (
        "{first_name}, still thinking about solar or should we close out your "
        "file for now? Totally fine either way — just want to respect your time 🙂"
    ),
    10: (
        "{first_name}, this'll be our last check-in for now. If solar's still on "
        "your radar down the road, we're here — {company_phone}. Wishing you well "
        "either way! ☀️"
    ),
}


def render_stage1_sms(**kwargs: str) -> str:
    return _format(STAGE1_APPOINTMENT_SMS, **kwargs) + _STOP_FOOTER


def render_stage2_sms(touch: int, **kwargs: str) -> str:
    template = STAGE2_SMS.get(touch)
    if not template:
        raise ValueError(f"Unknown Stage 2 touch: {touch}")
    body = _format(template, **kwargs)
    # Touch 1 already invites a reply; still add STOP for TCPA
    return body + _STOP_FOOTER


def _format(template: str, **kwargs: str) -> str:
    safe = {k: (v or "").strip() for k, v in kwargs.items()}
    if not safe.get("first_name"):
        safe["first_name"] = "there"
    try:
        return template.format(**safe)
    except KeyError:
        # Missing optional URLs — leave blank
        class _Blank(dict):
            def __missing__(self, key: str) -> str:
                return ""

        return template.format_map(_Blank(**safe))
