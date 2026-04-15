"""Contextual enrichment: prepend LLM-generated section context to each chunk."""

import asyncio
import logging
import re

from langchain_core.documents import Document

from shared.config import settings  # noqa: F401 — kept for symmetry / future use
from shared.services.llm import get_haiku_precise

logger = logging.getLogger(__name__)

# ──────────────────────────────────────
# Contextual Retrieval (Anthropic Research)
# ──────────────────────────────────────

_SECTION_CONTEXT_PROMPT = (
    "<document_section title=\"{section_title}\">\n{section_text}\n</document_section>\n\n"
    "<chunk>\n{chunk}\n</chunk>\n\n"
    "Write 1-2 sentences explaining what this chunk is about within its section. "
    "Include the section topic and what specific information this chunk contains. "
    "Respond in the same language as the document. Reply with ONLY the context."
)

_GLOBAL_CONTEXT_PROMPT = (
    "Here is the document:\n<document>\n{document}\n</document>\n\n"
    "<chunk>\n{chunk}\n</chunk>\n\n"
    "Write a short 1-2 sentence context in the SAME LANGUAGE as the document "
    "that explains where this chunk fits. Reply with ONLY the context."
)


def _build_section_map(text: str) -> list[dict]:
    """Parse markdown headers to build section map with positions and text.

    Returns a list of dicts with keys: title, start, end, text.
    If no headers found, returns a single 'Document' section covering all text.
    """
    lines = text.splitlines(keepends=True)
    sections: list[dict] = []
    current_title: str | None = None
    current_start: int = 0
    pos: int = 0

    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            # Detect markdown header (# Title, ## Subtitle, etc.)
            header_match = re.match(r"^(#+)\s+(.*)", stripped)
            if header_match:
                if current_title is not None:
                    # Close previous section
                    sections.append({
                        "title": current_title,
                        "start": current_start,
                        "end": pos,
                        "text": text[current_start:pos][:3000],
                    })
                current_title = header_match.group(2).strip()
                current_start = pos
        pos += len(line)

    # Close last section
    if current_title is not None:
        sections.append({
            "title": current_title,
            "start": current_start,
            "end": len(text),
            "text": text[current_start:len(text)][:3000],
        })

    # No headers found → single fallback section
    if not sections:
        return [{"title": "Document", "start": 0, "end": len(text), "text": text[:3000]}]

    return sections


def _find_section_for_chunk(sections: list[dict], chunk_text: str, full_text: str) -> dict:
    """Find which section a chunk belongs to by position matching.

    Locates the chunk in full_text, then returns the section whose start
    is <= the chunk position (reverse search for the last matching section).
    Falls back to the first section if the chunk is not found in full_text.
    """
    pos = full_text.find(chunk_text[:60]) if len(chunk_text) >= 60 else full_text.find(chunk_text)
    if pos == -1:
        return sections[0]

    # Walk backwards through sections to find the one that owns this position
    result = sections[0]
    for section in sections:
        if section["start"] <= pos:
            result = section
        else:
            break
    return result


async def _enrich_with_context(
    chunks: list[Document], full_text: str
) -> list[Document]:
    """Prepend section-level context to each chunk (~49% retrieval improvement).

    When the document has markdown headers, each chunk is enriched with
    context from its owning section. Otherwise, a global document context
    is used (first 4000 chars).
    """
    if not chunks:
        return chunks

    sections = _build_section_map(full_text)
    use_sections = len(sections) > 1 or sections[0]["title"] != "Document"

    llm = get_haiku_precise()

    for i, chunk in enumerate(chunks):
        if i > 0 and i % 10 == 0:
            await asyncio.sleep(1)  # Rate limit: pause every 10 chunks
        try:
            if use_sections:
                section = _find_section_for_chunk(sections, chunk.page_content, full_text)
                prompt = _SECTION_CONTEXT_PROMPT.format(
                    section_title=section["title"],
                    section_text=section["text"],
                    chunk=chunk.page_content,
                )
            else:
                doc_summary = full_text[:4000]
                prompt = _GLOBAL_CONTEXT_PROMPT.format(
                    document=doc_summary,
                    chunk=chunk.page_content,
                )
            context = await llm.ainvoke(prompt)
            chunk.page_content = f"[{context.content.strip()}]\n{chunk.page_content}"
        except Exception:
            logger.warning("Failed to generate context for chunk, skipping")

    return chunks
