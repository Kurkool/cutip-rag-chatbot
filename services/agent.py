"""Agentic RAG pipeline — Claude decides what tools to use and when."""

import logging
from functools import lru_cache

from anthropic import (
    APIStatusError,
    AuthenticationError,
    RateLimitError,
)
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from config import settings
from services.dependencies import format_history
from services.memory import conversation_memory
from services.tools import create_tools

logger = logging.getLogger(__name__)

AGENT_SYSTEM_PROMPT = """{persona}

You have tools to search the faculty's knowledge base and perform calculations.

## Core Rules
- ALWAYS search before answering faculty-related questions. If results are insufficient, search again with different keywords.
- Answer in the SAME LANGUAGE as the user's question (Thai → Thai, English → English).
- For greetings or casual chat, respond naturally WITHOUT searching.
- For math (tuition totals, GPA, credits), use the calculate tool.

## Search Result Confidence
- [HIGH CONFIDENCE]: Use directly — state information confidently.
- [MEDIUM]: Use but add a brief note like "จากข้อมูลที่พบ" (from available data).
- No results above threshold: Say honestly you couldn't find it. Suggest contacting faculty staff with specific contact info if available.

## Answer Quality — Be EXCEPTIONAL
Your goal is to make the user think "โอ้โห สุดยอด" — every answer should feel like talking to the most knowledgeable faculty advisor.

**Structure:** Use clear headers, numbered steps, and bullet points. Start with a brief overview, then details.

**Actionable links:** When search results contain download links for forms, templates, or documents, embed them INLINE in your answer using markdown format: [ชื่อเอกสาร](URL). This lets the user click and download immediately. This is CRITICAL — always include relevant download links from search results directly in your answer.

**Completeness:** Cover all steps/details found in search results. Don't omit steps to be brief.

**Conciseness:** Be thorough but not verbose. Every sentence should add value. Aim for 1500-3000 characters.

**Professional tone:** Formal but warm. Use emoji sparingly for visual structure (📋 📌 ✅), not decoration.

**End with next step:** Always close with what the user should do next, or offer to provide more details on a specific aspect.

## Do NOT add a references section
Source documents are displayed separately. Do NOT append "📎 เอกสารอ้างอิง" or any references section at the end. Focus your answer on actionable content with inline links.

## Conversation History
{history}"""


@lru_cache()
def _get_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.LLM_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=8192,
        max_retries=3,  # Auto-retry on 429 with exponential backoff
    )


async def run_agent(
    query: str,
    user_id: str,
    tenant: dict,
) -> tuple[str, list[dict]]:
    """
    Run the agentic RAG pipeline.
    Catches API errors (rate limit, auth, quota) and returns user-friendly messages.
    """
    namespace = tenant["pinecone_namespace"]
    persona = tenant.get("persona", "") or "You are a helpful university assistant."
    history = conversation_memory.get_history(user_id)

    tools, get_sources = create_tools(namespace)
    agent = create_react_agent(model=_get_llm(), tools=tools)

    system_prompt = AGENT_SYSTEM_PROMPT.format(
        persona=persona,
        history=format_history(history),
    )

    sources: list[dict] = []

    try:
        result = await agent.ainvoke({
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=query),
            ]
        })
        answer = result["messages"][-1].content
        sources = get_sources()

        # Track usage (fire-and-forget)
        from services.usage import track
        tid = tenant["tenant_id"]
        await track(tid, "llm_call")
        # Count tool invocations (each has tool_calls list), not tool results
        search_count = sum(
            len(m.tool_calls) for m in result["messages"]
            if hasattr(m, "tool_calls") and m.tool_calls
        )
        if search_count:
            await track(tid, "embedding_call", search_count)
            await track(tid, "reranker_call", search_count)

    except AuthenticationError:
        logger.error("Anthropic API key invalid or expired")
        answer = "ขออภัยค่ะ ระบบมีปัญหาด้านการยืนยันตัวตน กรุณาแจ้ง admin"
        sources = []

    except RateLimitError:
        logger.warning("Anthropic rate limit hit for tenant %s", tenant["tenant_id"])
        answer = "ขออภัยค่ะ ระบบมีผู้ใช้งานจำนวนมาก กรุณาลองใหม่ในอีกสักครู่"
        sources = []

    except APIStatusError as e:
        if "credit" in str(e).lower() or "quota" in str(e).lower():
            logger.error("Anthropic quota/credit exhausted: %s", e)
            answer = "ขออภัยค่ะ ระบบหมดโควต้าการใช้งานชั่วคราว กรุณาแจ้ง admin"
        else:
            logger.exception("Anthropic API error for tenant %s", tenant["tenant_id"])
            answer = "ขออภัยค่ะ เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่อีกครั้ง"
        sources = []

    except Exception:
        logger.exception("Agent execution failed for tenant %s", tenant["tenant_id"])
        answer = "ขออภัยค่ะ เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่อีกครั้ง"
        sources = []

    conversation_memory.add_turn(user_id, query, answer)
    return answer, sources
