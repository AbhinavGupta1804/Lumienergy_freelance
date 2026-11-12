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

# Lumi Lights — consultation booked (Meet when a link is present, otherwise in person)
LIGHTS_APPOINTMENT_SMS_MEET = (
    "Great, {first_name}! Your Lumi Lights consultation is set for "
    "{appointment_date} at {appointment_time} on Google Meet. Check your email "
    "for the calendar invite and Meet link. We'll walk through color, layout, "
    "and a clear quote. See you soon!"
)
LIGHTS_APPOINTMENT_SMS_IN_PERSON = (
    "Great, {first_name}! Your Lumi Lights consultation is set for "
    "{appointment_date} at {appointment_time} at your home. We'll walk through "
    "color, layout, and a clear quote in person. See you soon!"
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


def render_lights_appointment_sms(**kwargs: str) -> str:
    link = (kwargs.get("meet_link") or "").strip()
    template = (
        LIGHTS_APPOINTMENT_SMS_MEET if link else LIGHTS_APPOINTMENT_SMS_IN_PERSON
    )
    return _format(template, **kwargs) + _STOP_FOOTER


def render_appointment_reminder_sms(
    *,
    kind: str,
    brand: str,
    first_name: str,
    appointment_date: str,
    appointment_time: str,
    meet_link: str = "",
) -> str:
    """24 hours before, or 30 minutes before. Meet vs in-person follows the link."""
    link = (meet_link or "").strip()
    name = (first_name or "there").strip() or "there"
    if kind == "30m":
        if link:
            body = (
                f"Hi {name}, your {brand} Google Meet starts in 30 minutes. "
                f"Join here: {link}"
            )
        else:
            body = (
                f"Hi {name}, your {brand} in-home consultation starts in "
                f"30 minutes, {appointment_date} at {appointment_time}. "
                f"See you at your place!"
            )
    elif link:
        body = (
            f"Hi {name}, reminder from {brand}: your Google Meet consultation "
            f"is in 24 hours, {appointment_date} at {appointment_time}. "
            f"Check your email for the Meet link. See you then!"
        )
    else:
        body = (
            f"Hi {name}, reminder from {brand}: your in-home consultation is "
            f"in 24 hours, {appointment_date} at {appointment_time}. "
            f"See you at your place!"
        )
    return body + _STOP_FOOTER


def render_stage2_sms(touch: int, **kwargs: str) -> str:
    template = STAGE2_SMS.get(touch)
    if not template:
        raise ValueError(f"Unknown Stage 2 touch: {touch}")
    body = _format(template, **kwargs)
    # Touch 1 already invites a reply; still add STOP for TCPA
    return body + _STOP_FOOTER


# Lumi Lights — 10-touch no-answer. Same days as Energy Stage 2.
LIGHTS_STAGE2_SMS: dict[int, str] = {
    1: (
        "Hey {first_name}, this is {rep_name} with Lumi Lights! Just tried reaching "
        "you about permanent lighting for your home. Quick question — were you mainly "
        "looking to upgrade your home's appearance, or finally stop hanging holiday "
        "lights every year? Reply here and let me know!"
    ),
    2: (
        "{first_name}, honest question — are you still planning to climb ladders and "
        "hang Christmas lights this year? 😅 There's an easier way. Want to see how "
        "permanent lighting works?"
    ),
    3: (
        "{first_name}, here's the cool part about Lumi Lights: during the day, the "
        "lighting track is color-matched to your home's trim, so it blends in. At "
        "night, your home lights up. Want to see an example? Reply YES!"
    ),
    4: (
        "Quick thought, {first_name} — what if your lights weren't just for Christmas? "
        "🎄 Think warm white every evening, orange for Halloween, team colors on game "
        "day, and custom colors for birthdays. Which would you use most?"
    ),
    5: (
        "{first_name}, one thing worth considering: seasonal lights are temporary, but "
        "permanent lighting is designed to last 20+ years. You install it once and use "
        "it for holidays, game days, and everyday lighting. Want a free quote for your home?"
    ),
    6: (
        "Hey {first_name}, imagine pulling into your driveway and seeing your home "
        "beautifully lit every night — without any visible seasonal lights during the "
        "day. That's what we're aiming for with Lumi Lights. Want to see what a setup "
        "for your home could look like? {website_url}"
    ),
    7: (
        "{first_name}, wondering whether permanent lighting is worth the investment? "
        "Totally fair question. We offer free quotes and financing for qualifying "
        "homeowners, so you can understand the actual cost before deciding. Want us "
        "to price it for your home?"
    ),
    8: (
        "Hey {first_name}, quick one so I don't keep guessing — what's your biggest "
        "reason for considering permanent lighting?\n"
        "1️⃣ Never hanging holiday lights again\n"
        "2️⃣ Making the house look amazing at night\n"
        "3️⃣ Both!\n"
        "Just reply 1, 2, or 3 😊"
    ),
    9: (
        "Hey {first_name}, should we still help you explore permanent lighting for your "
        "home, or has the timing changed? Either is completely fine. Just reply "
        '"INTERESTED" or "LATER" and we\'ll take it from there. — Lumi Lights'
    ),
    10: (
        "Hey {first_name}, I'll close the loop for now so we're not filling up your "
        "phone. If you're ready to ditch the holiday ladder routine or upgrade your "
        "home's nighttime look, just reply \"LIGHTS\" or call {company_phone}. Happy "
        "to help whenever the time is right! — Lumi Lights"
    ),
}


def render_lights_stage2_sms(touch: int, **kwargs: str) -> str:
    template = LIGHTS_STAGE2_SMS.get(touch)
    if not template:
        raise ValueError(f"Unknown Lights Stage 2 touch: {touch}")
    return _format(template, **kwargs) + _STOP_FOOTER


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
