"""LINE Messaging API — signature verification, reply messages."""

import base64
import hashlib
import hmac
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

LINE_API_URL = "https://api.line.me/v2/bot/message/reply"


def verify_signature(body: bytes, signature: str, channel_secret: str) -> bool:
    """Verify X-Line-Signature per LINE Messaging API spec."""
    hash_value = hmac.new(
        channel_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(hash_value).decode("utf-8")
    return hmac.compare_digest(signature, expected)


def parse_text_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract text message events from LINE webhook payload."""
    events = []
    for event in payload.get("events", []):
        if (
            event.get("type") == "message"
            and event.get("message", {}).get("type") == "text"
        ):
            events.append({
                "reply_token": event["replyToken"],
                "user_id": event["source"]["userId"],
                "text": event["message"]["text"],
            })
    return events


async def reply_message(reply_token: str, text: str, channel_access_token: str):
    """Send a plain text reply via LINE."""
    await _send_reply(
        reply_token,
        [{"type": "text", "text": text[:5000]}],
        channel_access_token,
    )


async def reply_flex_message(
    reply_token: str,
    answer: str,
    sources: list[dict[str, Any]],
    channel_access_token: str,
):
    """Send a rich Flex Message reply. Falls back to plain text on error."""
    try:
        messages = [_build_flex_message(answer, sources)]
    except Exception:
        messages = [{"type": "text", "text": answer[:5000]}]

    await _send_reply(reply_token, messages, channel_access_token)


async def _send_reply(
    reply_token: str, messages: list[dict], channel_access_token: str,
):
    """Send messages via LINE Reply API with response validation."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            LINE_API_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {channel_access_token}",
            },
            json={"replyToken": reply_token, "messages": messages},
        )
        if response.status_code != 200:
            logger.error(
                "LINE reply failed: %d %s", response.status_code, response.text
            )


def _build_flex_message(answer: str, sources: list[dict[str, Any]]) -> dict:
    """Build a LINE Flex Message bubble with answer and source references."""
    display_answer = answer[:2000]

    body_contents: list[dict] = [
        {
            "type": "text",
            "text": display_answer,
            "wrap": True,
            "size": "sm",
            "color": "#333333",
        }
    ]

    if sources:
        source_names = []
        for src in sources[:3]:
            name = src.get("source_filename") or src.get("source", "")
            page = src.get("page", "")
            label = name
            if page and page != "N/A":
                label += f" (p.{page})"
            if label:
                source_names.append(label)

        if source_names:
            body_contents.append({"type": "separator", "margin": "lg"})
            body_contents.append({
                "type": "text",
                "text": "อ้างอิง",
                "weight": "bold",
                "size": "xxs",
                "color": "#AAAAAA",
                "margin": "md",
            })
            for name in source_names:
                body_contents.append({
                    "type": "text",
                    "text": f"- {name}",
                    "size": "xxs",
                    "color": "#AAAAAA",
                    "wrap": True,
                })

    return {
        "type": "flex",
        "altText": display_answer[:400],
        "contents": {
            "type": "bubble",
            "size": "mega",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": body_contents,
                "paddingAll": "16px",
            },
        },
    }
