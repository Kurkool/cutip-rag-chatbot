"""Claude Vision — reads document pages as images for maximum accuracy."""

import base64
import logging

from langchain_core.messages import HumanMessage

from shared.config import settings
from shared.services.llm import get_haiku_vision

logger = logging.getLogger(__name__)

# Anthropic-supported image mime types. PDF rendering via PyMuPDF always
# emits PNG, but DOCX blobs can be any embedded format (JPEG is common).
# Hardcoding "image/png" previously caused 400 errors + silent caption
# loss on JPEG-in-DOCX images (observed 2026-04-17).
_MIME_PNG = "image/png"
_MIME_JPEG = "image/jpeg"
_MIME_GIF = "image/gif"
_MIME_WEBP = "image/webp"


def _detect_image_mime(image_bytes: bytes) -> str:
    """Magic-byte sniff. Returns image/png as fallback for unknown formats."""
    if not image_bytes or len(image_bytes) < 12:
        return _MIME_PNG
    head = image_bytes[:12]
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return _MIME_PNG
    # JPEG: FF D8 FF
    if head.startswith(b"\xff\xd8\xff"):
        return _MIME_JPEG
    # GIF: 'GIF87a' or 'GIF89a'
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return _MIME_GIF
    # WebP: 'RIFF' + 4 bytes + 'WEBP'
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return _MIME_WEBP
    # Unknown: let Anthropic figure it out. image/png is least-surprising default.
    logger.warning("Unknown image magic bytes: %s — defaulting to image/png", head[:4].hex())
    return _MIME_PNG

_PARSE_PAGE_PROMPT = (
    "Read this document page and convert to well-structured Markdown.\n\n"
    "Rules:\n"
    "- Preserve ALL text exactly as shown (Thai and English)\n"
    "- Convert tables to Markdown tables with proper headers\n"
    "- Preserve lists, bullet points, numbering\n"
    "- Mark checkboxes as [x] checked or [ ] unchecked\n"
    "- Note form fields as: [field_name: ___]\n"
    "- Describe diagrams/charts briefly in [brackets]\n"
    "- Use ### headers for section titles\n"
    "- Output ONLY the markdown, no explanation"
)

_INTERPRET_SPREADSHEET_PROMPT = (
    "This is raw data from a spreadsheet. Interpret the layout and convert to "
    "well-structured Markdown.\n\n"
    "Rules:\n"
    "- Identify separate sections/tables (they may be side-by-side or stacked)\n"
    "- Add ### headers for each section (e.g. ปริญญาโท รุ่นที่ 18)\n"
    "- Convert each table/section to a proper Markdown table\n"
    "- Handle merged cells by repeating the value where needed\n"
    "- Ignore empty rows/columns\n"
    "- Preserve all Thai and English text exactly\n"
    "- Output ONLY the markdown, no explanation\n\n"
    "Raw data:\n{data}"
)


_get_vision_llm = get_haiku_vision  # Cached Claude Haiku for Vision


async def parse_page_image(image_bytes: bytes) -> str:
    """Send a page image to Claude Vision, get back structured markdown.

    Media type is autodetected from the blob's magic bytes (PNG/JPEG/GIF/WebP).
    Hardcoding PNG previously caused 400s on JPEG-embedded DOCX images.
    """
    media_type = _detect_image_mime(image_bytes)
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    try:
        response = await _get_vision_llm().ainvoke([
            HumanMessage(content=[
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64,
                    },
                },
                {"type": "text", "text": _PARSE_PAGE_PROMPT},
            ])
        ])
        return response.content
    except Exception as e:
        _log_api_error("Vision parse", e)
        return ""


async def interpret_spreadsheet(raw_text: str) -> str:
    """Send raw spreadsheet data to Claude, get back structured markdown."""
    try:
        prompt = _INTERPRET_SPREADSHEET_PROMPT.format(data=raw_text[:8000])
        response = await _get_vision_llm().ainvoke(prompt)
        return response.content
    except Exception as e:
        _log_api_error("Spreadsheet interpretation", e)
        return raw_text


def _log_api_error(context: str, error: Exception):
    """Log API errors with specific messages for common failure modes."""
    err_str = str(error).lower()
    if "rate" in err_str and "limit" in err_str:
        logger.error("%s: RATE LIMIT — too many requests, will retry later", context)
    elif "credit" in err_str or "quota" in err_str or "billing" in err_str:
        logger.error("%s: QUOTA/CREDIT EXHAUSTED — check billing", context)
    elif "auth" in err_str or "key" in err_str or "401" in err_str:
        logger.error("%s: AUTH FAILED — check API key", context)
    elif "timeout" in err_str or "timed out" in err_str:
        logger.error("%s: TIMEOUT — request took too long", context)
    else:
        logger.exception("%s failed: %s", context, error)
