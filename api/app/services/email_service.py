"""
Sam Email Intelligence — WORLD CLASS.

Multi-account support. Smart account detection. Primary 50 emails.
Subscription tracking. Bill detection. Ramble-to-email.
Sam NEVER sends without explicit permission.
"""

import logging
import imaplib
import smtplib
import ssl
import email as email_lib
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import asyncio
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..models import EmailConfig, User, AgentSoul
from ..config import settings
from .llm import call_gemini, call_gemini_json

logger = logging.getLogger("samva.email")

IMAP_SERVERS = {
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "googlemail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "outlook.com": ("imap-mail.outlook.com", "smtp-mail.outlook.com"),
    "hotmail.com": ("imap-mail.outlook.com", "smtp-mail.outlook.com"),
    "live.com": ("imap-mail.outlook.com", "smtp-mail.outlook.com"),
    "yahoo.com": ("imap.mail.yahoo.com", "smtp.mail.yahoo.com"),
    "zoho.com": ("imap.zoho.com", "smtp.zoho.com"),
    "zoho.in": ("imap.zoho.in", "smtp.zoho.in"),
    "rediffmail.com": ("imap.rediffmail.com", "smtp.rediffmail.com"),
}

GMAIL_GUIDE = """*Gmail App Password Setup:*

1. Go to myaccount.google.com
2. Security > 2-Step Verification > Turn ON
3. Go to myaccount.google.com/apppasswords
4. Select app: Mail, Device: Other (type "Samva")
5. Click Generate
6. Copy the 16-character password

Then send me:
*connect email your@gmail.com xxxx xxxx xxxx xxxx*

Multiple accounts? Connect as many as you want!
I'll figure out which is personal, work, or business."""


def _get_servers(email_addr):
    domain = email_addr.split("@")[-1].lower()
    return IMAP_SERVERS.get(domain, (f"imap.{domain}", f"smtp.{domain}"))


def _encrypt(password):
    if not settings.encryption_key:
        return password
    try:
        from cryptography.fernet import Fernet
        return Fernet(settings.encryption_key.encode()).encrypt(password.encode()).decode()
    except Exception:
        return password


def _decrypt(encrypted):
    if not settings.encryption_key:
        return encrypted
    try:
        from cryptography.fernet import Fernet
        return Fernet(settings.encryption_key.encode()).decrypt(encrypted.encode()).decode()
    except Exception:
        return encrypted


async def handle_email_command(db: AsyncSession, user_id: str, text: str) -> str:
    """Master email router."""
    lower = text.lower().strip()

    if lower.startswith("connect email"):
        return await connect_email(db, user_id, text)

    if any(w in lower for w in ["gmail guide", "app password", "how to connect", "email kaise connect"]):
        return GMAIL_GUIDE

    if any(w in lower for w in ["check mail", "check my mail", "check email", "my mail",
                                  "emails", "mail check", "mail dikhao", "email dikhao",
                                  "show emails", "show mail"]):
        return await check_all_accounts(db, user_id)

    if any(w in lower for w in ["summarize mail", "email summary", "important mail",
                                  "critical mail", "bills", "subscriptions"]):
        return await smart_email_summary(db, user_id)

    if any(w in lower for w in ["email accounts", "my accounts", "kitne email", "which email"]):
        return await list_accounts(db, user_id)

    # Ramble to email — draft
    return await draft_email(db, user_id, text)


# ── Multi-Account Management ────────────────────────────────────

async def connect_email(db: AsyncSession, user_id: str, text: str) -> str:
    """Connect email with smart account type detection."""
    parts = text.strip().split()
    if len(parts) < 4:
        return "Format: *connect email your@gmail.com your_app_password*\n\nGmail? Type 'gmail guide'"

    email_addr = parts[2]
    password = "".join(parts[3:]).replace(" ", "")

    if "@" not in email_addr:
        return "Invalid email. Example: *connect email ritu@gmail.com abcd1234efgh5678*"

    imap_host, smtp_host = _get_servers(email_addr)

    # Test IMAP
    def _test():
        try:
            mail = imaplib.IMAP4_SSL(imap_host, 993)
            mail.login(email_addr, password)
            mail.select("INBOX")
            _, data = mail.search(None, "UNSEEN")
            unread = len(data[0].split()) if data[0] else 0
            mail.logout()
            return True, unread, ""
        except imaplib.IMAP4.error as e:
            return False, 0, str(e)
        except Exception as e:
            return False, 0, str(e)

    success, unread, error = await asyncio.get_event_loop().run_in_executor(None, _test)

    if not success:
        if "AUTHENTICATION" in error.upper():
            return "Login fail \u274c\n\nGmail ke liye *App Password* chahiye.\nType 'gmail guide' for setup."
        return f"Connection failed: {error[:80]}"

    # Smart account type detection
    domain = email_addr.split("@")[-1].lower()
    account_type = "personal"
    if domain in ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com"):
        account_type = "personal"
    elif "company" in domain or "corp" in domain or "work" in domain:
        account_type = "work"
    else:
        # Custom domain = likely business
        account_type = "business"

    # Check how many accounts user has
    existing_all = await db.execute(
        select(EmailConfig).where(EmailConfig.user_id == user_id)
    )
    all_accounts = existing_all.scalars().all()
    is_first = len(all_accounts) == 0

    # Check if this email already exists
    existing = await db.execute(
        select(EmailConfig).where(
            EmailConfig.user_id == user_id, EmailConfig.email_address == email_addr
        )
    )
    config = existing.scalar_one_or_none()

    encrypted = _encrypt(password)
    if config:
        config.password_encrypted = encrypted
        config.imap_host = imap_host
        config.smtp_host = smtp_host
        config.enabled = True
        config.account_type = account_type
    else:
        db.add(EmailConfig(
            user_id=user_id, email_address=email_addr,
            imap_host=imap_host, imap_port=993,
            smtp_host=smtp_host, smtp_port=587,
            password_encrypted=encrypted, enabled=True,
            account_type=account_type, is_primary=is_first,
        ))

    await db.commit()

    total = len(all_accounts) + (0 if config else 1)
    type_emoji = {"personal": "\U0001f464", "work": "\U0001f4bc", "business": "\U0001f3e2"}.get(account_type, "\U0001f4e7")

    reply = (
        f"Email connected! \u2705 {type_emoji}\n"
        f"*{email_addr}* ({account_type})\n"
        f"\U0001f4ec {unread} unread\n"
    )
    if total > 1:
        reply += f"\nYou have {total} email accounts connected."
    reply += "\n\nBolo 'check mail' kabhi bhi!"
    return reply


async def list_accounts(db: AsyncSession, user_id: str) -> str:
    """Show all connected email accounts."""
    result = await db.execute(
        select(EmailConfig).where(EmailConfig.user_id == user_id, EmailConfig.enabled == True)
    )
    accounts = result.scalars().all()

    if not accounts:
        return "Koi email connected nahi hai.\n*connect email your@gmail.com password*"

    lines = [f"\U0001f4e7 *Your email accounts ({len(accounts)}):*\n"]
    for i, acc in enumerate(accounts, 1):
        primary = " \u2b50" if acc.is_primary else ""
        type_emoji = {"personal": "\U0001f464", "work": "\U0001f4bc", "business": "\U0001f3e2"}.get(acc.account_type, "")
        lines.append(f"{i}. {type_emoji} {acc.email_address} ({acc.account_type}){primary}")

    lines.append("\nBolo 'check mail' for all, ya 'work mail' for specific account.")
    return "\n".join(lines)


# ── Email Reading — Smart, Multi-Account ─────────────────────────

async def check_all_accounts(db: AsyncSession, user_id: str, count_per: int = 10) -> str:
    """Read all connected accounts. Smart summary with Gemini."""
    result = await db.execute(
        select(EmailConfig).where(EmailConfig.user_id == user_id, EmailConfig.enabled == True)
    )
    accounts = result.scalars().all()

    if not accounts:
        return "Email connected nahi hai.\n*connect email your@gmail.com password*\nGmail? Type 'gmail guide'"

    if len(accounts) == 1:
        return await _read_account(accounts[0], user_id, count_per)

    # Multiple accounts — show summary of each
    lines = []
    for acc in accounts:
        summary = await _read_account(acc, user_id, count_per, brief=True)
        if summary:
            lines.append(summary)

    if not lines:
        return "\U0001f4ed All inboxes clean!"

    return "\n\n".join(lines) + "\n\nKisi mail ka detail chahiye? Account name ya number batao."


async def _read_account(config: EmailConfig, user_id: str, count: int = 10, brief: bool = False) -> str:
    """Read one email account with AI summarization."""
    try:
        password = _decrypt(config.password_encrypted)
        imap_host = config.imap_host or _get_servers(config.email_address)[0]

        def _fetch():
            mail = imaplib.IMAP4_SSL(imap_host, 993)
            mail.login(config.email_address, password)
            mail.select("INBOX")

            # Get PRIMARY first (Gmail) or UNSEEN
            try:
                # Gmail: search primary category
                _, data = mail.search(None, 'X-GM-RAW "category:primary"')
                if not data[0]:
                    _, data = mail.search(None, "UNSEEN")
            except Exception:
                _, data = mail.search(None, "UNSEEN")

            if not data[0]:
                _, data = mail.search(None, "ALL")

            ids = data[0].split()
            unread_count = len(ids)
            ids = ids[-count:]  # Last N
            emails = []

            for eid in reversed(ids):
                try:
                    _, msg_data = mail.fetch(eid, "(RFC822)")
                    if not msg_data or not msg_data[0]:
                        continue

                    msg = email_lib.message_from_bytes(msg_data[0][1])
                    subject = _decode_header(msg.get("Subject", ""))
                    sender = msg.get("From", "")[:80]
                    date = msg.get("Date", "")[:30]

                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                except Exception:
                                    pass
                                break
                    else:
                        try:
                            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                        except Exception:
                            pass

                    emails.append({"from": sender, "subject": subject, "body": body[:400], "date": date})
                except Exception:
                    continue

            mail.logout()
            return emails, unread_count

        emails, unread_count = await asyncio.get_event_loop().run_in_executor(None, _fetch)

        if not emails:
            if brief:
                return f"\U0001f4e7 *{config.email_address}* ({config.account_type}): Inbox clean!"
            return "\U0001f4ed Inbox clean — koi naya email nahi!"

        # AI summarization with smart detection
        email_text = "\n---\n".join(
            f"From: {e['from']}\nSubject: {e['subject']}\nBody: {e['body'][:300]}" for e in emails
        )

        prompt = """Summarize these emails for a WhatsApp user. Be SMART about it:

For each email, give ONE line. But also DETECT and FLAG:
- 🔴 URGENT: deadlines, complaints, time-sensitive
- 💰 BILL/PAYMENT: utility bills, subscription charges, EMI
- 🔄 SUBSCRIPTION: renewal notices, auto-debit alerts
- 📋 ACTION NEEDED: forms to fill, replies expected

After the list, add:
- Total bills/payments mentioned with amounts if visible
- Any subscriptions detected
- Which emails need reply TODAY

Keep it SHORT — WhatsApp format."""

        summary = await call_gemini(prompt, f"Inbox ({unread_count} unread):\n\n{email_text}",
                                      user_id=user_id, max_tokens=500)

        type_emoji = {"personal": "\U0001f464", "work": "\U0001f4bc", "business": "\U0001f3e2"}.get(config.account_type, "\U0001f4e7")
        header = f"{type_emoji} *{config.email_address}* ({unread_count} unread)"

        if brief:
            # Short version for multi-account view
            short = summary.split("\n")[0] if summary else "No summary"
            return f"{header}\n{short}"

        return f"{header}\n\n{summary}\n\nReply karna hai? Batao — main draft kar dungi."

    except imaplib.IMAP4.error as e:
        if "AUTHENTICATION" in str(e).upper():
            return f"Login expired for {config.email_address}. Reconnect: *connect email {config.email_address} new_password*"
        return f"Email check failed: {str(e)[:60]}"
    except Exception as e:
        logger.error(f"Email read error: {e}", exc_info=True)
        return f"Email check mein problem — thodi der mein try karo."


async def smart_email_summary(db: AsyncSession, user_id: str) -> str:
    """Deep summary — bills, subscriptions, critical flags across ALL accounts."""
    result = await db.execute(
        select(EmailConfig).where(EmailConfig.user_id == user_id, EmailConfig.enabled == True)
    )
    accounts = result.scalars().all()
    if not accounts:
        return "Email connected nahi hai. Type 'connect email' to setup."

    all_emails = []
    for acc in accounts:
        try:
            password = _decrypt(acc.password_encrypted)
            imap_host = acc.imap_host or _get_servers(acc.email_address)[0]

            def _fetch_acc(host=imap_host, addr=acc.email_address, pwd=password):
                mail = imaplib.IMAP4_SSL(host, 993)
                mail.login(addr, pwd)
                mail.select("INBOX")
                _, data = mail.search(None, "UNSEEN")
                if not data[0]:
                    _, data = mail.search(None, "ALL")
                ids = data[0].split()[-15:]
                emails = []
                for eid in reversed(ids):
                    try:
                        _, msg_data = mail.fetch(eid, "(RFC822)")
                        if not msg_data or not msg_data[0]:
                            continue
                        msg = email_lib.message_from_bytes(msg_data[0][1])
                        subject = _decode_header(msg.get("Subject", ""))
                        sender = msg.get("From", "")[:60]
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain":
                                    try:
                                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                    except Exception:
                                        pass
                                    break
                        else:
                            try:
                                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                            except Exception:
                                pass
                        emails.append({"from": sender, "subject": subject, "body": body[:200], "account": addr})
                    except Exception:
                        continue
                mail.logout()
                return emails

            acc_emails = await asyncio.get_event_loop().run_in_executor(None, _fetch_acc)
            all_emails.extend(acc_emails)
        except Exception:
            continue

    if not all_emails:
        return "\U0001f4ed All inboxes clean!"

    email_text = "\n---\n".join(
        f"Account: {e['account']}\nFrom: {e['from']}\nSubject: {e['subject']}\nBody: {e['body'][:150]}"
        for e in all_emails
    )

    summary = await call_gemini(
        """You are Sam analyzing ALL email accounts. Give a SMART executive summary:

1. 🔴 CRITICAL — missed deadlines, urgent replies needed
2. 💰 BILLS & PAYMENTS — amounts, due dates
3. 🔄 SUBSCRIPTIONS — renewals, auto-debits, cancellation opportunities
4. 📋 ACTION ITEMS — forms, applications, approvals pending
5. 💡 SMART TIP — one tip based on what you see (save money, don't miss deadline)

Keep it CONCISE. WhatsApp format. The user should feel like their smart assistant just scanned everything and gave the cliff notes.""",
        f"All emails across accounts:\n\n{email_text}",
        user_id=user_id, max_tokens=600,
    )

    return f"\U0001f9e0 *Smart Email Summary*\n\n{summary}"


# ── Ramble to Email ──────────────────────────────────────────────

async def draft_email(db: AsyncSession, user_id: str, text: str) -> str:
    """Draft professional email from ramble in any language."""
    # Get user context
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    soul_result = await db.execute(select(AgentSoul).where(AgentSoul.user_id == user_id))
    soul = soul_result.scalar_one_or_none()

    sender_name = user.name if user else "User"
    soul_ctx = soul.system_prompt[:300] if soul else ""

    extracted = await call_gemini_json(
        f"""Extract email details. Sender is {sender_name}.
Return JSON:
{{"to_name": "", "to_email": "", "subject_hint": "", "intent": "", "language": "English"}}""",
        text, user_id=user_id,
    )

    draft = await call_gemini(
        f"""Draft professional email. Sender: {sender_name}. {f'Context: {soul_ctx}' if soul_ctx else ''}
Language: {extracted.get('language', 'English')}. Include Subject: line. Sign off with {sender_name}.""",
        f"Write: {extracted.get('intent', text)}", user_id=user_id,
    )

    # Save to DB — survives restarts
    from ..models import PendingEmailDraft
    from sqlalchemy import delete
    await db.execute(delete(PendingEmailDraft).where(PendingEmailDraft.user_id == user_id))
    db.add(PendingEmailDraft(
        user_id=user_id,
        to_email=extracted.get("to_email", ""),
        draft_text=draft,
    ))
    await db.commit()

    reply = f"*Draft ready* \u2713\n\n{draft}\n\n"
    if extracted.get("to_email"):
        reply += "Bhejun? (haan/nahi)"
    else:
        reply += "Kisko bhejein? Email address batao."
    return reply


async def confirm_send_email(db: AsyncSession, user_id: str) -> str:
    """Send the pending draft after owner confirms."""
    from ..models import PendingEmailDraft
    from sqlalchemy import delete as sql_delete

    result = await db.execute(
        select(PendingEmailDraft).where(PendingEmailDraft.user_id == user_id)
        .order_by(PendingEmailDraft.created_at.desc()).limit(1)
    )
    pending = result.scalar_one_or_none()
    if not pending:
        return "Koi pending draft nahi hai."

    to_email = pending.to_email
    draft = pending.draft_text
    if not to_email:
        return "Email address batao — kisko bhejni hai?"

    # Get primary email config
    result = await db.execute(
        select(EmailConfig).where(
            EmailConfig.user_id == user_id, EmailConfig.enabled == True
        ).order_by(EmailConfig.is_primary.desc())
    )
    config = result.scalars().first()
    if not config:
        from ..models import PendingEmailDraft
        from sqlalchemy import delete as sql_del
        await db.execute(sql_del(PendingEmailDraft).where(PendingEmailDraft.user_id == user_id))
        await db.commit()
        return "Email not configured. Type 'connect email' first."

    try:
        password = _decrypt(config.password_encrypted)

        subject = "Email from Samva"
        body = draft
        if "Subject:" in draft:
            for line in draft.split("\n"):
                if line.strip().startswith("Subject:"):
                    subject = line.strip().replace("Subject:", "").strip()
                    body = draft.replace(line, "").strip()
                    break

        msg = MIMEMultipart()
        msg["From"] = config.email_address
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        ctx = ssl.create_default_context()
        with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
            server.starttls(context=ctx)
            server.login(config.email_address, password)
            server.send_message(msg)

        await db.execute(sql_delete(PendingEmailDraft).where(PendingEmailDraft.user_id == user_id))
        await db.commit()
        return f"Email sent to {to_email} \u2705"
    except Exception as e:
        logger.error(f"Email send error: {e}")
        await db.execute(sql_delete(PendingEmailDraft).where(PendingEmailDraft.user_id == user_id))
        await db.commit()
        return f"Send fail: {str(e)[:60]}"


async def has_pending_draft(db: AsyncSession, user_id: str) -> bool:
    from ..models import PendingEmailDraft
    result = await db.execute(
        select(PendingEmailDraft).where(PendingEmailDraft.user_id == user_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def cancel_pending_draft(db: AsyncSession, user_id: str):
    from ..models import PendingEmailDraft
    from sqlalchemy import delete as sql_delete
    await db.execute(sql_delete(PendingEmailDraft).where(PendingEmailDraft.user_id == user_id))
    await db.commit()


# ── Morning Brief ────────────────────────────────────────────────

async def get_morning_email_summary(db: AsyncSession, user_id: str) -> str:
    """Short email summary for morning brief."""
    result = await db.execute(
        select(EmailConfig).where(EmailConfig.user_id == user_id, EmailConfig.enabled == True)
    )
    accounts = result.scalars().all()
    if not accounts:
        return ""

    total_unread = 0
    for acc in accounts:
        try:
            password = _decrypt(acc.password_encrypted)
            imap_host = acc.imap_host or _get_servers(acc.email_address)[0]

            def _count(host=imap_host, addr=acc.email_address, pwd=password):
                try:
                    mail = imaplib.IMAP4_SSL(host, 993)
                    mail.login(addr, pwd)
                    mail.select("INBOX")
                    _, data = mail.search(None, "UNSEEN")
                    count = len(data[0].split()) if data[0] else 0
                    mail.logout()
                    return count
                except Exception:
                    return 0

            total_unread += await asyncio.get_event_loop().run_in_executor(None, _count)
        except Exception:
            continue

    if total_unread == 0:
        return "\n\U0001f4e7 Email: All clear!"
    return f"\n\U0001f4e7 Email: *{total_unread} unread* across {len(accounts)} account(s) -- bolo 'check mail'"


# ── Helpers ──────────────────────────────────────────────────────

def _decode_header(raw):
    if not raw:
        return ""
    try:
        parts = decode_header(raw)
        return "".join(p.decode(enc or "utf-8") if isinstance(p, bytes) else p for p, enc in parts)
    except Exception:
        return str(raw)[:80]
