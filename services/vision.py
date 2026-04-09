"""Claude Vision — reads document pages as images for maximum accuracy."""

import base64
import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from config import settings

logger = logging.getLogger(__name__)

_VISION_MODEL = "claude-haiku-4-5-20251001"

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


def _get_vision_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model=_VISION_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0,
        max_tokens=4096,
    )


async def parse_page_image(image_bytes: bytes) -> str:
    """Send a page image to Claude Vision, get back structured markdown."""
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    llm = _get_vision_llm()
    try:
        response = await llm.ainvoke([
            HumanMessage(content=[
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": b64,
                    },
                },
                {"type": "text", "text": _PARSE_PAGE_PROMPT},
            ])
        ])
        return response.content
    except Exception:
        logger.warning("Vision parse failed for a page, returning empty")
        return ""


async def interpret_spreadsheet(raw_text: str) -> str:
    """Send raw spreadsheet data to Claude, get back structured markdown."""
    llm = _get_vision_llm()
    try:
        prompt = _INTERPRET_SPREADSHEET_PROMPT.format(data=raw_text[:8000])
        response = await llm.ainvoke(prompt)
        return response.content
    except Exception:
        logger.warning("Spreadsheet interpretation failed, returning raw text")
        return raw_text
