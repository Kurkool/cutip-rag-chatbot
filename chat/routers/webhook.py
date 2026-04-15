"""LINE webhook and standalone chat endpoints."""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from shared.schemas import ChatRequest, ChatResponse
from shared.services import firestore as firestore_service
from chat.services.agent import run_agent
from shared.services.dependencies import get_tenant_or_404
from chat.services.line import parse_text_events, reply_flex_message, reply_message, verify_signature
from shared.services.rate_limit import chat_limit, limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["LINE Webhook"])

DEFAULT_USER_ID = "anonymous"
ERROR_REPLY_THAI = "ขออภัยค่ะ เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่อีกครั้ง"


# ──────────────────────────────────────
# Endpoints
# ──────────────────────────────────────

@router.post("/webhook/line")
async def line_webhook(request: Request):
    """Receive LINE events, identify tenant, run agentic RAG, reply."""
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")
    payload = _parse_payload(body)

    if not payload.get("destination") or not payload.get("events"):
        return {"status": "ok"}

    tenant = await _identify_tenant(payload)
    _verify_request(body, signature, tenant)

    for event in parse_text_events(payload):
        await _handle_message_event(event, tenant)

    return {"status": "ok"}


@router.post("/api/chat", response_model=ChatResponse, tags=["Chat"])
@limiter.limit(chat_limit)
async def chat(request: Request, body: ChatRequest):
    """Standalone chat endpoint for testing or n8n integration."""
    if not body.tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    tenant = await get_tenant_or_404(body.tenant_id)
    user_id = body.user_id or DEFAULT_USER_ID

    answer, sources = await run_agent(query=body.query, user_id=user_id, tenant=tenant)

    await firestore_service.log_chat(
        tenant["tenant_id"], user_id, body.query, answer, sources,
    )

    return ChatResponse(answer=answer, sources=sources)


# ──────────────────────────────────────
# Helpers
# ──────────────────────────────────────

def _parse_payload(body: bytes) -> dict[str, Any]:
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")


async def _identify_tenant(payload: dict[str, Any]) -> dict[str, Any]:
    destination = payload.get("destination")
    if not destination:
        raise HTTPException(status_code=400, detail="Missing destination")

    tenant = await firestore_service.get_tenant_by_destination(destination)
    if not tenant:
        logger.warning("Unknown LINE destination: %s", destination)
        raise HTTPException(status_code=404, detail="Unknown LINE destination")
    return tenant


def _verify_request(body: bytes, signature: str, tenant: dict[str, Any]) -> None:
    if not verify_signature(body, signature, tenant["line_channel_secret"]):
        raise HTTPException(status_code=403, detail="Invalid signature")


async def _handle_message_event(event: dict[str, Any], tenant: dict[str, Any]) -> None:
    token = tenant["line_channel_access_token"]
    tenant_id = tenant["tenant_id"]
    user_id = event["user_id"]
    query = event["text"]

    logger.info("[%s] user=%s query='%s'", tenant_id, user_id[:8], query[:50])

    try:
        answer, sources = await run_agent(query=query, user_id=user_id, tenant=tenant)
        await firestore_service.log_chat(tenant_id, user_id, query, answer, sources)
        await reply_flex_message(event["reply_token"], answer, sources, token)
        logger.info("[%s] replied %d chars", tenant_id, len(answer))

    except Exception as exc:
        logger.exception("[%s] FAILED for user=%s query='%s'", tenant_id, user_id[:8], query[:50])
        await reply_message(event["reply_token"], ERROR_REPLY_THAI, token)

        try:
            from shared.services.notifications import alert_error
            await alert_error(
                "Chat Error",
                f"`{type(exc).__name__}`: {str(exc)[:200]}",
                Tenant=tenant_id,
                Query=query[:100],
            )
        except Exception:
            logger.warning("Failed to send Slack alert", exc_info=True)
