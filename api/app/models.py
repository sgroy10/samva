from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, DateTime, Time, JSON, Date,
    UniqueConstraint
)
from sqlalchemy.sql import func
from .database import Base
import datetime


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    phone = Column(String(20), unique=True, nullable=True)
    name = Column(String(100), nullable=True)
    email = Column(String(200), nullable=True)
    status = Column(String(20), default="onboarding")  # onboarding, active, paused, cancelled
    plan = Column(String(20), default="standard")
    paid_until = Column(DateTime, nullable=True)
    razorpay_id = Column(String(100), nullable=True)
    platform = Column(String(20), default="whatsapp")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class AgentSoul(Base):
    __tablename__ = "agent_souls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), unique=True, nullable=False)
    system_prompt = Column(Text, default="")
    business_type = Column(String(100), nullable=True)
    language_preference = Column(String(50), default="auto")
    voice_language = Column(String(50), default="auto")
    onboarding_complete = Column(Boolean, default=False)
    onboarding_step = Column(Integer, default=0)
    onboarding_context = Column(JSON, default=dict)
    daily_brief_time = Column(Time, default=datetime.time(9, 0))
    daily_brief_enabled = Column(Boolean, default=True)
    last_gold_brief_date = Column(Date, nullable=True)
    network_permission = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    role = Column(String(20), nullable=False)  # user, assistant
    content = Column(Text, nullable=False)

    def __init__(self, **kwargs):
        # Sanitize content to remove surrogate characters that PostgreSQL rejects
        if 'content' in kwargs and kwargs['content']:
            kwargs['content'] = kwargs['content'].encode('utf-8', errors='replace').decode('utf-8', errors='replace')
        super().__init__(**kwargs)
    created_at = Column(DateTime, default=func.now())


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    full_name = Column(String(200), nullable=True)
    company = Column(String(200), nullable=True)
    designation = Column(String(200), nullable=True)
    phone = Column(String(50), nullable=True)
    email = Column(String(200), nullable=True)
    address = Column(Text, nullable=True)
    website = Column(String(200), nullable=True)
    tag = Column(String(50), nullable=True)  # client, supplier, partner, personal
    notes = Column(Text, nullable=True)
    source = Column(String(20), default="card")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class MeetingNote(Base):
    __tablename__ = "meeting_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    raw_transcript = Column(Text, nullable=True)
    structured_json = Column(JSON, default=dict)
    location = Column(String(200), nullable=True)
    people_mentioned = Column(JSON, default=list)
    action_items = Column(JSON, default=list)
    follow_up_date = Column(DateTime, nullable=True)
    email_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    text = Column(Text, nullable=False)
    remind_at = Column(DateTime, nullable=False)
    repeat_type = Column(String(20), default="none")  # none, daily, weekly, monthly, yearly
    type = Column(String(20), default="custom")  # birthday, anniversary, payment, meeting, custom
    sent = Column(Boolean, default=False)
    is_urgent = Column(Boolean, default=False)
    call_attempted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())


class UserMemory(Base):
    __tablename__ = "user_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    key = Column(String(200), nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_memory_user_key"),
    )


class StockWatchlist(Base):
    __tablename__ = "stock_watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    symbol = Column(String(50), nullable=False)
    market = Column(String(20), default="NSE")
    target_high = Column(Float, nullable=True)
    target_low = Column(Float, nullable=True)
    last_price = Column(Float, nullable=True)
    last_checked = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())


class EmailConfig(Base):
    __tablename__ = "email_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    email_address = Column(String(200), nullable=False)
    imap_host = Column(String(200), nullable=True)
    smtp_host = Column(String(200), nullable=True)
    imap_port = Column(Integer, default=993)
    smtp_port = Column(Integer, default=587)
    password_encrypted = Column(Text, nullable=True)
    enabled = Column(Boolean, default=True)
    account_type = Column(String(50), default="personal")  # personal, work, business, side_hustle
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())


class EnterpriseInquiry(Base):
    __tablename__ = "enterprise_inquiries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    phone = Column(String(20), nullable=False)
    company = Column(String(200), nullable=True)
    system_needed = Column(Text, nullable=True)
    status = Column(String(20), default="new")
    created_at = Column(DateTime, default=func.now())


class SessionHealth(Base):
    __tablename__ = "session_health"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), unique=True, nullable=False)
    status = Column(String(20), default="disconnected")
    last_connected = Column(DateTime, nullable=True)
    last_qr_generated = Column(DateTime, nullable=True)
    reconnect_attempts = Column(Integer, default=0)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class DetectedPattern(Base):
    """Patterns Sam detects from watching user behavior. Shadow tested before proposing."""
    __tablename__ = "detected_patterns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    pattern_type = Column(String(50), nullable=False)  # gold_brief, morning_inbox, contact_priority
    pattern_data = Column(JSON, default=dict)           # trigger conditions, content spec
    confidence = Column(Float, default=0.0)
    detected_at = Column(DateTime, default=func.now())
    shadow_tested = Column(Boolean, default=False)
    shadow_success_rate = Column(Float, nullable=True)
    status = Column(String(20), default="detected")     # detected → shadow → proposed → active → declined
    proposed_at = Column(DateTime, nullable=True)
    user_response = Column(String(20), nullable=True)   # accepted, declined, ignored


class ActiveBehavior(Base):
    """User-approved behaviors that Sam executes automatically."""
    __tablename__ = "active_behaviors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    pattern_type = Column(String(50), nullable=False)
    trigger_spec = Column(JSON, default=dict)            # time, condition
    content_spec = Column(JSON, default=dict)            # what to generate/send
    created_at = Column(DateTime, default=func.now())
    last_executed = Column(DateTime, nullable=True)
    execution_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


class PendingReply(Base):
    """Draft reply waiting for owner confirmation. Survives restarts."""
    __tablename__ = "pending_replies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    chat_jid = Column(String(100), nullable=False)
    chat_name = Column(String(200), nullable=True)
    reply_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=func.now())


class PendingEmailDraft(Base):
    """Draft email waiting for owner confirmation. Survives restarts."""
    __tablename__ = "pending_email_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    to_email = Column(String(200), nullable=True)
    draft_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=func.now())


class ChatMessage(Base):
    """ALL WhatsApp messages — buffered every 15 min for chat intelligence."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    chat_id = Column(String(100), nullable=False)
    chat_name = Column(String(200), nullable=True)
    sender_name = Column(String(100), nullable=True)
    content = Column(Text, nullable=False)
    from_me = Column(Boolean, default=False)
    msg_timestamp = Column(Integer, nullable=True)
    analyzed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())


class ChatInsight(Base):
    """AI-generated insights from chat analysis."""
    __tablename__ = "chat_insights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    chat_id = Column(String(100), nullable=True)
    chat_name = Column(String(200), nullable=True)
    summary = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)
    suggested_reply = Column(Text, nullable=True)
    priority = Column(String(20), default="medium")
    delivered = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())


class InboxMessage(Base):
    """ALL WhatsApp messages — from customers, contacts, groups. Sam's inbox."""
    __tablename__ = "inbox_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)       # Sam owner
    chat_id = Column(String(100), nullable=False)       # WhatsApp JID of the sender
    chat_name = Column(String(200), nullable=True)      # Contact/group name
    sender_name = Column(String(200), nullable=True)    # Push name
    sender_id = Column(String(100), nullable=True)
    content = Column(Text, nullable=False)
    from_me = Column(Boolean, default=False)            # Owner's outgoing replies
    msg_timestamp = Column(Integer, nullable=False)     # Unix timestamp
    replied = Column(Boolean, default=False)             # Has owner replied to this thread
    auto_replied = Column(Boolean, default=False)        # Did Sam auto-reply
    created_at = Column(DateTime, default=func.now())


class SoulEvolution(Base):
    __tablename__ = "soul_evolutions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    week_date = Column(Date, nullable=False)
    patterns_found = Column(JSON, default=list)
    new_behaviors = Column(JSON, default=list)
    evolution_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())


class NetworkConnection(Base):
    __tablename__ = "network_connections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    need_type = Column(String(100), nullable=True)
    need_description = Column(Text, nullable=True)
    offer_type = Column(String(100), nullable=True)
    offer_description = Column(Text, nullable=True)
    location = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    permission_given = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())


class UserSkill(Base):
    """Self-built skill — Sam wrote this code to serve a specific user need."""
    __tablename__ = "user_skills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False)
    skill_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)      # what this skill does
    trigger_keywords = Column(JSON, default=list)    # words that activate this skill
    api_url = Column(String(500), nullable=True)     # the API it connects to
    python_code = Column(Text, nullable=False)       # the connector code Sam wrote
    test_result = Column(Text, nullable=True)        # output from test run
    test_passed = Column(Boolean, default=False)
    is_active = Column(Boolean, default=False)       # only True after test passes
    build_log = Column(Text, nullable=True)          # full log of how Sam built this
    created_at = Column(DateTime, default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "skill_name", name="uq_user_skill"),
    )


class NetworkMatch(Base):
    """Tracks a pending match between two users. Both must confirm before intro."""
    __tablename__ = "network_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_a_id = Column(String(36), nullable=False)
    user_b_id = Column(String(36), nullable=False)
    match_reason = Column(Text, nullable=True)  # what matched
    user_a_confirmed = Column(Boolean, default=False)
    user_b_confirmed = Column(Boolean, default=False)
    introduced = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())


class FeedbackSignal(Base):
    """Track user reactions to Sam's proactive messages.
    Sam learns: do more of what user likes, less of what they ignore."""
    __tablename__ = "feedback_signals"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(36), nullable=False, index=True)
    feature = Column(String(50), nullable=False)
    signal = Column(String(20), nullable=False)
    context = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())


class ApiCostLog(Base):
    """Every API call logged with cost. Powers the admin cost dashboard."""
    __tablename__ = "api_cost_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=True)
    api_type = Column(String(30), nullable=False)    # openrouter, gemini_tts, gemini_transcribe, perplexity, gemlens, jewelcraft
    model = Column(String(100), nullable=True)       # google/gemini-2.5-flash, anthropic/claude-sonnet-4, etc.
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)            # calculated cost in USD
    cost_inr = Column(Float, default=0.0)            # calculated cost in INR (USD * 84)
    endpoint = Column(String(100), nullable=True)    # what triggered this: chat, tts, transcribe, skill_build, etc.
    created_at = Column(DateTime, default=func.now())
