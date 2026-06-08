"""
Extract post-call analytics fields from ElevenLabs webhook payloads.
"""

from datetime import datetime, timezone
from typing import Any


def extract_post_call_analytics(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Parse ``post_call_transcription`` webhook into DB-ready fields.

    Returns None for event types without analysis (e.g. post_call_audio).
    """
    if payload.get("type") != "post_call_transcription":
        return None

    data = payload.get("data") or {}
    conversation_id = data.get("conversation_id")
    if not conversation_id:
        return None

    metadata = data.get("metadata") or {}
    analysis = data.get("analysis") or {}

    duration = metadata.get("call_duration_secs")
    if duration is not None:
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            duration = None

    call_ended_at: str | None = None
    event_ts = payload.get("event_timestamp")
    if event_ts is not None:
        try:
            call_ended_at = datetime.fromtimestamp(
                int(event_ts), tz=timezone.utc
            ).isoformat()
        except (TypeError, ValueError, OSError):
            pass

    call_successful = analysis.get("call_successful")
    if call_successful is not None:
        call_successful = str(call_successful)

    transcript_summary = analysis.get("transcript_summary")
    if transcript_summary is not None:
        transcript_summary = str(transcript_summary).strip() or None

    termination_reason = metadata.get("termination_reason")
    if termination_reason is not None:
        termination_reason = str(termination_reason).strip() or None

    return {
        "conversation_id": str(conversation_id),
        "call_duration_secs": duration,
        "call_successful": call_successful,
        "transcript_summary": transcript_summary,
        "termination_reason": termination_reason,
        "call_ended_at": call_ended_at,
    }
