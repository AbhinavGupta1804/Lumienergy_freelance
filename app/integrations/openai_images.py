"""Send a house photo to OpenAI's image edit API."""

from __future__ import annotations

import base64
import logging

import httpx

from app.config import get_settings
from app.content.lights_house_prompt import LIGHTS_HOUSE_RENDER_PROMPT

logger = logging.getLogger(__name__)

_EDITS_URL = "https://api.openai.com/v1/images/edits"
DEFAULT_IMAGE_MODEL = "gpt-image-2.5-sunburst"
_DEFAULT_MODEL = DEFAULT_IMAGE_MODEL
# Models the image-edit endpoint currently accepts. gpt-image-1 was shut down
# on 2026-10-23; dall-e-2 and dall-e-3 were retired on 2026-05-12.
IMAGE_MODELS: tuple[dict[str, str], ...] = (
    {"id": "gpt-image-2.5-sunburst", "label": "GPT Image 2.5 Sunburst"},
    {"id": "gpt-image-2.5-flare", "label": "GPT Image 2.5 Flare"},
    {"id": "gpt-image-2.5-sunburst-2026-09-08", "label": "GPT Image 2.5 Sunburst (Sep 2026)"},
    {"id": "gpt-image-2.5-flare-2026-09-08", "label": "GPT Image 2.5 Flare (Sep 2026)"},
    {"id": "gpt-image-2", "label": "GPT Image 2"},
    {"id": "gpt-image-2-2026-04-21", "label": "GPT Image 2 (Apr 2026)"},
    {"id": "gpt-image-1.5", "label": "GPT Image 1.5"},
    {"id": "chatgpt-image-latest", "label": "ChatGPT Image latest"},
)
_RETIRED_MODELS = {"gpt-image-1", "gpt-image-1-mini", "dall-e-2", "dall-e-3"}


class OpenAIImageError(Exception):
    """Raised when the lighting preview cannot be generated."""


def _error_message(response: httpx.Response) -> str:
    try:
        message = str(response.json().get("error", {}).get("message") or "").strip()
    except ValueError:
        message = ""
    return message or response.text[:240].strip()


def image_model_options() -> list[dict[str, str]]:
    return [dict(item) for item in IMAGE_MODELS]


def resolve_image_model(requested: str = "") -> str:
    allowed = {item["id"] for item in IMAGE_MODELS}
    choice = (requested or "").strip()
    if choice:
        if choice not in allowed:
            raise OpenAIImageError("Choose one of the listed image models")
        return choice
    settings_model = (get_settings().openai_image_model or "").strip()
    if settings_model in allowed:
        return settings_model
    return _DEFAULT_MODEL


def _prompt_with_extra(extra_prompt: str) -> str:
    extra = " ".join((extra_prompt or "").split())
    if not extra:
        return LIGHTS_HOUSE_RENDER_PROMPT
    return (
        f"{LIGHTS_HOUSE_RENDER_PROMPT}\n\n"
        "Also follow this extra instruction, without undoing the rules above:\n"
        f"{extra}"
    )


def render_house_lighting(
    image_jpeg: bytes,
    *,
    extra_prompt: str = "",
    model: str = "",
    timeout: float = 180.0,
) -> bytes:
    settings = get_settings()
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        raise OpenAIImageError("OPENAI_API_KEY is not configured")
    if not image_jpeg:
        raise OpenAIImageError("The Street View photo is empty")

    model = resolve_image_model(model)
    files = {"image": ("house.jpg", image_jpeg, "image/jpeg")}
    data = {
        "model": model,
        "prompt": _prompt_with_extra(extra_prompt),
        "size": "1536x1024",
        "quality": "medium",
        "output_format": "jpeg",
    }
    # input_fidelity is only accepted by gpt-image-1.5. Newer models reject it with 400.
    if model == "gpt-image-1.5":
        data["input_fidelity"] = "high"
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=timeout) as client:
        response = client.post(_EDITS_URL, headers=headers, data=data, files=files)

    if response.status_code != 200:
        message = _error_message(response).replace(api_key, "")
        logger.warning(
            "OpenAI image edit failed status=%s body=%s",
            response.status_code,
            message[:240],
        )
        if response.status_code in {401, 403}:
            raise OpenAIImageError("OpenAI rejected the API key")
        raise OpenAIImageError(message or f"OpenAI image edit failed ({response.status_code})")

    try:
        payload = response.json()
        b64 = payload["data"][0]["b64_json"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise OpenAIImageError("OpenAI returned an unreadable image") from exc
    try:
        return base64.b64decode(b64)
    except ValueError as exc:
        raise OpenAIImageError("OpenAI returned an unreadable image") from exc
