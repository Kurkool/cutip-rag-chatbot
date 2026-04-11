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

## Instructions
- ALWAYS use search_knowledge_base before answering questions about the faculty.
- If the first search doesn't return enough info, search again with different keywords.
- For questions involving math (total tuition, GPA, credits), use the calculate tool.
- If you truly cannot find the answer after searching, say so honestly and suggest contacting faculty staff.
- Answer in the SAME LANGUAGE as the user's question (Thai → Thai, English → English).
- Cite which source document you used (e.g. "ตามเอกสาร curriculum.pdf").
- Be concise, polite, and helpful.
- For greetings or casual conversation, respond naturally WITHOUT searching.

## Conversation History
{history}"""


@lru_cache()
def _get_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.LLM_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=2048,
        max_retries=3,  # Auto-retry on 429 with exponential backoff
    )


async def run_agent(
    query: str,
    user_id: str,
    tenant: dict,
) -> str:
    """
    Run the agentic RAG pipeline.
    Catches API errors (rate limit, auth, quota) and returns user-friendly messages.
    """
    namespace = tenant["pinecone_namespace"]
    persona = tenant.get("persona", "") or "You are a helpful university assistant."
    history = conversation_memory.get_history(user_id)

    tools = create_tools(namespace)
    agent = create_react_agent(model=_get_llm(), tools=tools)

    system_prompt = AGENT_SYSTEM_PROMPT.format(
        persona=persona,
        history=format_history(history),
    )

    try:
        result = await agent.ainvoke({
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=query),
            ]
        })
        answer = result["messages"][-1].content

    except AuthenticationError:
        logger.error("Anthropic API key invalid or expired")
        answer = "ขออภัยค่ะ ระบบมีปัญหาด้านการยืนยันตัวตน กรุณาแจ้ง admin"

    except RateLimitError:
        logger.warning("Anthropic rate limit hit for tenant %s", tenant["tenant_id"])
        answer = "ขออภัยค่ะ ระบบมีผู้ใช้งานจำนวนมาก กรุณาลองใหม่ในอีกสักครู่"

    except APIStatusError as e:
        if "credit" in str(e).lower() or "quota" in str(e).lower():
            logger.error("Anthropic quota/credit exhausted: %s", e)
            answer = "ขออภัยค่ะ ระบบหมดโควต้าการใช้งานชั่วคราว กรุณาแจ้ง admin"
        else:
            logger.exception("Anthropic API error for tenant %s", tenant["tenant_id"])
            answer = "ขออภัยค่ะ เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่อีกครั้ง"

    except Exception:
        logger.exception("Agent execution failed for tenant %s", tenant["tenant_id"])
        answer = "ขออภัยค่ะ เกิดข้อผิดพลาดในระบบ กรุณาลองใหม่อีกครั้ง"

    conversation_memory.add_turn(user_id, query, answer)
    return answer
