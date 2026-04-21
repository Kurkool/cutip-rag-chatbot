"""Opus 4.7 prompt + tool schema for ingest v2.

Kept in a separate module so prompt tuning does not churn the main
pipeline file. The schema is the single source of truth for what
``opus_parse_and_chunk`` returns.
"""

SYSTEM_PROMPT = """You are a document-parsing tool for a Thai+English academic/administrative knowledge base.

Your job: split the provided document into self-contained, retrieval-ready chunks and call the `record_chunks` tool with the result.

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

OUTPUT
Call the `record_chunks` tool exactly once with the full chunk list. Do not respond with any other text."""

USER_PROMPT_TEMPLATE = """Document filename: {filename}

Hyperlink sidecar (URIs hidden in PDF annotations, not visible on the rendered page):
{sidecar_block}

OCR sidecar:
{ocr_block}

Parse the attached PDF and emit chunks via the `record_chunks` tool."""

USER_PROMPT_TEMPLATE_TEXT_ONLY = """Document filename: {filename}

The document below has been pre-OCR'd; no PDF is attached. Use the text as the sole source of truth and produce chunks via the `record_chunks` tool.

Page boundaries are marked with `### Page N` — use them to set each chunk's `page` field.

Hyperlink sidecar (URIs hidden in PDF annotations, not visible on the rendered page):
{sidecar_block}

{page_text_block}
"""


CHUNK_TOOL_SCHEMA = {
    "name": "record_chunks",
    "description": (
        "Record the parsed document as a list of retrieval-ready chunks. "
        "Call exactly once."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "chunks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Chunk content (300–1500 chars).",
                        },
                        "section_path": {
                            "type": "string",
                            "description": (
                                "Hierarchical section path like "
                                "'Parent > Child'. Empty string when the "
                                "document has no genuine hierarchy."
                            ),
                        },
                        "page": {
                            "type": "integer",
                            "description": "1-based page index where chunk starts.",
                            "minimum": 1,
                        },
                        "has_table": {
                            "type": "boolean",
                            "description": "True if the chunk contains a markdown table.",
                        },
                    },
                    "required": ["text", "page"],
                },
            }
        },
        "required": ["chunks"],
    },
}


def format_sidecar(hyperlinks: list[dict]) -> str:
    """Render the hyperlink sidecar as a stable human+LLM-readable block."""
    if not hyperlinks:
        return "(no hidden hyperlinks on any page)"
    lines = []
    for h in hyperlinks:
        lines.append(f"- page {h['page']}: [{h['text']}]({h['uri']})")
    return "\n".join(lines)


def format_ocr_sidecar(ocr_text: dict[int, str]) -> str:
    """Render per-page OCR text as a stable markdown block for Opus.

    Opus is told (via the user prompt) to treat the rendered PDF image as
    ground truth and the OCR text as assistive — OCR may miss Thai tone
    marks or confuse digits, and Opus should correct obvious errors by
    looking at the image. Empty input returns a placeholder string so the
    prompt template substitution never leaves a blank line dangling.
    """
    if not ocr_text or all(not v for v in ocr_text.values()):
        return "(no OCR sidecar — document text layer sufficient)"
    lines = [
        "OCR was run on every page because the PDF has no extractable text layer.",
        "Treat the rendered image as ground truth and correct obvious OCR errors",
        "(mis-segmented Thai tone marks, digit/letter confusion, etc.).",
        "",
    ]
    for page_num in sorted(ocr_text.keys()):
        text = ocr_text[page_num]
        lines.append(f"### Page {page_num}")
        lines.append(text if text else "(OCR failed for this page — rely on vision only)")
        lines.append("")
    return "\n".join(lines).rstrip()
