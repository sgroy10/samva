"""
Sam Email Intelligence — not just read emails, MANAGE them.

- Check inbox with AI summarization
- Flag critical/urgent emails
- Draft and send replies
- Connect email with step-by-step Gmail guide
- Morning email summary in brief
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
from sqlalchemy import select
from ..models import EmailConfig
from ..config import settings
from .llm import call_gemini, call_gemini_json

logger = logging.getLogger("samva.email_service")


IMAP_SERVERS = {
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "googlemail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "outlook.com": ("imap-mail.outlook.com", "smtp-mail.outlook.com"),
    "hotmail.com": ("imap-mail.outlook.com", "smtp-mail.outlook.com"),
    "yahoo.com": ("imap.mail.yahoo.com", "smtp.mail.yahoo.com"),
    "zoho.com": ("imap.zoho.com", "smtp.zoho.com"),
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

(The 16 chars with spaces — I'll handle the rest)"""


def _get_servers(email_addr: str):
    domain = email_addr.split("@")[-1].lower()
    if domain in IMAP_SERVERS:
        return IMAP_SERVERS[domain]
    return (f"imap.{domain}", f"smtp.{domain}")


def _encrypt(password: str) -> str:
    if not settings.encryption_key:
        return password
    try:
        from cryptography.fernet import Fernet
        f = Fernet(settings.encryption_key.encode())
        return f.encrypt(password.encode()).decode()
    except Exception:
        return password


def _decrypt(encrypted: str) -> str:
    if not settings.encryption_key:
        return encrypted
    try:
        from cryptography.fernet import Fernet
        f = Fernet(settings.encryption_key.encode())
        return f.decrypt(encrypted.encode()).decode()
    except Exception:
        return encrypted


async def handle_email_command(db: AsyncSession, user_id: str, text: str) -> str:
    """
    Master email handler — routes all email commands.
    """
    lower = text.lower().strip()

    # Connect email
    if lower.startswith("connect email"):
        return await _connect_email(db, user_id, text)

    # Gmail guide
    if any(w in lower for w in ["gmail guide", "app password", "how to connect", "email kaise connect", "gmail setup"]):
        return GMAIL_GUIDE

    # Check mail
    if any(w in lower for w in ["check mail", "check my mail", "check email", "inbox", "my mail",
                                  "emails", "mail check", "mail dikhao", "email dikhao"]):
        return await check_emails(db, user_id)

    # Summarize emails
    if any(w in lower for w in ["summarize mail", "email summary", "mail summary", "important mail"]):
        return await check_emails(db, user_id, summarize=True)

    # Send/draft email
    return await draft_email(db, user_id, text)


async def _connect_email(db: AsyncSession, user_id: str, text: str) -> str:
    """Connect user's email — test IMAP and save config."""
    parts = text.strip().split()
    # Expected: connect email user@gmail.com password_here
    if len(parts) < 4:
        return (
            "Format: *connect email your@gmail.com your_app_password*\n\n"
            "Gmail ke liye App Password chahiye.\n"
            "Type 'gmail guide' for step-by-step setup."
        )

    email_addr = parts[2]
    # Handle Gmail app passwords with spaces (xxxx xxxx xxxx xxxx)
    password = " ".join(parts[3:]).replace(" ", "")

    if "@" not in email_addr:
        return "Invalid email address. Example: *connect email ritu@gmail.com abcd1234efgh5678*"

    imap_host, smtp_host = _get_servers(email_addr)

    # Test connection in thread
    def _test():
        try:
            mail = imaplib.IMAP4_SSL(imap_host, 993)
            mail.login(email_addr, password)
            # Get inbox count
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
        if "AUTHENTICATIONFAILED" in error or "Invalid credentials" in error:
            return (
                "Login fail ho gaya. \u274c\n\n"
                "Gmail ke liye *App Password* chahiye, regular password nahi chalega.\n\n"
                "Type 'gmail guide' for setup steps."
            )
        return f"Connection failed: {error[:100]}\n\nCheck email and password."

    # Save config
    encrypted = _encrypt(password)
    existing = await db.execute(
        select(EmailConfig).where(EmailConfig.user_id == user_id)
    )
    config = existing.scalar_one_or_none()

    if config:
        config.email_address = email_addr
        config.imap_host = imap_host
        config.smtp_host = smtp_host
        config.password_encrypted = encrypted
        config.enabled = True
    else:
        db.add(EmailConfig(
            user_id=user_id,
            email_address=email_addr,
            imap_host=imap_host, imap_port=993,
            smtp_host=smtp_host, smtp_port=587,
            password_encrypted=encrypted,
            enabled=True,
        ))

    await db.commit()

    return (
        f"Email connected! \u2705 — {email_addr}\n"
        f"\U0001f4ec {unread} unread emails in inbox.\n\n"
        f"Ab bolo 'check mail' kabhi bhi!\n"
        f"Ya voice note mein batao kya email bhejni hai — main draft kar dungi."
    )


async def check_emails(db: AsyncSession, user_id: str, count: int = 7, summarize: bool = False) -> str:
    """Read inbox, summarize with Gemini, flag critical ones."""
    config_result = await db.execute(
        select(EmailConfig).where(EmailConfig.user_id == user_id, EmailConfig.enabled == True)
    )
    config = config_result.scalar_one_or_none()

    if not config:
        return (
            "Email abhi connected nahi hai.\n\n"
            "Setup karne ke liye:\n"
            "*connect email your@gmail.com your_app_password*\n\n"
            "Gmail? Type 'gmail guide' for App Password setup."
        )

    try:
        password = _decrypt(config.password_encrypted)
        imap_host = config.imap_host or _get_servers(config.email_address)[0]

        def _fetch():
            mail = imaplib.IMAP4_SSL(imap_host, 993)
            mail.login(config.email_address, password)
            mail.select("INBOX")

            _, data = mail.search(None, "UNSEEN")
            if not data[0]:
                _, data = mail.search(None, "ALL")

            ids = data[0].split()
            if not ids:
                mail.logout()
                return [], 0

            unread_count = len(ids)
            ids = ids[-count:]
            emails = []

            for eid in reversed(ids):
                _, msg_data = mail.fetch(eid, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue

                msg = email_lib.message_from_bytes(msg_data[0][1])

                subject = ""
                raw_sub = msg.get("Subject", "")
                if raw_sub:
                    parts = decode_header(raw_sub)
                    subject = "".join(
                        p.decode(enc or "utf-8") if isinstance(p, bytes) else p
                        for p, enc in parts
                    )

                sender = msg.get("From", "")
                date = msg.get("Date", "")

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

                emails.append({
                    "from": sender[:80],
                    "subject": subject[:100],
                    "body": body[:500],
                    "date": date[:30],
                })

            mail.logout()
            return emails, unread_count

        emails, unread_count = await asyncio.get_event_loop().run_in_executor(None, _fetch)

        if not emails:
            return "\U0001f4ed Inbox clean — koi naya email nahi!"

        # Summarize with Gemini — flag critical ones
        email_text = "\n---\n".join(
            f"From: {e['from']}\nSubject: {e['subject']}\nDate: {e['date']}\nBody: {e['body'][:300]}"
            for e in emails
        )

        summary = await call_gemini(
            """You are an email assistant summarizing a WhatsApp user's inbox.
For each email, give ONE line summary. Flag critical/urgent ones with a red emoji.

Format:
1. [Sender name] — [one line summary]
2. [Sender name] — [one line summary] 🔴 URGENT

After the list:
- If any email needs immediate reply, say so
- If any has a deadline, mention it
- Keep everything SHORT — this is WhatsApp

End with: "Kisi ko reply karna hai? Batao aur main draft kar deti hoon."
""",
            f"Inbox ({unread_count} unread):\n\n{email_text}",
            user_id=user_id,
            max_tokens=500,
        )

        return f"\U0001f4e7 *Inbox* ({unread_count} unread)\n\n{summary}"

    except imaplib.IMAP4.error as e:
        if "AUTHENTICATIONFAILED" in str(e):
            return "Email login expired. Phir se connect karo: *connect email your@gmail.com app_password*"
        return f"Email check failed: {str(e)[:80]}"
    except Exception as e:
        logger.error(f"Email check error for {user_id}: {e}", exc_info=True)
        return "Email check mein problem. Thodi der mein try karo."


async def draft_email(db: AsyncSession, user_id: str, text: str) -> str:
    """Draft professional email from ramble in any language."""
    from ..models import User, AgentSoul

    config_result = await db.execute(
        select(EmailConfig).where(EmailConfig.user_id == user_id, EmailConfig.enabled == True)
    )
    config = config_result.scalar_one_or_none()

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    soul_result = await db.execute(select(AgentSoul).where(AgentSoul.user_id == user_id))
    soul = soul_result.scalar_one_or_none()

    sender_name = user.name if user else "User"
    soul_context = soul.system_prompt[:300] if soul else ""

    # Extract email details
    extracted = await call_gemini_json(
        f"""Extract email details from this message. Sender is {sender_name}.
Return JSON:
{{
    "to_name": "recipient name if mentioned",
    "to_email": "recipient email if mentioned",
    "subject_hint": "what the email is about",
    "intent": "what they want to say",
    "language": "language to write email in (default English)"
}}""",
        text,
        user_id=user_id,
    )

    to_email = extracted.get("to_email", "")
    intent = extracted.get("intent", text)
    lang = extracted.get("language", "English")

    draft = await call_gemini(
        f"""Draft a professional email.
Sender: {sender_name}
{f'Sender context: {soul_context}' if soul_context else ''}
Language: {lang}
Include Subject: line at top.
Sign off with {sender_name}'s name.
Keep it concise and professional.""",
        f"Write this email: {intent}",
        user_id=user_id,
    )

    reply = f"*Draft ready* \u2713\n\n{draft}\n\n"
    if to_email and config:
        reply += "Bhejun? (haan/nahi)"
    elif not config:
        reply += "Email sending set up nahi hai. Type 'connect email' to set up."
    else:
        reply += "Kisko bhejein? Email address batao."

    return reply


async def send_email(db: AsyncSession, user_id: str, to_email: str, subject: str, body: str) -> str:
    """Send email via SMTP."""
    config_result = await db.execute(
        select(EmailConfig).where(EmailConfig.user_id == user_id, EmailConfig.enabled == True)
    )
    config = config_result.scalar_one_or_none()
    if not config:
        return "Email not configured. Type 'connect email' first."

    try:
        password = _decrypt(config.password_encrypted)
        msg = MIMEMultipart()
        msg["From"] = config.email_address
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        context = ssl.create_default_context()
        with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
            server.starttls(context=context)
            server.login(config.email_address, password)
            server.send_message(msg)

        return f"Email sent to {to_email} \u2705"
    except Exception as e:
        logger.error(f"Email send error: {e}")
        return f"Email send fail: {str(e)[:80]}"


async def get_morning_email_summary(db: AsyncSession, user_id: str) -> str:
    """Short email summary for morning brief."""
    config_result = await db.execute(
        select(EmailConfig).where(EmailConfig.user_id == user_id, EmailConfig.enabled == True)
    )
    config = config_result.scalar_one_or_none()
    if not config:
        return ""

    try:
        password = _decrypt(config.password_encrypted)
        imap_host = config.imap_host or _get_servers(config.email_address)[0]

        def _count():
            try:
                mail = imaplib.IMAP4_SSL(imap_host, 993)
                mail.login(config.email_address, password)
                mail.select("INBOX")
                _, data = mail.search(None, "UNSEEN")
                count = len(data[0].split()) if data[0] else 0
                mail.logout()
                return count
            except Exception:
                return -1

        unread = await asyncio.get_event_loop().run_in_executor(None, _count)

        if unread < 0:
            return ""
        if unread == 0:
            return "\n\U0001f4e7 Email: Inbox clean!"

        return f"\n\U0001f4e7 Email: *{unread} unread* — bolo 'check mail' for details"

    except Exception:
        return ""
