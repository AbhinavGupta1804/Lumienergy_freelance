"""
Discord Incoming Webhook — post messages to a fixed channel.

Uses a webhook URL (no bot token). Create in Discord:
  Server → Channel → Edit Channel → Integrations → Webhooks → New Webhook
"""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

DISCORD_CONTENT_LIMIT = 2000
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096
DISCORD_FIELD_VALUE_LIMIT = 1024


class DiscordNotifyError(Exception):
    pass


async def send_discord_embed(
    *,
    title: str,
    description: str,
    fields: list[dict[str, str]] | None = None,
    color: int = 0x2B7A4B,
    webhook_url: str | None = None,
    username: str = "Lumi Calls",
) -> bool:
    """
    POST an embed to a Discord webhook.

    Uses webhook_url if provided, otherwise DISCORD_WEBHOOK_URL.
    Returns True on success.
    """
    settings = get_settings()
    if not settings.discord_notifications_enabled:
        logger.debug("Discord notifications disabled")
        return False
    url = (webhook_url or settings.discord_webhook_url or "").strip()
    if not url:
        logger.warning("Discord webhook URL not set — skip notification")
        return False

    description = description[:DISCORD_EMBED_DESCRIPTION_LIMIT]
    embed: dict = {
        "title": title[:256],
        "description": description,
        "color": color,
    }
    if fields:
        trimmed = []
        for f in fields[:25]:
            trimmed.append(
                {
                    "name": str(f.get("name", ""))[:256],
                    "value": str(f.get("value", ""))[:DISCORD_FIELD_VALUE_LIMIT] or "—",
                    "inline": bool(f.get("inline", False)),
                }
            )
        embed["fields"] = trimmed

    payload = {
        "username": (username or "Lumi")[:80],
        "embeds": [embed],
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        logger.error("Discord webhook HTTP error: %s", exc)
        return False

    if resp.status_code >= 400:
        logger.error("Discord webhook failed HTTP %s: %s", resp.status_code, resp.text)
        return False

    logger.info("Discord notification posted username=%s", username)
    return True
