"""LINE webhook and standalone chat endpoints."""

import json
import logging
import time
from collections import OrderedDict, defaultdict
from threading import Lock
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from shared.schemas import ChatRequest, ChatResponse
from shared.services import firestore as firestore_service
from shared.services.auth import check_tenant_access, get_current_user
from chat.services.agent import run_agent
from shared.services.dependencies import get_tenant_or_404
from chat.services.line import parse_text_events, reply_flex_message, reply_message, verify_signature
from shared.services.rate_limit import chat_limit, limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["LINE Webhook"])

_ANON_PREFIX = "anon"

# Webhook rate limit ceiling: high enough not to throttle normal LINE edge
# traffic (shared IPs across customers), low enough to stop a burst DoS.
_WEBHOOK_RATE_LIMIT = "600/minute"

# In-memory TTL dedup for webhookEventId. LINE retries failed deliveries, so
# without dedup a single user message can summarize twice, double-log, and
# double-charge usage. 5 minutes covers the retry window.
_DEDUP_TTL_SECONDS = 300
_dedup_lock = Lock()
_dedup_cache: "OrderedDict[str, float]" = OrderedDict()

# Per-tenant rate limit (post-identify). The route-level 600/min is keyed on
# LINE's edge IP (shared across every LINE customer), so one tenant's spam
# would throttle everyone. This secondary check runs AFTER we identify the
# tenant from the LINE destination and is keyed by tenant_id — a noisy
# cutip_01 cannot starve cutip_02 or cutip_03.
#
# Sliding-window counter: bucket holds timestamps of recent messages; entries
# older than the window are evicted each call. Limit tuned for LINE-OA
# realistic burst (even a noisy classroom rarely exceeds 30/min).
_TENANT_WEBHOOK_WINDOW_SECONDS = 60.0
_TENANT_WEBHOOK_LIMIT_PER_WINDOW = 60  # messages per minute per tenant
_tenant_rate_lock = Lock()
_tenant_rate_buckets: dict[str, list[float]] = defaultdict(list)


def _default_user_id(tenant_id: str) -> str:
    """Namespace anonymous callers per-tenant so /api/chat without user_id
    cannot accidentally share conversation memory across tenants.
    """
    return f"{_ANON_PREFIX}_{tenant_id}"


def _is_duplicate_event(event_id: str) -> bool:
    """Return True if this webhookEventId was seen within the TTL window."""
    if not event_id:
        return False
    now = time.time()
    with _dedup_lock:
        # Evict expired entries (bounded-time because OrderedDict is ordered by insertion)
        while _dedup_cache:
            oldest_key, oldest_ts = next(iter(_dedup_cache.items()))
            if now - oldest_ts < _DEDUP_TTL_SECONDS:
                break
            _dedup_cache.popitem(last=False)
        if event_id in _dedup_cache:
            return True
        _dedup_cache[event_id] = now
    return False


def _tenant_rate_check(tenant_id: str) -> bool:
    """Sliding-window rate check for one tenant. True = within limit, False = exceeded."""
    if not tenant_id:
        return True  # defensive: shouldn't happen post-identify, don't block
    now = time.time()
    window_start = now - _TENANT_WEBHOOK_WINDOW_SECONDS
    with _tenant_rate_lock:
        bucket = _tenant_rate_buckets[tenant_id]
        # Evict stale entries (sorted-by-insertion → trim-from-left once)
        while bucket and bucket[0] < window_start:
            bucket.pop(0)
        if len(bucket) >= _TENANT_WEBHOOK_LIMIT_PER_WINDOW:
            return False
        bucket.append(now)
    return True
from shared.services.lang import is_thai

ERROR_REPLY_THAI = "ขออภัยค่ะ เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่อีกครั้ง"
ERROR_REPLY_ENGLISH = "Sorry, a system error occurred. Please try again."


def _error_reply_for(query: str) -> str:
    """Match the webhook error fallback to the user's query language so an
    English-speaking user doesn't get a jarring Thai message during demo.
    """
    return ERROR_REPLY_THAI if is_thai(query) else ERROR_REPLY_ENGLISH


# ──────────────────────────────────────
# Endpoints
# ──────────────────────────────────────

@router.post("/webhook/line")
@limiter.limit(_WEBHOOK_RATE_LIMIT)
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
        if _is_duplicate_event(event.get("webhook_event_id", "")):
            logger.info(
                "[%s] dropping duplicate webhookEventId=%s",
                tenant["tenant_id"], event.get("webhook_event_id"),
            )
            continue
        # Per-tenant rate shield (after dedup so retries don't waste a slot)
        if not _tenant_rate_check(tenant["tenant_id"]):
            logger.warning(
                "[%s] tenant rate limit exceeded (>%d/min), dropping message from user=%s",
                tenant["tenant_id"], _TENANT_WEBHOOK_LIMIT_PER_WINDOW,
                event.get("user_id", "")[:8],
            )
            # Silent drop: no reply to user since replying would also cost API.
            # Tenant admin will see the WARNING in Cloud Logging.
            continue
        await _handle_message_event(event, tenant)

    return {"status": "ok"}


@router.post("/api/chat", response_model=ChatResponse, tags=["Chat"])
@limiter.limit(chat_limit)
async def chat(
    request: Request,
    body: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """Standalone chat endpoint for testing or n8n integration.

    Requires Firebase bearer token or admin API key. tenant_id in the body
    must be one the caller is authorized for (super_admin / API-key: any;
    faculty_admin: only their assigned tenants).
    """
    if not body.tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    check_tenant_access(current_user, body.tenant_id)

    tenant = await get_tenant_or_404(body.tenant_id)
    user_id = body.user_id or _default_user_id(body.tenant_id)

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
        await reply_message(event["reply_token"], _error_reply_for(query), token)

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
