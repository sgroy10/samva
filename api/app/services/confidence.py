"""
INVENTION 2 — Confidence Transparency.
After chat replies, rate Sam's confidence and append tag if needed.
HIGH = no tag. MEDIUM = soft warning. LOW = verify warning.
Language-aware: Hindi tags for Hindi users, English for English users.
"""

import logging
from .llm import call_gemini_json

logger = logging.getLogger("samva.confidence")

TAGS = {
    "hindi": {
        "MEDIUM": "\n\n_\U0001f4a1 Main kaafi sure hoon -- par ek baar confirm kar lena_",
        "LOW": "\n\n_\u26a0\ufe0f Main guess kar raha hoon -- verify karo_",
    },
    "english": {
        "MEDIUM": "\n\n_\U0001f4a1 I'm fairly sure -- but double-check_",
        "LOW": "\n\n_\u26a0\ufe0f I'm guessing -- please verify_",
    },
}


async def tag_confidence(
    reply: str, soul_excerpt: str, user_id: str = "", language: str = "auto"
) -> str:
    """
    Rate confidence of a chat reply and append appropriate tag.
    Fast call — max_tokens: 50.
    """
    try:
        result = await call_gemini_json(
            """Rate the confidence of this AI assistant response.
- HIGH: response is based on stored facts, user's own data, or clear knowledge
- MEDIUM: response is inferred from context but not 100% certain
- LOW: response is a guess — user should verify

Return JSON: {"confidence": "HIGH", "reason": "one line"}""",
            f"Response: {reply[:500]}\n\nContext used: {soul_excerpt[:300]}",
            user_id=user_id,
            max_tokens=50,
        )

        confidence = result.get("confidence", "HIGH").upper()

        if confidence in ("MEDIUM", "LOW"):
            # Pick language-appropriate tag
            lang_key = "english" if language in ("english",) else "hindi"
            return reply + TAGS[lang_key][confidence]

        return reply

    except Exception as e:
        logger.debug(f"Confidence check failed for {user_id}: {e}")
        return reply
