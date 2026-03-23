import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import MeetingNote, Contact, Reminder
from .llm import call_gemini, call_gemini_json

logger = logging.getLogger("samva.meeting")


async def process_meeting_note(
    db: AsyncSession, user_id: str, transcript: str
) -> str:
    """Process a voice/text meeting note. Structure, save contacts, set reminders."""
    # Structure the note using Gemini
    structured = await call_gemini_json(
        """Structure this meeting note into JSON:
{
    "summary": "2-3 line summary",
    "people": [{"name": "...", "company": "...", "phone": "...", "email": "...", "designation": "..."}],
    "location": "if mentioned",
    "items_discussed": ["item1", "item2"],
    "action_items": [{"task": "...", "owner": "...", "deadline": "if mentioned"}],
    "deals": [{"product": "...", "quantity": ..., "price": ..., "total": ...}],
    "follow_up_date": "YYYY-MM-DD if mentioned, else null",
    "key_decisions": ["decision1"]
}
Extract ALL people mentioned, even partially. Infer reasonable deadlines if tone suggests urgency.""",
        transcript,
        user_id=user_id,
    )

    if "error" in structured:
        # Fallback: save raw
        note = MeetingNote(
            user_id=user_id,
            raw_transcript=transcript,
            structured_json={},
        )
        db.add(note)
        await db.commit()
        return "Meeting note saved \u2713 (I had trouble structuring it, but it's safely stored.)"

    # Save meeting note
    follow_up = None
    if structured.get("follow_up_date"):
        try:
            follow_up = datetime.strptime(structured["follow_up_date"], "%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    people = structured.get("people", [])
    action_items = structured.get("action_items", [])

    note = MeetingNote(
        user_id=user_id,
        raw_transcript=transcript,
        structured_json=structured,
        location=structured.get("location", ""),
        people_mentioned=[p.get("name", "") for p in people],
        action_items=action_items,
        follow_up_date=follow_up,
    )
    db.add(note)

    # Auto-save contacts
    contacts_saved = 0
    for person in people:
        name = person.get("name", "").strip()
        if not name:
            continue

        # Check if contact already exists
        existing = await db.execute(
            select(Contact).where(
                Contact.user_id == user_id,
                Contact.full_name == name,
            )
        )
        if existing.scalar_one_or_none():
            continue

        contact = Contact(
            user_id=user_id,
            full_name=name,
            company=person.get("company", ""),
            designation=person.get("designation", ""),
            phone=person.get("phone", ""),
            email=person.get("email", ""),
            source="meeting",
        )
        db.add(contact)
        contacts_saved += 1

    # Create reminders from action items
    reminders_created = 0
    for item in action_items:
        task = item.get("task", "")
        deadline = item.get("deadline", "")
        if not task:
            continue

        remind_at = datetime.now()
        if deadline:
            try:
                remind_at = datetime.strptime(deadline, "%Y-%m-%d")
            except (ValueError, TypeError):
                remind_at = datetime.now().replace(hour=9, minute=0, second=0)

        reminder = Reminder(
            user_id=user_id,
            text=f"Meeting follow-up: {task}",
            remind_at=remind_at,
            type="meeting",
        )
        db.add(reminder)
        reminders_created += 1

    await db.commit()

    # Format response
    reply_parts = ["Note saved \u2713"]

    if contacts_saved:
        reply_parts.append(f"{contacts_saved} contact(s) saved \u2713")

    if structured.get("deals"):
        for deal in structured["deals"]:
            if deal.get("total"):
                reply_parts.append(
                    f"\ud83d\udce6 {deal.get('product', 'Deal')}: \u20b9{deal['total']:,.0f}"
                )

    if reminders_created:
        reply_parts.append(f"\u23f0 {reminders_created} reminder(s) set")

    summary = structured.get("summary", "")
    if summary:
        reply_parts.append(f"\n{summary}")

    return " | ".join(reply_parts[:4]) + (f"\n\n{summary}" if summary else "")


async def get_today_notes(db: AsyncSession, user_id: str) -> str:
    """Get today's meeting notes."""
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(MeetingNote)
        .where(
            MeetingNote.user_id == user_id,
            MeetingNote.created_at >= today_start,
        )
        .order_by(MeetingNote.created_at.desc())
    )
    notes = result.scalars().all()

    if not notes:
        return "No meeting notes today."

    lines = [f"\ud83d\udcdd *Today's Notes* ({len(notes)})"]
    for i, note in enumerate(notes, 1):
        s = note.structured_json or {}
        summary = s.get("summary", note.raw_transcript[:100] if note.raw_transcript else "No details")
        people = ", ".join(note.people_mentioned or [])
        lines.append(f"\n{i}. {summary}")
        if people:
            lines.append(f"   People: {people}")

    return "\n".join(lines)


async def search_notes(db: AsyncSession, user_id: str, query: str) -> str:
    """Search meeting notes."""
    result = await db.execute(
        select(MeetingNote)
        .where(MeetingNote.user_id == user_id)
        .order_by(MeetingNote.created_at.desc())
        .limit(50)
    )
    notes = result.scalars().all()

    if not notes:
        return "No meeting notes found."

    # Use Gemini to find relevant notes
    notes_text = "\n".join(
        [
            f"ID {n.id}: {n.structured_json.get('summary', '') if n.structured_json else ''} | People: {', '.join(n.people_mentioned or [])} | {n.raw_transcript[:200] if n.raw_transcript else ''}"
            for n in notes
        ]
    )

    relevant = await call_gemini(
        "You are a search assistant. Find the most relevant meeting notes for the user's query. Return a brief, helpful summary of what you found. Keep it short for WhatsApp.",
        f"Query: {query}\n\nMeeting notes:\n{notes_text}",
        user_id=user_id,
    )

    return relevant
