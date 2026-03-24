"""
INVENTION 3 — Network Intelligence.
Connects users who can help each other — with explicit double permission.
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..models import AgentSoul, User, NetworkConnection, NetworkMatch

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
    Creates NetworkMatch records and sends notifications.
    NEVER shares personal details until both users confirm.
    """
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
            if profile_a.user_id == profile_b.user_id:
                continue

            # Skip if already matched (pending or introduced)
            existing_match = await db.execute(
                select(NetworkMatch).where(
                    ((NetworkMatch.user_a_id == profile_a.user_id) & (NetworkMatch.user_b_id == profile_b.user_id)) |
                    ((NetworkMatch.user_a_id == profile_b.user_id) & (NetworkMatch.user_b_id == profile_a.user_id))
                )
            )
            if existing_match.scalar_one_or_none():
                continue

            match_a_needs_b = _keyword_match(
                profile_a.need_type, profile_a.need_description,
                profile_b.offer_type, profile_b.offer_description,
            )
            match_b_needs_a = _keyword_match(
                profile_b.need_type, profile_b.need_description,
                profile_a.offer_type, profile_a.offer_description,
            )

            if match_a_needs_b or match_b_needs_a:
                # Create match record
                reason = f"{profile_a.need_type} <-> {profile_b.offer_type}"
                match = NetworkMatch(
                    user_a_id=profile_a.user_id,
                    user_b_id=profile_b.user_id,
                    match_reason=reason,
                )
                db.add(match)
                await db.flush()

                if match_a_needs_b:
                    notifications.append({
                        "user_id": profile_a.user_id,
                        "match_id": match.id,
                        "message": (
                            f"Sam ne ek connection dhundha! \U0001f91d\n\n"
                            f"Koi hai jo *{profile_b.offer_type}* offer karta hai"
                            f"{' (' + profile_b.location + ')' if profile_b.location else ''}.\n"
                            f"Aapko *{profile_a.need_type}* chahiye tha na?\n\n"
                            f"Interested ho? _Haan_ bolo toh main introduce karungi.\n"
                            f"(Aapki details tabhi share hongi jab dono taraf se haan aaye)"
                        ),
                    })

                if match_b_needs_a:
                    notifications.append({
                        "user_id": profile_b.user_id,
                        "match_id": match.id,
                        "message": (
                            f"Sam ne ek connection dhundha! \U0001f91d\n\n"
                            f"Koi hai jo *{profile_a.offer_type}* offer karta hai"
                            f"{' (' + profile_a.location + ')' if profile_a.location else ''}.\n"
                            f"Aapko *{profile_b.need_type}* chahiye tha na?\n\n"
                            f"Interested ho? _Haan_ bolo toh main introduce karungi.\n"
                            f"(Aapki details tabhi share hongi jab dono taraf se haan aaye)"
                        ),
                    })

    await db.commit()
    logger.info(f"Network matching: {len(profiles)} profiles, {len(notifications)} matches")
    return notifications


# ── Match Confirmation + Introduction ────────────────────────────

async def handle_match_confirmation(db: AsyncSession, user_id: str, text: str) -> str:
    """
    When a user says 'haan' to a match notification.
    If both confirmed → share first name + WhatsApp number.
    """
    lower = text.strip().lower()
    yes_words = {"haan", "ha", "yes", "ok", "sure", "bilkul", "interested"}

    if not any(w in lower for w in yes_words):
        return ""

    # Find the user's most recent unconfirmed match
    match_result = await db.execute(
        select(NetworkMatch).where(
            ((NetworkMatch.user_a_id == user_id) | (NetworkMatch.user_b_id == user_id)),
            NetworkMatch.introduced == False,
        ).order_by(NetworkMatch.created_at.desc()).limit(1)
    )
    match = match_result.scalar_one_or_none()

    if not match:
        return ""

    # Mark this user's confirmation
    is_user_a = match.user_a_id == user_id
    if is_user_a:
        match.user_a_confirmed = True
    else:
        match.user_b_confirmed = True
    await db.commit()

    # Check if BOTH confirmed
    if match.user_a_confirmed and match.user_b_confirmed:
        # Both said yes — do the introduction
        return await _introduce_users(db, match)

    # Only one confirmed so far
    return (
        "Noted! Aapne haan bol diya. Jab doosri taraf se bhi haan aayega, "
        "tab main dono ko introduce karungi. Thoda wait karo!"
    )


async def _introduce_users(db: AsyncSession, match: NetworkMatch) -> str:
    """
    Both users confirmed. Share first name + WhatsApp number.
    Returns intro message for the user who just confirmed.
    The other user gets their intro via a separate notification.
    """
    # Get both users
    user_a_result = await db.execute(select(User).where(User.id == match.user_a_id))
    user_a = user_a_result.scalar_one_or_none()
    user_b_result = await db.execute(select(User).where(User.id == match.user_b_id))
    user_b = user_b_result.scalar_one_or_none()

    if not user_a or not user_b:
        return "Match details not found. Sorry!"

    # Mark as introduced
    match.introduced = True
    await db.commit()

    name_a = user_a.name or "Samva User"
    name_b = user_b.name or "Samva User"
    phone_a = user_a.phone or "?"
    phone_b = user_b.phone or "?"

    # Get their offer types for context
    nc_a = await db.execute(
        select(NetworkConnection).where(NetworkConnection.user_id == match.user_a_id, NetworkConnection.is_active == True)
    )
    nc_b = await db.execute(
        select(NetworkConnection).where(NetworkConnection.user_id == match.user_b_id, NetworkConnection.is_active == True)
    )
    profile_a = nc_a.scalar_one_or_none()
    profile_b = nc_b.scalar_one_or_none()
    offer_a = profile_a.offer_type if profile_a else "?"
    offer_b = profile_b.offer_type if profile_b else "?"

    # This return goes to whichever user just confirmed last
    # The OTHER user gets their intro via intro_messages_for_match()
    logger.info(f"Network intro: {match.user_a_id} <-> {match.user_b_id}")

    return (
        f"Dono taraf se haan aa gaya! \U0001f389 Introduction:\n\n"
        f"\U0001f464 *{name_b}*\n"
        f"\U0001f4bc {offer_b}\n"
        f"\U0001f4f1 {phone_b}\n\n"
        f"Ab directly baat kar sakte ho. Good luck! \U0001f91d"
    )


async def get_pending_introductions(db: AsyncSession) -> list[dict]:
    """
    Get all matches where both confirmed but the other user hasn't been notified.
    Called after handle_match_confirmation to send the other user their intro.
    """
    result = await db.execute(
        select(NetworkMatch).where(
            NetworkMatch.user_a_confirmed == True,
            NetworkMatch.user_b_confirmed == True,
            NetworkMatch.introduced == True,
        )
    )
    matches = result.scalars().all()

    intros = []
    for match in matches:
        user_a = await db.execute(select(User).where(User.id == match.user_a_id))
        user_b = await db.execute(select(User).where(User.id == match.user_b_id))
        ua = user_a.scalar_one_or_none()
        ub = user_b.scalar_one_or_none()
        if not ua or not ub:
            continue

        nc_a = await db.execute(
            select(NetworkConnection).where(NetworkConnection.user_id == match.user_a_id, NetworkConnection.is_active == True)
        )
        nc_b = await db.execute(
            select(NetworkConnection).where(NetworkConnection.user_id == match.user_b_id, NetworkConnection.is_active == True)
        )
        pa = nc_a.scalar_one_or_none()
        pb = nc_b.scalar_one_or_none()

        # User A gets intro to User B
        intros.append({
            "user_id": match.user_a_id,
            "message": (
                f"Dono taraf se haan aa gaya! \U0001f389 Introduction:\n\n"
                f"\U0001f464 *{ub.name or 'Samva User'}*\n"
                f"\U0001f4bc {pb.offer_type if pb else '?'}\n"
                f"\U0001f4f1 {ub.phone or '?'}\n\n"
                f"Ab directly baat kar sakte ho. Good luck! \U0001f91d"
            ),
        })
        # User B gets intro to User A
        intros.append({
            "user_id": match.user_b_id,
            "message": (
                f"Dono taraf se haan aa gaya! \U0001f389 Introduction:\n\n"
                f"\U0001f464 *{ua.name or 'Samva User'}*\n"
                f"\U0001f4bc {pa.offer_type if pa else '?'}\n"
                f"\U0001f4f1 {ua.phone or '?'}\n\n"
                f"Ab directly baat kar sakte ho. Good luck! \U0001f91d"
            ),
        })

    return intros


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
