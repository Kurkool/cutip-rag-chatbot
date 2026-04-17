"""Language detection helpers for error-message + fallback routing.

The primary consumer is the chat path: we use the user's query language to
decide whether to respond in Thai or English when the model can't produce an
answer (rate limit, auth error, empty content, LangGraph step exhaustion).
Inline Thai-unicode comprehensions used to live in agent.py and webhook.py;
they disagreed on edge cases (English queries that contain a Thai program
name gave a false Thai positive), so we consolidate here.
"""

_THAI_START = "\u0e00"
_THAI_END = "\u0e7f"

# Fraction of alphabetic characters that must be Thai before we call a query
# "Thai-dominant." 0.5 means Thai needs to be a strict majority of letters;
# ties or Thai-minority fall back to English. Calibrated against real cases:
#   "What is the TIP หลักสูตร?" → 8 Thai / 20 total = 0.40 → English
#   "สวัสดีค่ะ TIP คืออะไร"    → 16 Thai / 19 total = 0.84 → Thai
#   "สวัสดี 123"               → 6 Thai / 6 total  = 1.00 → Thai
_THAI_DOMINANCE_FRACTION = 0.5


def is_thai(text: str) -> bool:
    """Return True if ``text`` is Thai-dominant by letter count.

    Uses script dominance (Thai-letters / total-letters), not mere presence,
    so an English query referencing a Thai program name
    ("tell me about the หลักสูตร TIP") is still treated as English for
    error-routing purposes. An exact 50/50 mix defaults to English.

    Empty / None / whitespace-only / digits-only → False (English fallbacks).
    """
    if not text:
        return False
    thai = 0
    latin = 0
    for c in text:
        if _THAI_START <= c <= _THAI_END:
            thai += 1
        elif c.isalpha():
            latin += 1
    total_alpha = thai + latin
    if total_alpha == 0:
        return False
    return thai / total_alpha > _THAI_DOMINANCE_FRACTION
