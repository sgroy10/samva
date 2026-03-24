"""
INVENTION 2 — Confidence Transparency.
After chat replies, rate Sam's confidence and append tag if needed.
HIGH = no tag. MEDIUM = soft warning. LOW = verify warning.
"""

import logging
from .llm import call_gemini_json

logger = logging.getLogger("samva.confidence")


async def tag_confidence(reply: str, soul_excerpt: str, user_id: str = "") -> str:
    """
    Rate confidence of a chat reply and append appropriate tag.
    Fast call — max_tokens: 50.

    Returns the reply with confidence tag appended (or unchanged if HIGH).
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

        if confidence == "MEDIUM":
            return reply + "\n\n_\U0001f4a1 Main kaafi sure hoon -- par ek baar confirm kar lena_"
        elif confidence == "LOW":
            return reply + "\n\n_\u26a0\ufe0f Main guess kar raha hoon -- verify karo_"
        else:
            # HIGH — clean response, no tag
            return reply

    except Exception as e:
        # If confidence check fails, return reply as-is (HIGH assumed)
        logger.debug(f"Confidence check failed for {user_id}: {e}")
        return reply
