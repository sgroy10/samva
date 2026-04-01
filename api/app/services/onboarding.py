import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..models import AgentSoul, User, Conversation
from .llm import call_gemini, call_gemini_json

logger = logging.getLogger("samva.onboarding")

FIRST_MESSAGE = (
    "Hi! I'm Sam -- your personal WhatsApp assistant from Samva.\n\n"
    "I'm here to help you every day -- answering messages, reading your emails, "
    "remembering your contacts, capturing your meetings, and reminding you of what matters.\n\n"
    "To get started -- tell me about yourself. What do you do? "
    "What takes up most of your time every day?\n\n"
    "You can type or send a voice note -- in any language."
)


STEP_PROMPTS = {
    0: """You are Sam, a friendly onboarding assistant for Samva.
The user just told you about themselves. Ask a SPECIFIC follow-up question about:
- What products/services they deal with and their price range
- Who are their typical customers/clients
- What takes up most of their daily time
Keep it warm, short (2-3 lines max), conversational. Match their language.""",

    1: """You are Sam, continuing onboarding. The user has described their work.
Now ask about specifics that will help you assist them:
- Do they want you to answer customer messages? What should you say/not say?
- Any specific prices, catalogs, or key info to remember?
- Any topics that are off-limits?
Keep it warm, short, match their language.""",

    2: """You are Sam, continuing onboarding. You now know their work and preferences.
Now ask about LANGUAGE — this is critical. Say exactly:

"Aapko kis language mein baat karni hai?

• English only
• Hindi
• Hindi + English (Hinglish)
• Gujarati
• Bengali / Bangla
• Tamil + English
• Telugu
• Malayalam
• Marathi
• Kannada
• Punjabi

Jo bhi comfortable ho — batao!

Aur voice notes mein kaunsi language? Same ya alag?"

Also ask: What time for morning brief (default 9am)?
Do they want email integration?""",

    3: """You are Sam. You've gathered enough info about this user.
Summarize what you've learned in 4-5 bullet points and ask them to confirm:
"Is this right? Anything to add or change?"
Match their language. Be warm.""",
}


async def handle_onboarding(
    db: AsyncSession, user_id: str, message: str
) -> str:
    """Process an onboarding message. Returns Sam's reply."""
    # Get or create soul
    result = await db.execute(
        select(AgentSoul).where(AgentSoul.user_id == user_id)
    )
    soul = result.scalar_one_or_none()

    if not soul:
        soul = AgentSoul(user_id=user_id, onboarding_context={})
        db.add(soul)
        await db.commit()
        await db.refresh(soul)

    step = soul.onboarding_step
    context = soul.onboarding_context or {}

    # Save user message to context
    context[f"step_{step}_user"] = message

    # Get conversation history for context
    conv_result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.created_at.desc())
        .limit(20)
    )
    conversations = conv_result.scalars().all()
    conv_text = "\n".join(
        [f"{c.role}: {c.content}" for c in reversed(list(conversations))]
    )

    if step >= 3:
        # Check if user confirmed
        confirm_check = await call_gemini_json(
            """Determine if the user is confirming/agreeing or wants to change something.
Return JSON: {"confirmed": true/false, "changes": "description of changes if any"}""",
            f"User said: {message}\nContext: We asked them to confirm their profile summary.",
            user_id=user_id,
        )

        if confirm_check.get("confirmed", False):
            # Generate permanent soul
            reply = await _finalize_soul(db, user_id, soul, context, conv_text)
            return reply
        else:
            # They want changes - ask what to change
            reply = await call_gemini(
                "You are Sam. The user wants to modify their profile. Ask what they'd like to change. Be warm, brief, match their language.",
                f"Conversation so far:\n{conv_text}\n\nUser's latest: {message}",
                user_id=user_id,
            )
            # Don't advance step, let them provide changes
            context[f"step_{step}_change"] = message
            await db.execute(
                update(AgentSoul)
                .where(AgentSoul.user_id == user_id)
                .values(onboarding_context=context)
            )
            await db.commit()
            return reply

    # Normal step progression
    if step in STEP_PROMPTS:
        system = STEP_PROMPTS[step]
        reply = await call_gemini(
            system,
            f"Conversation so far:\n{conv_text}\n\nUser's latest message: {message}",
            user_id=user_id,
        )
    else:
        # Beyond defined steps, finalize
        reply = await _finalize_soul(db, user_id, soul, context, conv_text)
        return reply

    # Advance step
    new_step = step + 1
    context[f"step_{step}_sam"] = reply
    await db.execute(
        update(AgentSoul)
        .where(AgentSoul.user_id == user_id)
        .values(onboarding_step=new_step, onboarding_context=context)
    )
    await db.commit()

    return reply


async def _finalize_soul(
    db: AsyncSession, user_id: str, soul: AgentSoul, context: dict, conv_text: str
) -> str:
    """Generate the permanent system prompt and activate the user."""
    # Generate system prompt WITH Indian regional context
    system_prompt = await call_gemini(
        """Generate a permanent system prompt for a WhatsApp AI assistant called Sam.
Based on the onboarding conversation, create a detailed prompt that captures:
- Who this person is (name, role, business/profession)
- What they do specifically (products, services, prices)
- Their rules and boundaries (what Sam should/shouldn't do)
- Their communication style and preferences
- Key facts Sam should always remember

CRITICAL — INJECT REGIONAL CONTEXT based on the user's city/state:
If they are from Gujarat/Surat: Know about Ratanlal Chowk, Textile Market, Diwali/Dhanteras buying season, typical Gujarati making charges (10-16%), COD norms, common Gujarati phrases.
If they are from Mumbai: Know about Zaveri Bazaar, BKC business district, local festivals (Ganpati, Navratri), Mumbai real estate context, BMC rules.
If they are from Jaipur: Know about Johari Bazaar, Rajasthani gemstone market, lac jewelry, kundan/meenakari work, tourist season patterns.
If they are from Delhi: Know about Chandni Chowk, Karol Bagh jewelry market, wedding season (Nov-Feb), Delhi NCR business norms.
If they are from Chennai/South India: Know about T Nagar, gold temple jewelry, Pongal/Onam buying, South Indian design preferences, traditional weight norms.
If they are from Kolkata: Know about Bowbazar, Bengali jewelry traditions, Durga Puja season, lightweight vs heavy jewelry preferences.
If they are from Goa: Know about beach tourism Oct-March peak season, Konkani and English mix, North Goa party scene vs South Goa heritage, water sports and heritage walk pricing norms, cashew and feni culture.
If they are from Pune: Know about IT/education hub, startup culture, Koregaon Park and FC Road lifestyle, weekend tourist destination, Marathi-English bilingual, Ganpati festival is massive.
If they are from Hyderabad: Know about Pearls and Laad Bazaar, IT corridor Hitech City, biryani culture, bilingual Telugu+Hindi, Charminar heritage market, wedding jewelry traditions.
If they are from Kochi/Kerala: Know about backwaters tourism, Kerala's massive gold buying culture (highest per capita in India), Onam and Vishu season, Thrissur Pooram, spice trade history.
If they are from Ahmedabad: Know about Manek Chowk, textile and diamond industry, Navratri garba culture, dry state, SG Highway business district, Kutch handicraft market.
If they are from Lucknow: Know about Chikankari embroidery, Nawabi culture, polite Urdu-Hindi (Lucknowi tehzeeb), Aminabad market, kebab and biryani culture.
If they are from Chandigarh: Know about planned city, Sector 17 market, Punjabi-Hindi mix, wedding season culture, proximity to Shimla for tourism.
If they are from Varanasi: Know about Banarasi silk sarees, temple jewelry, spiritual tourism, ghats, ancient goldsmith traditions, Kashi Vishwanath corridor.
If they are from Indore: Know about street food capital, textile market, MP's commercial hub, Sarafa Bazaar (night food market), Rajwada area.

Also inject:
- Indian festival calendar relevant to their business (Akshaya Tritiya, Dhanteras, Karva Chauth, wedding season)
- Common Hindi/regional language phrases for their domain
- Local payment norms (UPI, RTGS for wholesale, cash for retail)
- Typical pricing structures for their business in their region

Write it as instructions for Sam. Be specific, regional, and detailed.
Output ONLY the system prompt text, nothing else.""",
        f"Full onboarding conversation:\n{conv_text}",
        user_id=user_id,
        max_tokens=1200,
    )

    # Detect language, voice language, business type, city
    analysis = await call_gemini_json(
        """Analyze this conversation and return JSON:
{
    "language": "the user's EXPLICITLY chosen text language (e.g. english, hindi, gujarati, tamil, bengali, telugu, malayalam, marathi, hinglish). If they said 'English only' use 'english'. If they said 'Tamil + English' use 'tamil'. Use what they explicitly asked for, not what they typed in.",
    "voice_language": "the user's chosen voice note language. If they said 'same' or didn't specify, use same as language field. If they said a different language for voice, use that.",
    "business_type": "brief business/profession type (e.g. saree shop, jeweller, fitness trainer, student, finance manager)",
    "city": "city/town if mentioned (e.g. Surat, Mumbai, Delhi, Jaipur, Chennai, Kolkata)",
    "state": "Indian state if detectable"
}""",
        f"Conversation:\n{conv_text}",
        user_id=user_id,
    )

    language = analysis.get("language", "english")
    voice_language = analysis.get("voice_language", language)
    business_type = analysis.get("business_type", "")

    # Update soul
    await db.execute(
        update(AgentSoul)
        .where(AgentSoul.user_id == user_id)
        .values(
            system_prompt=system_prompt,
            language_preference=language,
            voice_language=voice_language,
            business_type=business_type,
            onboarding_complete=True,
            onboarding_context=context,
        )
    )

    # Activate user
    await db.execute(
        update(User).where(User.id == user_id).values(status="active")
    )
    await db.commit()

    # Generate personalized welcome message
    reply = await call_gemini(
        f"""You are Sam. You just finished setting up for this user.
Their profile: {system_prompt[:500]}
Send a warm, excited confirmation message in 3-4 lines.
Tell them you're ready and mention 2 specific things you'll do for THEM.
Match their language. Keep it short.""",
        "Generate the post-onboarding welcome message.",
        user_id=user_id,
    )

    # If jeweller — tell them about the gold brief
    from .gold import _is_jeweller
    if _is_jeweller(business_type):
        reply += (
            "\n\n\U0001f4b0 *Aapke liye special:* Roz subah 9 AM pe main aapko gold/silver ka "
            "live rate bhejungi — 24K, 22K, 18K, silver, platinum, international price, "
            "aur expert buy/hold view.\n"
            "Time change karna ho toh bolo: 'brief 8am'\n"
            "Band karna ho toh bolo: 'stop gold brief'"
        )

    # Append the quick guide + network permission question
    from .network import ask_network_permission
    network_q = await ask_network_permission(db, user_id)
    reply += QUICK_GUIDE + "\n\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n" + network_q

    return reply


# ── Quick Guide — sent right after onboarding ────────────────────

QUICK_GUIDE = """

━━━━━━━━━━━━━━━━━━━━━━━━━━

🚀 *Here's what I can do for you:*

💬 *Chat* — Ask me anything. I know your business.
📧 *Email* — "Check my mail" or voice note me what to send
📸 *Business card* — Photo a card, I save the contact forever
🎙️ *Meeting notes* — Voice note after any meeting, I structure everything
⏰ *Reminders* — "Remind me tomorrow 9am to call Ramesh"
🔍 *Web search* — "What's the gold rate today?"
📊 *Stocks* — "Watch Reliance, alert me above 1450"
🧠 *Memory* — "My COD charge is ₹50" — I never forget

━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 *Try these right now:*

1. Send me a photo of a business card
2. Say "remind me tomorrow at 9am to check email"
3. Ask "check my mail" (connect email first)
4. Voice note me about your last meeting

Type *help* anytime to see this again.
"""


async def send_first_message(
    db: AsyncSession, user_id: str, phone: str, push_name: str = ""
) -> list[str]:
    """Called when a new user first connects. Returns list of messages to send."""
    # Update user info
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user:
        if phone and not user.phone:
            user.phone = phone
        if push_name and not user.name:
            user.name = push_name
        await db.commit()

    # Ensure soul exists
    result = await db.execute(
        select(AgentSoul).where(AgentSoul.user_id == user_id)
    )
    soul = result.scalar_one_or_none()

    # If already onboarded — don't send first message again (happens on every deploy/reconnect)
    if soul and soul.onboarding_complete:
        logger.info(f"[{user_id}] Already onboarded, skipping first message")
        return []

    if not soul:
        soul = AgentSoul(user_id=user_id, onboarding_context={})
        db.add(soul)
        await db.commit()

    # Save first message as conversation
    conv = Conversation(user_id=user_id, role="assistant", content=FIRST_MESSAGE)
    db.add(conv)
    await db.commit()

    return [FIRST_MESSAGE]
