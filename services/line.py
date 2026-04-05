import hashlib
import hmac
import base64
import json
from typing import Any

import httpx

LINE_API_URL = "https://api.line.me/v2/bot/message/reply"


def verify_signature(body: bytes, signature: str, channel_secret: str) -> bool:
    """ตรวจสอบ X-Line-Signature ตาม LINE Messaging API spec"""
    hash_value = hmac.new(
        channel_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(hash_value).decode("utf-8")
    return hmac.compare_digest(signature, expected)


def parse_text_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """ดึงเฉพาะ text message events จาก LINE webhook payload"""
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
    """ส่งข้อความตอบกลับแบบ plain text"""
    async with httpx.AsyncClient() as client:
        await client.post(
            LINE_API_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {channel_access_token}",
            },
            json={
                "replyToken": reply_token,
                "messages": [{"type": "text", "text": text[:5000]}],
            },
        )


async def reply_flex_message(
    reply_token: str,
    answer: str,
    sources: list[dict[str, Any]],
    channel_access_token: str,
):
    """
    ส่ง Flex Message แบบ rich card พร้อมคำตอบและแหล่งอ้างอิง
    ถ้าสร้าง Flex ไม่สำเร็จ จะ fallback เป็น plain text
    """
    try:
        messages = [_build_flex_message(answer, sources)]
    except Exception:
        # Fallback to plain text
        messages = [{"type": "text", "text": answer[:5000]}]

    async with httpx.AsyncClient() as client:
        await client.post(
            LINE_API_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {channel_access_token}",
            },
            json={
                "replyToken": reply_token,
                "messages": messages,
            },
        )


def _build_flex_message(answer: str, sources: list[dict[str, Any]]) -> dict:
    """สร้าง LINE Flex Message bubble พร้อมคำตอบและอ้างอิง"""
    # Truncate answer for Flex (LINE limit)
    display_answer = answer[:2000]

    body_contents = [
        {
            "type": "text",
            "text": display_answer,
            "wrap": True,
            "size": "sm",
            "color": "#333333",
        }
    ]

    # Add source references
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
