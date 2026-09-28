"""
core/language_utils.py
-----------------------
Lightweight automatic language detection for Tamil vs English.

Instead of pulling in a heavy NLP dependency, we check for characters
in the Tamil Unicode block (U+0B80 to U+0BFF). This is fast, works
offline, and is accurate for Tamil script text (including Tamil typed
with English mixed in - "Tanglish" typed in Latin letters is treated
as English, which is expected behavior for this simple approach).

Zero third-party dependencies - important for the deploy size budget.
"""

TAMIL_UNICODE_RANGE = (0x0B80, 0x0BFF)


def detect_language(text: str) -> str:
    """
    Return 'ta' if the text contains Tamil script characters,
    otherwise return 'en'.
    """
    if not text:
        return "en"

    for char in text:
        code_point = ord(char)
        if TAMIL_UNICODE_RANGE[0] <= code_point <= TAMIL_UNICODE_RANGE[1]:
            return "ta"

    return "en"


def language_label(code: str) -> str:
    """Human-friendly label, used for the little badge in the UI."""
    return {"ta": "தமிழ்", "en": "English"}.get(code, "English")
