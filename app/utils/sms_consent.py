"""
Transactional SMS consent helpers.

Form "Transactional SMS Consent" is stored on leads as ``sms_eligible``.
STOP replies set ``sms_opt_out``. Both must allow before any outbound SMS.
"""

from __future__ import annotations


def is_sms_consent_granted(value: object) -> bool:
    """True when sheet/DB consent is Yes (handles bool, 0/1, and common strings)."""
    if value is True or value == 1:
        return True
    if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "y"}:
        return True
    return False


def lead_allows_transactional_sms(lead: dict | None) -> bool:
    """
    Whether we may send transactional SMS to this lead row.

    Requires form consent (``sms_eligible``) and no STOP opt-out.
    Missing lead → False (cannot prove consent).
    """
    if not lead:
        return False
    if lead.get("sms_opt_out") in (True, 1, "1", "true", "True"):
        return False
    return is_sms_consent_granted(lead.get("sms_eligible"))
