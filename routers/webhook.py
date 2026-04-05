"""LINE webhook and standalone chat endpoints."""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from config import settings
from schemas import ChatRequest, ChatResponse
from services import firestore as firestore_service
from services.dependencies import format_history, get_tenant_or_404
from services.line import parse_text_events, reply_flex_message, reply_message, verify_signature
from services.memory import conversation_memory
from services.rag_chain import create_rag_chain, get_query_condenser
from services.reranker import rerank_documents
from services.vectorstore import get_vectorstore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["LINE Webhook"])


# ──────────────────────────────────────
# Endpoints
# ──────────────────────────────────────

@router.post("/webhook/line")
async def line_webhook(request: Request):
    """Receive LINE events, identify tenant, run RAG, reply via Flex Message."""
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
    answer, sources = await run_rag_pipeline(
        query=request.query,
        user_id=request.user_id or "anonymous",
        tenant=tenant,
    )
    return ChatResponse(answer=answer, sources=sources)


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
        answer, sources = await run_rag_pipeline(
            query=event["text"],
            user_id=event["user_id"],
            tenant=tenant,
        )
        await reply_flex_message(event["reply_token"], answer, sources, token)
    except Exception:
        logger.exception("Error processing message for tenant %s", tenant["tenant_id"])
        await reply_message(
            event["reply_token"],
            "ขออภัยค่ะ เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่อีกครั้ง",
            token,
        )


# ──────────────────────────────────────
# RAG pipeline (broken into steps)
# ──────────────────────────────────────

async def run_rag_pipeline(
    query: str, user_id: str, tenant: dict
) -> tuple[str, list[dict]]:
    """Full RAG pipeline: condense → search → rerank → generate → log."""
    namespace = tenant["pinecone_namespace"]
    persona = tenant.get("persona", "")
    history = conversation_memory.get_history(user_id)

    search_query = await _condense_query(query, history)
    docs = await _retrieve(search_query, namespace)

    if not docs:
        return "ขออภัยค่ะ ยังไม่มีข้อมูลในระบบ กรุณานำเข้าเอกสารก่อน", []

    reranked = rerank_documents(search_query, docs, top_k=settings.TOP_K)
    answer = await _generate(query, reranked, history, persona)
    sources = _extract_sources(reranked)

    conversation_memory.add_turn(user_id, query, answer)
    await firestore_service.log_chat(
        tenant["tenant_id"], user_id, query, answer, sources
    )
    return answer, sources


async def _condense_query(query: str, history: list[dict]) -> str:
    """Rewrite follow-up questions into standalone queries."""
    if not history:
        return query
    condenser = get_query_condenser()
    return await condenser.ainvoke({
        "history": format_history(history),
        "query": query,
    })


async def _retrieve(query: str, namespace: str):
    """Semantic search in the tenant's Pinecone namespace."""
    vectorstore = get_vectorstore(namespace)
    return await vectorstore.asimilarity_search(query, k=settings.RETRIEVAL_K)


async def _generate(
    query: str,
    docs: list,
    history: list[dict],
    persona: str,
) -> str:
    """Generate an answer using Claude with tenant persona."""
    context = "\n\n---\n\n".join(doc.page_content for doc in docs)
    chain, system_prompt = create_rag_chain(persona)
    return await chain.ainvoke({
        "persona": system_prompt,
        "context": context,
        "history": format_history(history),
        "query": query,
    })


def _extract_sources(docs: list) -> list[dict]:
    """Build source reference list from reranked documents."""
    return [
        {
            "page": doc.metadata.get("page", "N/A"),
            "source": doc.metadata.get(
                "source_filename", doc.metadata.get("source", "N/A")
            ),
            "source_filename": doc.metadata.get("source_filename", ""),
        }
        for doc in docs
    ]
