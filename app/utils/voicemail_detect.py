"""
Detect ElevenLabs voicemail-detection tool usage from post-call webhook data.
"""

from __future__ import annotations

import json
from typing import Any


def _text_suggests_voicemail(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    markers = (
        "voicemail_detection",
        "voicemail detection",
        "voicemail system",
        "reached voicemail",
        "went to voicemail",
        "answered by voicemail",
        "automated greeting",
        "leave a message after the beep",
        "leave a message after the tone",
    )
    return any(m in lowered for m in markers)


def _iter_tool_names(obj: Any) -> list[str]:
    names: list[str] = []
    if isinstance(obj, dict):
        for key in ("name", "tool_name", "type"):
            val = obj.get(key)
            if val:
                names.append(str(val))
        for val in obj.values():
            names.extend(_iter_tool_names(val))
    elif isinstance(obj, list):
        for item in obj:
            names.extend(_iter_tool_names(item))
    elif isinstance(obj, str):
        if "voicemail" in obj.lower():
            names.append(obj)
    return names


def _transcript_has_voicemail_tool(transcript: list[Any] | None) -> bool:
    if not transcript:
        return False
    for turn in transcript:
        if not isinstance(turn, dict):
            continue
        for field in ("tool_calls", "tool_results"):
            block = turn.get(field)
            if not block:
                continue
            for name in _iter_tool_names(block):
                if "voicemail" in name.lower():
                    return True
            try:
                blob = json.dumps(block).lower()
            except (TypeError, ValueError):
                blob = str(block).lower()
            if "voicemail_detection" in blob:
                return True
    return False


def detect_voicemail(
    *,
    webhook_payload: dict[str, Any] | None = None,
    termination_reason: str | None = None,
    transcript_summary: str | None = None,
) -> bool:
    """
    Return True when the call was handled as voicemail (not a live human).

    Primary signal: ElevenLabs ``voicemail_detection`` system tool in transcript.
    Fallback: termination_reason / transcript_summary text from post-call analytics.
    """
    if webhook_payload:
        data = webhook_payload.get("data") or {}
        if _transcript_has_voicemail_tool(data.get("transcript")):
            return True

    if _text_suggests_voicemail(termination_reason):
        return True
    if _text_suggests_voicemail(transcript_summary):
        return True

    return False
