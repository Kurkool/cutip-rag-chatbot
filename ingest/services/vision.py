"""Vision-refusal-string detector used by the v2 ingest pipeline.

Post-v1 cleanup (2026-04-19): the actual Vision-OCR calls moved into
``ingestion_v2.py::opus_parse_and_chunk`` which uses Opus 4.7 directly on
rendered PDFs. Only the refusal-phrase filter remains here since v2 still
needs to drop chunks whose content is a model "I can't read this" string
rather than real document text.
"""


# Phrases Opus/Haiku Vision emit when they can't OCR the page (blank, blurry,
# or encoding-damaged). Any response containing these is a refusal string,
# not document content — must be dropped, not stored as chunk text.
_VISION_REFUSAL_PATTERNS = (
    "ensure the image is clear",
    "could you please",
    "re-upload the document",
    "readable document",
    "no visible text",
    "unable to see",
    "cannot read",
    "appears to be blank",
    "file loaded correctly",
    "i'll be happy",
    "i cannot process",
    "please provide",
)


def _looks_like_refusal(markdown: str) -> bool:
    """Return True if Vision output is a refusal/error string, not content."""
    if not markdown:
        return False
    lower = markdown.lower()
    return any(p in lower for p in _VISION_REFUSAL_PATTERNS)
