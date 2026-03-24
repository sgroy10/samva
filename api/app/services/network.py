"""
INVENTION 3 — Network Intelligence.
Connects users who can help each other — with explicit double permission.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..models import AgentSoul, User, NetworkConnection

logger = logging.getLogger("samva.network")


# ── Permission & Profile ─────────────────────────────────────────

async def ask_network_permission(db: AsyncSession, user_id: str) -> str:
    """
    Called after onboarding finishes.
    Returns the permission question message.
    """
    return (
        "Ek last cheez -- kya main aapko useful contacts se connect kar sakti hoon? "
        "Jaise koi supplier dhundh raha ho ya koi client -- permission doge toh main bataungi.\n\n"
        "(Haan / Nahi)"
    )


async def handle_permission_response(db: AsyncSession, user_id: str, text: str) -> str:
    """
    Handle user's yes/no response to network permission question.
    Returns follow-up message or confirmation.
    """
    lower = text.strip().lower()
    yes_words = {"haan", "ha", "yes", "ok", "sure", "bilkul", "theek", "thik", "ji"}
    no_words = {"nahi", "nai", "no", "nope", "mat", "nah"}

    if any(w in lower for w in yes_words):
        # Grant permission
        await db.execute(
            update(AgentSoul)
            .where(AgentSoul.user_id == user_id)
            .values(network_permission=True)
        )
        await db.commit()

        return (
            "Permission saved! Ab batao:\n\n"
            "1. *Aap kya dhundh rahe ho?* (supplier, client, partner, service...)\n"
            "2. *Aap kya offer kar sakte ho?* (product, service, expertise...)\n\n"
            "Ek message mein dono batao -- jaise:\n"
            "_\"Mujhe diamond supplier chahiye Surat se. Main gold jewelry design karti hoon.\"_"
        )

    elif any(w in lower for w in no_words):
        await db.execute(
            update(AgentSoul)
            .where(AgentSoul.user_id == user_id)
            .values(network_permission=False)
        )
        await db.commit()
        return "Bilkul! Aapki privacy meri priority hai. Kabhi bhi mann badle toh bolo."

    return ""  # Not a permission response


async def save_network_profile(db: AsyncSession, user_id: str, text: str) -> str:
    """
    Parse and save user's need/offer for network matching.
    Called when user describes what they need and offer.
    """
    from .llm import call_gemini_json

    try:
        parsed = await call_gemini_json(
            """Extract what this person needs and what they offer for a business network.
Return JSON:
{
    "need_type": "short category (e.g. diamond supplier, saree buyer, accountant)",
    "need_description": "full description of what they need",
    "offer_type": "short category (e.g. gold jewelry designer, silk sarees, CA services)",
    "offer_description": "full description of what they offer",
    "location": "city if mentioned"
}
If any field is not clear, use empty string.""",
            text,
            user_id=user_id,
        )

        # Get user info for location fallback
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()

        # Check existing profile
        result = await db.execute(
            select(NetworkConnection).where(
                NetworkConnection.user_id == user_id,
                NetworkConnection.is_active == True,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.need_type = parsed.get("need_type", "")
            existing.need_description = parsed.get("need_description", "")
            existing.offer_type = parsed.get("offer_type", "")
            existing.offer_description = parsed.get("offer_description", "")
            existing.location = parsed.get("location", "")
            existing.permission_given = True
        else:
            db.add(NetworkConnection(
                user_id=user_id,
                need_type=parsed.get("need_type", ""),
                need_description=parsed.get("need_description", ""),
                offer_type=parsed.get("offer_type", ""),
                offer_description=parsed.get("offer_description", ""),
                location=parsed.get("location", ""),
                permission_given=True,
                is_active=True,
            ))

        await db.commit()

        need = parsed.get("need_type", "?")
        offer = parsed.get("offer_type", "?")
        return (
            f"Profile saved!\n"
            f"Dhundh rahe ho: *{need}*\n"
            f"Offer karte ho: *{offer}*\n\n"
            f"Jab koi match milega, main bataungi. Tab tak -- koi baat nahi, "
            f"Sam aapke saath hai!"
        )

    except Exception as e:
        logger.error(f"[{user_id}] Network profile save failed: {e}")
        return "Samajh nahi aayi. Aise batao: \"Mujhe X chahiye. Main Y karti hoon.\""


# ── Weekly Matching ──────────────────────────────────────────────

async def run_network_matching(db: AsyncSession) -> list[dict]:
    """
    Match users whose offer matches another's need.
    Called by cron every Sunday after soul_evolution.
    Returns list of match notifications to send.

    CRITICAL: Never share personal details without both users confirming.
    """
    # Get all active profiles with permission
    result = await db.execute(
        select(NetworkConnection).where(
            NetworkConnection.is_active == True,
            NetworkConnection.permission_given == True,
        )
    )
    profiles = result.scalars().all()

    if len(profiles) < 2:
        return []

    notifications = []

    for i, profile_a in enumerate(profiles):
        for profile_b in profiles[i + 1:]:
            # Skip same user
            if profile_a.user_id == profile_b.user_id:
                continue

            # Check if A's need matches B's offer (keyword overlap)
            match_a_needs_b = _keyword_match(
                profile_a.need_type, profile_a.need_description,
                profile_b.offer_type, profile_b.offer_description,
            )

            # Check if B's need matches A's offer
            match_b_needs_a = _keyword_match(
                profile_b.need_type, profile_b.need_description,
                profile_a.offer_type, profile_a.offer_description,
            )

            if match_a_needs_b:
                notifications.append({
                    "user_id": profile_a.user_id,
                    "message": (
                        f"Sam ne ek connection dhundha! \U0001f91d\n\n"
                        f"Koi hai jo *{profile_b.offer_type}* offer karta hai"
                        f"{' (' + profile_b.location + ')' if profile_b.location else ''}.\n"
                        f"Aapko *{profile_a.need_type}* chahiye tha na?\n\n"
                        f"Interested ho? _Haan_ bolo toh main introduce karungi.\n"
                        f"(Aapki details tabhi share hongi jab dono taraf se haan aaye)"
                    ),
                    "match_user_id": profile_b.user_id,
                })

            if match_b_needs_a:
                notifications.append({
                    "user_id": profile_b.user_id,
                    "message": (
                        f"Sam ne ek connection dhundha! \U0001f91d\n\n"
                        f"Koi hai jo *{profile_a.offer_type}* offer karta hai"
                        f"{' (' + profile_a.location + ')' if profile_a.location else ''}.\n"
                        f"Aapko *{profile_b.need_type}* chahiye tha na?\n\n"
                        f"Interested ho? _Haan_ bolo toh main introduce karungi.\n"
                        f"(Aapki details tabhi share hongi jab dono taraf se haan aaye)"
                    ),
                    "match_user_id": profile_a.user_id,
                })

    logger.info(f"Network matching: {len(profiles)} profiles, {len(notifications)} matches")
    return notifications


def _keyword_match(need_type: str, need_desc: str, offer_type: str, offer_desc: str) -> bool:
    """
    Simple keyword overlap matching.
    Returns True if the need and offer share meaningful keywords.
    """
    if not need_type or not offer_type:
        return False

    # Combine and normalize
    need_words = set(
        w.lower().strip() for w in
        f"{need_type} {need_desc or ''}".split()
        if len(w) > 2
    )
    offer_words = set(
        w.lower().strip() for w in
        f"{offer_type} {offer_desc or ''}".split()
        if len(w) > 2
    )

    # Remove common stop words
    stop = {"the", "and", "for", "from", "with", "that", "this", "who", "what",
            "mein", "hai", "hoon", "karta", "karti", "chahiye", "koi", "aur"}
    need_words -= stop
    offer_words -= stop

    # Check overlap — at least 1 meaningful keyword match
    overlap = need_words & offer_words
    return len(overlap) >= 1
