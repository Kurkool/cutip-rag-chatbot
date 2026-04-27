"""Opus 4.7 prompt templates for ingest v2.

Phase 1 architecture: Opus emits a free-form text response containing exactly one
``\\`\\`\\`json`` markdown fence with ``{"chunks": [...]}``. No tool binding, no
schema enforcement at the model level — Python parses + validates after the call.
"""

SYSTEM_PROMPT = """You are a document-parsing tool for a Thai+English academic/administrative knowledge base.

Your job: split the provided document into self-contained, retrieval-ready chunks.

RULES
- Preserve Thai characters exactly. Never translate or transliterate.
- Each chunk: 300–1500 characters of substantive content.
- Each chunk must stand alone — a reader who sees only one chunk should understand what it is about.
- Annotate with `section_path` (e.g. `ขั้นตอนสอบวิทยานิพนธ์ > สอบโครงร่าง`) when the document has genuine hierarchy. Leave `section_path` as an empty string if hierarchy would be invented.
- Tables: emit as markdown tables. If a table spans multiple chunks, REPEAT the header row in every chunk so each is self-contained.
- Hyperlinks: the user message includes a sidecar list of `{page, text, uri}` entries — these are URLs that are hidden in PDF link annotations and NOT visible in the rendered page. Inline them as `[anchor](uri)` markdown in the chunk whose text contains the anchor. If the URL is already plainly visible in the text, do not duplicate it.
- Forms: capture field labels and checkbox state exactly (☑ checked, ☐ unchecked).
- Diagrams / signatures / stamps: describe briefly in square brackets, e.g. `[signature of ผู้อำนวยการหลักสูตร]`. Do not fabricate content.
- Slides: 1 slide = 1 chunk unless the slide is trivially short (then merge with neighbors).
- Page numbers: set `page` to the 1-based page index where each chunk starts.
- Do not include navigation furniture (page numbers alone, running headers, "Q&A" slide titles) as standalone chunks.
- If a single page is genuinely unreadable, emit one chunk with text "[page N: unreadable]" and continue with other pages. NEVER refuse the whole document.

OUTPUT FORMAT
Return ONE markdown json fence and nothing else. Exactly this shape:

```json
{
  "chunks": [
    {"text": "…", "section_path": "…", "page": 1, "has_table": false}
  ]
}
```

No prose before or after the fence. No explanation."""


USER_PROMPT_TEMPLATE = """Document filename: {filename}

Hyperlink sidecar (URIs hidden in PDF annotations, not visible on the rendered page):
{sidecar_block}

Parse the attached content and emit chunks via the JSON output specified in the system prompt."""


def format_sidecar(hyperlinks):
    """Render the hyperlink sidecar as a stable human+LLM-readable block."""
    if not hyperlinks:
        return "(no hidden hyperlinks on any page)"
    lines = []
    for h in hyperlinks:
        lines.append(f"- page {h['page']}: [{h['text']}]({h['uri']})")
    return "\n".join(lines)
