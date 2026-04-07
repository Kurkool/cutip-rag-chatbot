"""LINE webhook and standalone chat endpoints."""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from schemas import ChatRequest, ChatResponse
from services import firestore as firestore_service
from services.agent import run_agent
from services.dependencies import get_tenant_or_404
from services.line import parse_text_events, reply_flex_message, reply_message, verify_signature

logger = logging.getLogger(__name__)

router = APIRouter(tags=["LINE Webhook"])


# ──────────────────────────────────────
# Endpoints
# ──────────────────────────────────────

@router.post("/webhook/line")
async def line_webhook(request: Request):
    """Receive LINE events, identify tenant, run agentic RAG, reply."""
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")
    payload = _parse_payload(body)
    tenant = await _identify_tenant(payload)
    _verify_request(body, signature, tenant)

    for event in parse_text_events(payload):
        await _handle_message_event(event, tenant)

    return {"status": "ok"}


@router.post("/api/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(request: ChatRequest):
    """Standalone chat endpoint for testing or n8n integration."""
    if not request.tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    tenant = await get_tenant_or_404(request.tenant_id)
    answer = await run_agent(
        query=request.query,
        user_id=request.user_id or "anonymous",
        tenant=tenant,
    )

    # Log to Firestore
    await firestore_service.log_chat(
        tenant["tenant_id"], request.user_id or "anonymous",
        request.query, answer, [],
    )

    return ChatResponse(answer=answer, sources=[])


# ──────────────────────────────────────
# LINE webhook helpers
# ──────────────────────────────────────

def _parse_payload(body: bytes) -> dict:
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")


async def _identify_tenant(payload: dict) -> dict[str, Any]:
    destination = payload.get("destination")
    if not destination:
        raise HTTPException(status_code=400, detail="Missing destination")

    tenant = await firestore_service.get_tenant_by_destination(destination)
    if not tenant:
        logger.warning("Unknown LINE destination: %s", destination)
        raise HTTPException(status_code=404, detail="Unknown LINE destination")
    return tenant


def _verify_request(body: bytes, signature: str, tenant: dict):
    if not verify_signature(body, signature, tenant["line_channel_secret"]):
        raise HTTPException(status_code=403, detail="Invalid signature")


async def _handle_message_event(event: dict, tenant: dict):
    token = tenant["line_channel_access_token"]
    try:
        answer = await run_agent(
            query=event["text"],
            user_id=event["user_id"],
            tenant=tenant,
        )

        # Log to Firestore
        await firestore_service.log_chat(
            tenant["tenant_id"], event["user_id"],
            event["text"], answer, [],
        )

        await reply_flex_message(event["reply_token"], answer, [], token)
    except Exception:
        logger.exception("Error processing message for tenant %s", tenant["tenant_id"])
        await reply_message(
            event["reply_token"],
            "ขออภัยค่ะ เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่อีกครั้ง",
            token,
        )
