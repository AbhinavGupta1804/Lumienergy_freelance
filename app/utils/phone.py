"""
Phone number normalization for E.164 (Cal.com, Twilio, ElevenLabs).
"""


def normalize_e164(phone: str, *, default_country_code: str = "1") -> str:
    """
    Normalize a sheet phone value to E.164 when possible.

    Examples (US default):
      +16025551234   -> +16025551234
      16025551234    -> +16025551234
      6025551234     -> +16025551234 (with default_country_code=1)
    """
    raw = "".join(c for c in phone.strip() if c.isdigit() or c == "+")
    if not raw:
        return ""

    if raw.startswith("+"):
        return f"+{''.join(c for c in raw[1:] if c.isdigit())}"

    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return ""

    # Reject too-short values (e.g. street number "534" from wrong column)
    if len(digits) < 10:
        return ""

    # Already includes country code (e.g. 16025551234)
    if len(digits) > 10 and digits.startswith(default_country_code):
        return f"+{digits}"

    # Local 10-digit number
    if len(digits) == 10:
        return f"+{default_country_code}{digits}"

    return f"+{digits}"
