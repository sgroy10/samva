"""
Memory Beast — Sam's total recall engine.

Sam remembers EVERYTHING. Every conversation, every topic, every person mentioned,
every request ever made. When the user references something from days, weeks, or
months ago, Sam finds it instantly and responds as if she remembers.

This is what makes Sam feel magical — users can forget, Sam never does.

Architecture:
1. detect_memory_need() — Is this message referencing something from the past?
2. search_conversations() — Full-text search across ALL conversation history
3. search_inbox() — Search inbox messages for contact/topic references
4. build_memory_context() — Compile relevant history into a prompt injection
"""

import logging
import re
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, text as sql_text
from ..models import Conversation, InboxMessage, UserMemory, Contact

logger = logging.getLogger("samva.memory_beast")


# Words that signal the user is referencing something from the past
RECALL_SIGNALS = [
    # English
    "remember", "what about", "what happened", "did i", "did you", "did we",
    "last time", "before", "earlier", "previously", "that thing",
    "you said", "i said", "i told you", "i asked", "we talked",
    "the other day", "few days", "last week", "yesterday",
    "follow up", "update on", "status of", "any update",
    "what was", "where was", "when was", "who was",
    # Hindi
    "yaad hai", "kya hua", "wo wala", "pehle", "kal", "parso",
    "maine bola tha", "tune bola tha", "humne baat ki thi",
    "wo baat", "wo cheez", "kab hua", "kaise hua",
    "update de", "kya status", "aage kya hua",
    "bataya tha", "pucha tha", "bola tha",
]

# Topic extraction patterns — nouns/proper nouns that are likely references
TOPIC_WORDS_TO_SKIP = {
    "i", "you", "me", "my", "sam", "samva", "the", "a", "an", "is", "was",
    "are", "were", "what", "how", "when", "where", "who", "that", "this",
    "do", "did", "can", "will", "about", "with", "from", "for", "and",
    "but", "or", "not", "no", "yes", "ok", "hi", "hello", "hey",
    "please", "thanks", "thank", "kya", "hai", "tha", "thi", "the",
    "ka", "ki", "ke", "ko", "se", "mein", "pe", "ne", "aur", "bhi",
    "nahi", "haan", "na", "toh", "main", "mera", "meri", "mere",
    "wo", "woh", "ye", "yeh", "us", "is", "isko", "usko",
}


def detect_memory_need(text: str) -> bool:
    """Check if this message is referencing something from the past."""
    if not text or len(text) < 5:
        return False
    lower = text.lower()
    # Direct recall signals
    if any(signal in lower for signal in RECALL_SIGNALS):
        return True
    # Question about a specific topic (contains a proper noun / specific term + question word)
    has_question = any(w in lower for w in ["?", "kya", "what", "how", "where", "when", "status", "update"])
    has_specific = len([w for w in text.split() if len(w) > 3 and w.lower() not in TOPIC_WORDS_TO_SKIP]) >= 2
    return has_question and has_specific


def extract_search_terms(text: str) -> list[str]:
    """Extract key search terms from a message for conversation search."""
    words = text.split()
    # Filter out common words, keep meaningful terms
    terms = []
    for w in words:
        clean = re.sub(r'[^\w]', '', w).lower()
        if clean and len(clean) > 2 and clean not in TOPIC_WORDS_TO_SKIP:
            terms.append(clean)
    return terms[:6]  # Max 6 search terms


async def search_conversations(db: AsyncSession, user_id: str, query: str, limit: int = 10) -> list[dict]:
    """
    Search ALL conversation history for relevant messages.
    Uses PostgreSQL ILIKE for each search term.
    Returns list of {role, content, created_at} ordered by relevance.
    """
    terms = extract_search_terms(query)
    if not terms:
        return []

    # Build OR conditions for each term
    conditions = []
    for term in terms:
        conditions.append(Conversation.content.ilike(f"%{term}%"))

    try:
        result = await db.execute(
            select(Conversation).where(
                Conversation.user_id == user_id,
                or_(*conditions),
            ).order_by(Conversation.created_at.desc()).limit(limit)
        )
        messages = result.scalars().all()

        return [
            {
                "role": m.role,
                "content": m.content[:300],  # Truncate for prompt injection
                "date": m.created_at.strftime("%d %b %Y, %I:%M %p") if m.created_at else "unknown",
                "days_ago": (datetime.utcnow() - m.created_at).days if m.created_at else 0,
            }
            for m in messages
        ]
    except Exception as e:
        logger.error(f"Conversation search error: {e}")
        return []


async def search_inbox(db: AsyncSession, user_id: str, query: str, limit: int = 5) -> list[dict]:
    """Search inbox messages from contacts for relevant context."""
    terms = extract_search_terms(query)
    if not terms:
        return []

    conditions = []
    for term in terms:
        conditions.append(InboxMessage.content.ilike(f"%{term}%"))
        conditions.append(InboxMessage.chat_name.ilike(f"%{term}%"))

    try:
        result = await db.execute(
            select(InboxMessage).where(
                InboxMessage.user_id == user_id,
                or_(*conditions),
            ).order_by(InboxMessage.msg_timestamp.desc()).limit(limit)
        )
        messages = result.scalars().all()

        return [
            {
                "from": m.chat_name or m.sender_name or "unknown",
                "content": m.content[:200],
                "date": m.created_at.strftime("%d %b") if m.created_at else "",
                "from_me": m.from_me,
            }
            for m in messages
        ]
    except Exception as e:
        logger.error(f"Inbox search error: {e}")
        return []


async def search_memories(db: AsyncSession, user_id: str, query: str) -> list[dict]:
    """Search UserMemory for relevant saved facts."""
    terms = extract_search_terms(query)
    if not terms:
        return []

    conditions = []
    for term in terms:
        conditions.append(UserMemory.key.ilike(f"%{term}%"))
        conditions.append(UserMemory.value.ilike(f"%{term}%"))

    try:
        result = await db.execute(
            select(UserMemory).where(
                UserMemory.user_id == user_id,
                ~UserMemory.key.startswith("_"),  # Skip internal keys
                or_(*conditions),
            ).limit(5)
        )
        memories = result.scalars().all()
        return [{"key": m.key, "value": m.value} for m in memories]
    except Exception as e:
        logger.error(f"Memory search error: {e}")
        return []


async def build_memory_context(db: AsyncSession, user_id: str, current_message: str) -> str:
    """
    The main function. Called by orchestrator BEFORE generating any response.

    1. Detects if message references the past
    2. Searches conversations, inbox, and memories
    3. Returns formatted context string for prompt injection

    Returns empty string if no relevant history found.
    """
    if not detect_memory_need(current_message):
        # Even without explicit recall signals, do a quick topic search
        # if the message mentions specific names or topics
        terms = extract_search_terms(current_message)
        # Only search if there are specific enough terms (proper nouns, specific topics)
        specific_terms = [t for t in terms if len(t) > 4]
        if len(specific_terms) < 1:
            return ""

    logger.info(f"[{user_id}] Memory Beast activated: '{current_message[:50]}...'")

    # Search all sources in parallel-ish
    conv_results = await search_conversations(db, user_id, current_message)
    inbox_results = await search_inbox(db, user_id, current_message)
    mem_results = await search_memories(db, user_id, current_message)

    if not conv_results and not inbox_results and not mem_results:
        return ""

    # Build context
    parts = []

    if conv_results:
        parts.append("PAST CONVERSATIONS (Sam remembers):")
        for c in conv_results[:5]:
            ago = f"{c['days_ago']} days ago" if c['days_ago'] > 0 else "today"
            parts.append(f"  [{ago}] {c['role']}: {c['content']}")

    if inbox_results:
        parts.append("\nRELATED INBOX MESSAGES:")
        for m in inbox_results[:3]:
            direction = "You said" if m["from_me"] else f"{m['from']} said"
            parts.append(f"  [{m['date']}] {direction}: {m['content']}")

    if mem_results:
        parts.append("\nSAVED MEMORIES:")
        for m in mem_results:
            parts.append(f"  {m['key']}: {m['value']}")

    context = "\n".join(parts)
    logger.info(f"[{user_id}] Memory Beast found {len(conv_results)} conversations, {len(inbox_results)} inbox, {len(mem_results)} memories")

    return f"""
MEMORY RECALL — Sam found relevant history for this message:
{context}

IMPORTANT: Use this context naturally. Don't say "I searched my database."
Instead say "Haan yaad hai!" or "Oh right!" as if you genuinely remember.
Reference specific dates, people, and details from the context above.
If the user asked about something and you found it — answer confidently.
If you found related but not exact matches — mention them helpfully.
"""
