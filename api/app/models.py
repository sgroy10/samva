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
