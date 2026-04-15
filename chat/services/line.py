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


_LINE_TEXT_LIMIT = 5000
_MAX_REPLY_MESSAGES = 5  # LINE limit per reply


def _split_text_messages(text: str, max_parts: int = 4) -> list[dict]:
    """Split long text into multiple LINE text messages at natural boundaries."""
    # Fix #1: Guard against empty/whitespace text
    text = (text or "").strip()
    if not text:
        return []

    if len(text) <= _LINE_TEXT_LIMIT:
        return [{"type": "text", "text": text}]

    messages = []
    remaining = text

    while remaining and len(messages) < max_parts:
        if len(remaining) <= _LINE_TEXT_LIMIT:
            messages.append({"type": "text", "text": remaining})
            remaining = ""
        else:
            # Split at last double-newline or newline before limit
            cut = remaining[:_LINE_TEXT_LIMIT].rfind("\n\n")
            if cut < _LINE_TEXT_LIMIT // 3:
                cut = remaining[:_LINE_TEXT_LIMIT].rfind("\n")
            if cut < _LINE_TEXT_LIMIT // 3:
                cut = _LINE_TEXT_LIMIT
            messages.append({"type": "text", "text": remaining[:cut].rstrip()})
            remaining = remaining[cut:].lstrip()

    # Fix #2: If text remains after max_parts, append to last message
    if remaining and messages:
        last_text = messages[-1]["text"]
        combined = last_text + "\n\n" + remaining
        if len(combined) <= _LINE_TEXT_LIMIT:
            messages[-1]["text"] = combined
        else:
            # Last resort: truncate at boundary with note
            messages[-1]["text"] = last_text

    return messages


async def reply_flex_message(
    reply_token: str,
    answer: str,
    sources: list[dict[str, Any]],
    channel_access_token: str,
):
    """Send answer as text messages (copyable, auto-split) + sources as Flex bubble."""
    # Fix #2: Dynamically allocate text slots based on whether sources exist
    max_text = _MAX_REPLY_MESSAGES - (1 if sources else 0)
    messages = _split_text_messages(answer, max_parts=max_text)

    if not messages and not sources:
        return  # Fix #1: Nothing to send

    # Add sources as a compact Flex bubble if room left
    if sources and len(messages) < _MAX_REPLY_MESSAGES:
        try:
            flex = _build_sources_flex(sources)
            if flex:
                messages.append(flex)
        except Exception:
            # Fix #5: Log instead of silently swallowing
            logger.warning("Failed to build sources flex bubble", exc_info=True)

    if messages:
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


def _build_sources_flex(sources: list[dict[str, Any]]) -> dict | None:
    """Build a compact Flex bubble showing source references with download links."""
    body_contents: list[dict] = [
        {
            "type": "text",
            "text": "📎 เอกสารอ้างอิง",
            "weight": "bold",
            "size": "sm",
            "color": "#555555",
        },
        {"type": "separator", "margin": "sm"},
    ]

    seen = set()
    for src in sources[:5]:
        name = src.get("filename") or src.get("source_filename") or src.get("source", "")
        if not name or name in seen:
            continue
        seen.add(name)

        page = src.get("page", "")
        label = name
        if page and page != "N/A":
            label += f" (p.{page})"

        link = src.get("download_link", "")
        # Fix #3: Validate URI scheme — LINE requires https:// or http://
        if link and not link.startswith(("https://", "http://")):
            link = ""

        confidence = src.get("confidence", "")
        badge = "✅" if confidence == "HIGH" else "⚠️" if confidence == "MEDIUM" else ""

        if link:
            body_contents.append({
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": f"{badge} {label}", "size": "xxs", "color": "#1a73e8", "wrap": True, "flex": 1, "action": {"type": "uri", "uri": link}},
                ],
                "margin": "sm",
            })
        else:
            body_contents.append({
                "type": "text",
                "text": f"{badge} {label}",
                "size": "xxs",
                "color": "#666666",
                "wrap": True,
                "margin": "sm",
            })

    # Fix #7: Don't return empty bubble (only header + separator, no sources)
    if len(body_contents) <= 2:
        return None

    return {
        "type": "flex",
        "altText": "📎 เอกสารอ้างอิง",
        "contents": {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": body_contents,
                "paddingAll": "12px",
            },
        },
    }
