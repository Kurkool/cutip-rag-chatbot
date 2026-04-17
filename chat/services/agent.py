"""Agentic RAG pipeline — Claude decides what tools to use and when."""

import logging

from anthropic import (
    APIStatusError,
    AuthenticationError,
    RateLimitError,
)
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent

from shared.config import settings
from shared.services.lang import is_thai as _is_thai
from shared.services.llm import get_opus
from shared.services.dependencies import format_history
from shared.services.usage import track as track_usage
from chat.services.memory import conversation_memory
from chat.services.tools import create_tools

logger = logging.getLogger(__name__)

# ──────────────────────────────────────
# System prompt — split for prompt caching
# ──────────────────────────────────────
# Static prefix = core rules, confidence tiers, answer-quality guidance.
# Tagged ``cache_control: ephemeral`` so once this prefix exceeds Anthropic's
# minimum cacheable size (4096 tokens on Opus 4.6/4.7), repeated requests
# read the cache at ~10% of base input price. Today it's ~700 tokens so the
# marker is a no-op; it becomes a real cost win if we expand instructions or
# add few-shot examples later.

_STATIC_SYSTEM_PROMPT = """You are the faculty's knowledgeable academic advisor. You have tools to search the knowledge base and perform math.

## When to Search (vs. Respond Directly)

**SEARCH when:** The question asks about anything specific to the faculty — tuition, courses, forms, schedules, admission, regulations, credits, instructors, policies, facilities, or program details. If unsure whether the KB has the answer — search.

**DO NOT SEARCH when:**
- Pure greetings with no topic: "สวัสดี" / "hello" / "หวัดดีครับ" → respond warmly, briefly offer to help.
- Thank-you / acknowledgment: "ขอบคุณค่ะ" / "thanks" → acknowledge warmly.
- Casual meta-chat about the bot itself: "คุณคือใคร" / "what can you do" → describe role briefly.

**MIXED (greeting + topic):** "สวัสดีค่ะ อยากถามเรื่องค่าเทอม" → ALWAYS search for the topic. The greeting is courtesy; the question is the intent.

**Follow-up searches:** If the first search is weak, search AGAIN with different keywords (synonyms, English terms, narrower scope). Don't give up after one try.

## Language Match
Answer in the SAME LANGUAGE as the user's question (Thai → Thai, English → English). This is strict. Even if search results are in Thai, if the user asked in English, translate naturally.

## Math Tool
For tuition totals, GPA, credit sums, year-over-year calculations — use the calculate tool. Don't do arithmetic in your head.

## Confidence Tiers (from search results)
- `[HIGH CONFIDENCE]` — State the information directly and confidently.
- `[MEDIUM - may not be exact match]` — Use with a soft framing: "จากข้อมูลที่พบ" / "Based on available information". Do NOT present it as definitive.
- `NO_RESULTS` marker or no chunks above threshold — Say honestly you couldn't find this specific information. Suggest contacting faculty staff (add specific contact info from persona if given).

## Answer Quality — The "โอ้โห" Standard

Your goal: make the user feel they got expert, actionable advice in under 10 seconds of reading.

### Structure (always)
1. **Lead with the answer.** First sentence directly addresses what they asked. No preamble like "Great question! Let me search for that..."
2. **Organize with visible structure.** Short headers (📋 หัวข้อ), numbered steps for procedures, bullet points for lists of requirements/options.
3. **End with a concrete next step.** "ต้องการรายละเอียดเพิ่มเติมเกี่ยวกับ X ไหมคะ?" or "Would you like details on Y next?"

### Inline download links (CRITICAL)
When search results contain `DOWNLOAD: https://...`, embed them as markdown INLINE in your answer:
- ✅ CORRECT: "กรอก [ใบคำขอทุน](https://drive.google.com/...) แล้วส่งที่สำนักทะเบียน"
- ❌ WRONG: Dumping the URL on its own line, or listing "References: …" at the end.

The user must be able to click and download without scrolling or hunting.

### Completeness vs. conciseness
- Cover every step/requirement the search returned — never skip to be brief.
- But every sentence should carry information. No filler ("As you may know…", "It's important to note…").
- Target 1500–3000 chars for procedural answers; 200–500 for simple factual lookups.

### Tone
Formal but warm. Use "ค่ะ / ครับ" naturally in Thai. Address the user with respect. Use emoji ONLY for visual structure: 📋 (list), 📌 (key point), ✅ (confirmed), 📥 (download), ⚠️ (caution). Never 😊 🎉 😂.

### Example of an exceptional answer

**User:** "ค่าเทอมหลักสูตร TIP เท่าไหร่"

**Exceptional response:**
```
ค่าเทอมหลักสูตร TIP อยู่ที่ **21,000 บาท/ภาคเรียน** ค่ะ (รวม 8 ภาค = 168,000 บาทตลอดหลักสูตร 4 ปี)

📋 **รายละเอียดการชำระ**
1. ชำระที่ [ธนาคาร X ผ่านใบแจ้งค่าเทอม](https://drive.google.com/file/d/xxx)
2. ช่วงเวลา: มีนาคม และ กันยายน ของทุกปี
3. ยื่นหลักฐานการชำระที่ระบบทะเบียนภายใน 7 วัน

📌 **กรณีขอผ่อนชำระ**
สามารถยื่นคำขอผ่อนได้ 2 งวดต่อภาคเรียน — ดาวน์โหลด [แบบฟอร์มขอผ่อนชำระ](https://drive.google.com/file/d/yyy)

ต้องการทราบเรื่องทุนการศึกษาหรือส่วนลดเพิ่มเติมไหมคะ?
```

Notice: direct answer first, visible structure, inline clickable links, offer next step. That's the bar.

## Do NOT add a references section
Source documents are displayed separately by the UI. Do NOT append "📎 เอกสารอ้างอิง" or any bibliography at the end. Keep the answer clean and actionable.
"""

_DYNAMIC_SUFFIX_TEMPLATE = """## Persona
{persona}

## Conversation History
{history}"""


_get_llm = get_opus  # Cached Claude Opus for agentic reasoning

# LangGraph's create_react_agent returns this hardcoded English string as the
# AIMessage content when `remaining_steps < 2` with pending tool_calls — it
# does NOT raise GraphRecursionError, so the existing except branch can't
# catch it. See langgraph.prebuilt.chat_agent_executor docstring.
# We match by prefix (not exact equality) so a minor wording change in a
# langgraph minor-version bump doesn't silently re-leak the English string.
_LANGGRAPH_STEPS_FALLBACK = "Sorry, need more steps to process this request."
_LANGGRAPH_STEPS_PREFIX = "Sorry, need more steps"


def _build_system_content(persona: str, history_text: str) -> list[dict]:
    """Build the system message as two blocks so the static prefix is cacheable.

    Block 1 (cacheable): core rules + confidence + answer quality guidance.
    Block 2 (per-request): persona + conversation history.
    """
    dynamic = _DYNAMIC_SUFFIX_TEMPLATE.format(persona=persona, history=history_text)
    return [
        {
            "type": "text",
            "text": _STATIC_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": dynamic},
    ]


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
    tenant_id = tenant["tenant_id"]
    persona = tenant.get("persona", "") or "You are a helpful university assistant."
    history = await conversation_memory.get_history(tenant_id, user_id)

    # History threads into the tools so follow-up queries can be rewritten
    # against conversation context before searching. user_id is threaded for
    # telemetry correlation. invalidate_ts is from the tenant doc — when it's
    # newer than the chat-api's cached BM25 warmed_ts, the search path
    # re-warms (cross-process ingest→chat invalidation).
    #
    # Defensive coercion: the Firestore field is written as a float by
    # _bump_bm25_invalidate_ts_sync, but an operator editing the doc in the
    # console could leave a string/bool. We fall back to 0 (= no invalidation)
    # rather than crashing the whole request.
    raw_ts = tenant.get("bm25_invalidate_ts")
    try:
        invalidate_ts = float(raw_ts) if raw_ts else 0.0
    except (TypeError, ValueError):
        logger.warning(
            "Invalid bm25_invalidate_ts for tenant %s: %r",
            tenant_id, raw_ts,
        )
        invalidate_ts = 0.0
    tools, get_sources = create_tools(
        namespace, history=history, user_id=user_id, invalidate_ts=invalidate_ts,
    )
    agent = create_react_agent(model=_get_llm(), tools=tools)

    system_content = _build_system_content(persona, format_history(history))

    sources: list[dict] = []

    try:
        result = await agent.ainvoke(
            {
                "messages": [
                    SystemMessage(content=system_content),
                    HumanMessage(content=query),
                ]
            },
            config={"recursion_limit": settings.AGENT_RECURSION_LIMIT},
        )
        # Opus 4.7 adaptive thinking returns content as a list of blocks
        # [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "..."}]
        # rather than a plain string. Concatenate text-type blocks; ignore
        # thinking blocks (internal reasoning is not user-facing).
        raw_content = result["messages"][-1].content
        if isinstance(raw_content, list):
            answer = "\n".join(
                b.get("text", "") for b in raw_content
                if isinstance(b, dict) and b.get("type") == "text"
            ).strip()
        else:
            answer = raw_content or ""
        hit_step_limit = answer.strip().startswith(_LANGGRAPH_STEPS_PREFIX)
        if hit_step_limit:
            logger.info(
                "agent hit LangGraph step-exhausted fallback tenant=%s user=%s query=%r",
                tenant_id, user_id[:8] if user_id else "", query[:80],
            )
        if not answer or hit_step_limit:
            # Match fallback language to the user's query so an English
            # speaker doesn't get a jarring Thai error (and vice versa).
            if hit_step_limit:
                answer = (
                    "ขออภัยค่ะ ค้นหาข้อมูลหลายรอบแล้วแต่ยังไม่พบคำตอบที่แน่ชัด "
                    "กรุณาลองถามใหม่ในรูปแบบอื่น หรือติดต่อเจ้าหน้าที่คณะ"
                    if _is_thai(query)
                    else "I searched multiple times but couldn't find a definitive answer. "
                    "Please try rephrasing, or contact faculty staff."
                )
            else:
                answer = (
                    "ขออภัยค่ะ ไม่สามารถสร้างคำตอบได้ กรุณาลองใหม่"
                    if _is_thai(query)
                    else "Sorry, I couldn't generate an answer. Please try again."
                )
        sources = get_sources()

        # Track usage (fire-and-forget)
        tid = tenant["tenant_id"]
        await track_usage(tid, "llm_call")
        # Count tool invocations (each has tool_calls list), not tool results
        search_count = sum(
            len(m.tool_calls) for m in result["messages"]
            if hasattr(m, "tool_calls") and m.tool_calls
        )
        if search_count:
            await track_usage(tid, "embedding_call", search_count)
            await track_usage(tid, "reranker_call", search_count)

            # Telemetry: flag queries where agent looped excessively.
            # Threshold is tunable via settings (default 5) — lower values
            # flood logs on legitimately-complex questions.
            if search_count >= settings.TELEMETRY_HIGH_TOOL_COUNT:
                logger.info(
                    "search_quality: high_tool_count=%d tenant=%s user=%s query=%r",
                    search_count, tid, user_id[:8] if user_id else "", query[:80],
                )

    except GraphRecursionError:
        logger.warning(
            "Agent hit recursion_limit=%d for tenant %s",
            settings.AGENT_RECURSION_LIMIT, tenant["tenant_id"],
        )
        answer = (
            "ขออภัยค่ะ ค้นหาข้อมูลหลายรอบแล้วแต่ยังไม่พบคำตอบที่แน่ชัด กรุณาติดต่อเจ้าหน้าที่คณะ"
            if _is_thai(query)
            else "I searched multiple times but couldn't find a definitive answer. Please contact faculty staff."
        )
        sources = []

    except AuthenticationError:
        logger.error("Anthropic API key invalid or expired")
        answer = (
            "ขออภัยค่ะ ระบบมีปัญหาด้านการยืนยันตัวตน กรุณาแจ้ง admin"
            if _is_thai(query)
            else "Sorry, the system has an authentication issue. Please notify the admin."
        )
        sources = []

    except RateLimitError:
        logger.warning("Anthropic rate limit hit for tenant %s", tenant["tenant_id"])
        answer = (
            "ขออภัยค่ะ ระบบมีผู้ใช้งานจำนวนมาก กรุณาลองใหม่ในอีกสักครู่"
            if _is_thai(query)
            else "Sorry, the system is experiencing high load. Please try again in a moment."
        )
        sources = []

    except APIStatusError as e:
        if "credit" in str(e).lower() or "quota" in str(e).lower():
            logger.error("Anthropic quota/credit exhausted: %s", e)
            answer = (
                "ขออภัยค่ะ ระบบหมดโควต้าการใช้งานชั่วคราว กรุณาแจ้ง admin"
                if _is_thai(query)
                else "Sorry, the system has temporarily run out of quota. Please notify the admin."
            )
        else:
            logger.exception("Anthropic API error for tenant %s", tenant["tenant_id"])
            answer = (
                "ขออภัยค่ะ เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่อีกครั้ง"
                if _is_thai(query)
                else "Sorry, a system error occurred. Please try again."
            )
        sources = []

    except Exception:
        logger.exception("Agent execution failed for tenant %s", tenant["tenant_id"])
        answer = (
            "ขออภัยค่ะ เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่อีกครั้ง"
            if _is_thai(query)
            else "Sorry, a system error occurred. Please try again."
        )
        sources = []

    await conversation_memory.add_turn(tenant_id, user_id, query, answer)
    return answer, sources
