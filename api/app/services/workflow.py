"""
Multi-Step Workflow Engine — Sam executes complex chains.

When user says something that requires multiple actions,
Sam breaks it down and executes step by step:

"New customer Priya called about gold necklace" →
  1. Save contact: Priya
  2. Set reminder: Follow up in 5 days
  3. Draft email: Welcome + catalog
  4. Note: Gold necklace inquiry

"Meeting just ended with Amit about Jaipur order" →
  1. Save meeting note
  2. Extract action items
  3. Set reminder for each action
  4. Draft follow-up email
"""

import logging
from datetime import datetime, timedelta
import pytz
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import Conversation, UserMemory
from .llm import call_gemini_json

logger = logging.getLogger("samva.workflow")
IST = pytz.timezone("Asia/Kolkata")

# Workflow triggers — detected by orchestrator
WORKFLOW_TRIGGERS = {
    "new_customer": [
        "new customer", "naya customer", "new client", "naya client",
        "inquiry aaya", "enquiry aaya", "call aaya", "lead aaya",
    ],
    "meeting_ended": [
        "meeting ho gayi", "meeting just ended", "meeting khatam",
        "abhi meeting hua", "call ho gayi", "discussion ho gayi",
    ],
    "payment_received": [
        "payment aa gaya", "payment received", "paisa aa gaya",
        "transfer ho gaya", "amount received",
    ],
    "order_placed": [
        "order place ho gaya", "order confirmed", "order de diya",
        "order book ho gaya",
    ],
}


def detect_workflow(text: str) -> str:
    """Detect if message triggers a workflow. Returns workflow type or empty string."""
    text_lower = text.lower()
    for wf_type, triggers in WORKFLOW_TRIGGERS.items():
        if any(t in text_lower for t in triggers):
            return wf_type
    return ""


async def execute_workflow(
    db: AsyncSession, user_id: str, workflow_type: str, text: str, soul_prompt: str = ""
) -> str:
    """Execute a multi-step workflow and return summary of actions taken."""
    logger.info(f"[{user_id}] Executing workflow: {workflow_type}")

    # Use LLM to extract structured data from the message
    extract_prompt = f"""Extract structured information from this message for a {workflow_type} workflow.
Return JSON with these fields:
{{
    "person_name": "name if mentioned",
    "phone": "phone if mentioned",
    "company": "company if mentioned",
    "topic": "what was discussed/requested",
    "amount": "if any amount mentioned",
    "follow_up_days": 5,
    "actions": ["list of actions Sam should take"]
}}
Only include fields that are actually mentioned. Be precise."""

    try:
        data = await call_gemini_json(
            extract_prompt, text, user_id=user_id, max_tokens=400,
        )
    except Exception as e:
        logger.error(f"[{user_id}] Workflow extraction failed: {e}")
        return ""

    if not data or "error" in data:
        return ""

    actions_taken = []
    person = data.get("person_name", "")
    topic = data.get("topic", "")
    follow_up = data.get("follow_up_days", 5)

    # Step 1: Save contact if person mentioned
    if person:
        try:
            from .contacts import save_contact_from_text
            await save_contact_from_text(
                db, user_id,
                f"Name: {person}, Company: {data.get('company', '')}, Phone: {data.get('phone', '')}",
            )
            actions_taken.append(f"📇 Contact saved: {person}")
        except Exception:
            pass

    # Step 2: Set follow-up reminder
    if person and follow_up:
        try:
            from .reminders import create_reminder
            remind_at = datetime.now(IST) + timedelta(days=int(follow_up))
            reminder_text = f"Follow up with {person}"
            if topic:
                reminder_text += f" about {topic}"
            await create_reminder(db, user_id, reminder_text, remind_at)
            actions_taken.append(f"⏰ Reminder set: {reminder_text} ({follow_up} days)")
        except Exception:
            pass

    # Step 3: Save memory about this interaction
    if person and topic:
        try:
            mem_key = f"last_interaction_{person.lower().replace(' ', '_')}"
            from ..models import UserMemory
            from sqlalchemy import delete as sa_delete
            # Upsert memory
            await db.execute(
                sa_delete(UserMemory).where(
                    UserMemory.user_id == user_id,
                    UserMemory.key == mem_key,
                )
            )
            db.add(UserMemory(
                user_id=user_id,
                key=mem_key,
                value=f"{topic} (on {datetime.now(IST).strftime('%d %b %Y')})",
            ))
            await db.commit()
            actions_taken.append(f"🧠 Noted: {person} — {topic}")
        except Exception:
            pass

    # Step 4: Save amount if payment
    if workflow_type == "payment_received" and data.get("amount"):
        try:
            db.add(UserMemory(
                user_id=user_id,
                key=f"payment_{person.lower().replace(' ', '_')}",
                value=f"₹{data['amount']} received on {datetime.now(IST).strftime('%d %b')}",
            ))
            await db.commit()
            actions_taken.append(f"💰 Payment logged: ₹{data['amount']} from {person}")
        except Exception:
            pass

    if actions_taken:
        summary = "\n".join(actions_taken)
        logger.info(f"[{user_id}] Workflow {workflow_type}: {len(actions_taken)} actions")
        return f"Done! I've handled everything:\n\n{summary}\n\nKuch aur karna hai?"
    return ""
