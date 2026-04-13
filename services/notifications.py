"""Slack alerting for critical errors and system events.

Sends notifications via Slack Incoming Webhook.
Disabled when SLACK_WEBHOOK_URL is empty.
"""

import logging
from datetime import datetime, timezone

import httpx

from config import APP_VERSION, settings

logger = logging.getLogger(__name__)

# ──────────────────────────────────────
# Alert levels
# ──────────────────────────────────────

LEVEL_ERROR = "error"      # red
LEVEL_WARNING = "warning"  # yellow
LEVEL_INFO = "info"        # green

_LEVEL_COLORS = {
    LEVEL_ERROR: "#dc3545",
    LEVEL_WARNING: "#ffc107",
    LEVEL_INFO: "#28a745",
}

_LEVEL_EMOJI = {
    LEVEL_ERROR: ":rotating_light:",
    LEVEL_WARNING: ":warning:",
    LEVEL_INFO: ":white_check_mark:",
}


# ──────────────────────────────────────
# Core send function
# ──────────────────────────────────────

async def send_alert(
    title: str,
    message: str,
    level: str = LEVEL_ERROR,
    fields: dict[str, str] | None = None,
) -> bool:
    """Send an alert to Slack. Returns True if sent, False if disabled/failed."""
    if not settings.SLACK_WEBHOOK_URL:
        return False

    color = _LEVEL_COLORS.get(level, _LEVEL_COLORS[LEVEL_ERROR])
    emoji = _LEVEL_EMOJI.get(level, "")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    attachment_fields = [
        {"title": "Time", "value": now, "short": True},
        {"title": "Version", "value": APP_VERSION, "short": True},
    ]
    if fields:
        for key, value in fields.items():
            attachment_fields.append({"title": key, "value": value, "short": True})

    payload = {
        "channel": settings.SLACK_ALERT_CHANNEL,
        "attachments": [
            {
                "color": color,
                "title": f"{emoji} {title}",
                "text": message,
                "fields": attachment_fields,
                "footer": "CU TIP RAG Bot",
            }
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(settings.SLACK_WEBHOOK_URL, json=payload)
            if res.status_code != 200:
                logger.warning("Slack webhook returned %d: %s", res.status_code, res.text)
                return False
            return True
    except Exception:
        logger.warning("Failed to send Slack alert", exc_info=True)
        return False


# ──────────────────────────────────────
# Convenience functions
# ──────────────────────────────────────

async def alert_error(title: str, message: str, **fields: str) -> bool:
    """Send an error-level alert."""
    return await send_alert(title, message, level=LEVEL_ERROR, fields=fields or None)


async def alert_warning(title: str, message: str, **fields: str) -> bool:
    """Send a warning-level alert."""
    return await send_alert(title, message, level=LEVEL_WARNING, fields=fields or None)


async def alert_info(title: str, message: str, **fields: str) -> bool:
    """Send an info-level alert."""
    return await send_alert(title, message, level=LEVEL_INFO, fields=fields or None)
