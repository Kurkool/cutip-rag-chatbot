"""Tenant-scoped tools for the agentic chatbot."""

import ast
import logging
import operator
from typing import Callable

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

def create_tools(
    namespace: str,
    history: list | dict | None = None,
    user_id: str | None = None,
    invalidate_ts: float = 0.0,
) -> tuple[list, Callable[[], list[dict]]]:
    """Create tools scoped to a tenant's Pinecone namespace.

    ``history`` is threaded into the search tools so they can rewrite
    follow-up queries with conversation context before searching.
    ``user_id`` is threaded for telemetry correlation only (does not affect
    retrieval).
    ``invalidate_ts`` is the tenant's bm25_invalidate_ts from Firestore —
    when the cached BM25 index is older than this, search re-warms from
    Pinecone. This is how cross-process (ingest → chat) invalidation works.
    Returns (tools, get_sources).
    """
    collected_sources: list[dict] = []  # Per-request, not global

    @tool
    async def search_knowledge_base(query: str) -> str:
        """Search the faculty's entire knowledge base (all document types).

        Use this when you don't know which document category the answer lives
        in, or for broad topics spanning multiple types. Call this multiple
        times with different keywords (English variants, Thai synonyms,
        narrower scope) if the first search returns weak results — don't give
        up after one try.

        Returns formatted chunks tagged with confidence tiers and markdown
        download links when available. Embed those links inline in your
        final answer.
        """
        try:
            from chat.services.search import search_with_sources
            result, sources = await search_with_sources(
                query, namespace, history=history, user_id=user_id,
                invalidate_ts=invalidate_ts,
            )
            collected_sources.extend(sources)
            return result
        except Exception as e:
            logger.exception("search_knowledge_base failed")
            return f"Search error: {type(e).__name__} — {e}"

    @tool
    async def search_by_category(query: str, category: str) -> str:
        """Search the knowledge base filtered to a specific document category.

        Use this when you ALREADY know which type of document contains the
        answer — it's faster and more precise than search_knowledge_base
        because irrelevant categories are filtered out server-side.

        Category → When to use:
        - "curriculum": tuition, fees, course structure, credit requirements, GPA rules
        - "form": application forms, enrollment, withdrawal, scholarship applications
        - "announcement": deadlines, events, policy changes, news
        - "schedule": class times, exam dates, academic calendar
        - "regulation": academic rules, policies, conduct standards
        - "general": catch-all for anything not matching the above

        Examples:
        - search_by_category("ค่าเทอม", "curriculum")
        - search_by_category("ใบลาพักการเรียน", "form")
        - search_by_category("กำหนดการสอบปลายภาค", "schedule")

        If your first category guess returns weak results, try
        search_knowledge_base instead — the answer may live in a different
        category than expected.
        """
        try:
            from chat.services.search import search_with_sources
            result, sources = await search_with_sources(
                query, namespace, category=category, history=history, user_id=user_id,
                invalidate_ts=invalidate_ts,
            )
            collected_sources.extend(sources)
            return result
        except Exception as e:
            logger.exception("search_by_category failed")
            return f"Search error: {type(e).__name__} — {e}"

    @tool
    def calculate(expression: str) -> str:
        """Evaluate a math expression safely. Use for tuition totals, GPA calculations,
        credit sums, or any numeric computation.
        Examples: '21000 * 8', '(3.5 + 4.0) / 2', '144 - 36'"""
        try:
            result = _safe_eval(ast.parse(expression, mode="eval").body)
            return str(result)
        except Exception as e:
            return f"Calculation error: {e}"

    @tool
    async def fetch_webpage(url: str) -> str:
        """Fetch and read a web page as plain text.

        Use ONLY when the search result text is incomplete and explicitly
        references an external page (e.g., "see details at https://..."). Do
        NOT call this for every search result that contains a download_link
        — for downloadable PDFs, forms, or documents, embed the INLINE_LINK
        markdown in your final answer so the user can click and open it
        directly. Calling this tool on every link wastes steps and slows the
        response during a demo.

        Times out at 8 seconds — if the page is slow or dead, tell the user
        to open the document via the download link instead.
        """
        import httpx
        if not url.startswith(("http://", "https://")):
            return "Only http(s) URLs are supported."
        try:
            # 8s timeout: fail fast to avoid a 15s demo hang on slow/dead URLs.
            # If the user really needs the page content, they can click the
            # download link directly instead.
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(
                    f"https://r.jina.ai/{url}",
                    headers={"Accept": "text/plain"},
                )
                response.raise_for_status()
                return response.text[:3000]
        except Exception as exc:
            logger.info("fetch_webpage failed for %s: %s", url, exc)
            return (
                "Couldn't load that page in time. Tell the user to click "
                "the download link in the previous answer to access the "
                "document directly."
            )

    def get_sources() -> list[dict]:
        """Return sources collected during this request's tool calls."""
        return list(collected_sources)

    return [search_knowledge_base, search_by_category, calculate, fetch_webpage], get_sources


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return _SAFE_OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")
