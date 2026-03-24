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
Ask about:
- Preferred language for responses (or auto-detect?)
- What time they want their daily morning brief (default 9am)
- Do they want email integration? If so, which email?
Keep it warm, short, match their language.""",

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
    # Generate system prompt
    system_prompt = await call_gemini(
        """Generate a permanent system prompt for a WhatsApp AI assistant called Sam.
Based on the onboarding conversation, create a detailed prompt that captures:
- Who this person is (name, role, business/profession)
- What they do specifically (products, services, prices)
- Their rules and boundaries (what Sam should/shouldn't do)
- Their communication style and preferences
- Key facts Sam should always remember

Write it as instructions for Sam. Be specific and detailed.
Output ONLY the system prompt text, nothing else.""",
        f"Full onboarding conversation:\n{conv_text}",
        user_id=user_id,
    )

    # Detect language and business type
    analysis = await call_gemini_json(
        """Analyze this conversation and return JSON:
{
    "language": "detected primary language (e.g. hindi, english, gujarati, etc.)",
    "business_type": "brief business/profession type (e.g. saree shop, jeweller, fitness trainer, student, finance manager)"
}""",
        f"Conversation:\n{conv_text}",
        user_id=user_id,
    )

    language = analysis.get("language", "auto")
    business_type = analysis.get("business_type", "")

    # Update soul
    await db.execute(
        update(AgentSoul)
        .where(AgentSoul.user_id == user_id)
        .values(
            system_prompt=system_prompt,
            language_preference=language,
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

    # Append the quick guide + network permission question
    from .network import ask_network_permission
    network_q = await ask_network_permission(db, user_id)
    reply += QUICK_GUIDE + "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n" + network_q

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
    if not soul:
        soul = AgentSoul(user_id=user_id, onboarding_context={})
        db.add(soul)
        await db.commit()

    # Save first message as conversation
    conv = Conversation(user_id=user_id, role="assistant", content=FIRST_MESSAGE)
    db.add(conv)
    await db.commit()

    return [FIRST_MESSAGE]
