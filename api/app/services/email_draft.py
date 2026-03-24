import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from cryptography.fernet import Fernet
from ..models import EmailConfig, User
from ..config import settings
from .llm import call_gemini, call_gemini_json

logger = logging.getLogger("samva.email")

# In-memory pending drafts per user
_pending_drafts: dict[str, dict] = {}

IMAP_SERVERS = {
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "googlemail.com": ("imap.gmail.com", "smtp.gmail.com"),
    "outlook.com": ("imap-mail.outlook.com", "smtp-mail.outlook.com"),
    "hotmail.com": ("imap-mail.outlook.com", "smtp-mail.outlook.com"),
    "yahoo.com": ("imap.mail.yahoo.com", "smtp.mail.yahoo.com"),
    "zoho.com": ("imap.zoho.com", "smtp.zoho.com"),
    "rediffmail.com": ("imap.rediffmail.com", "smtp.rediffmail.com"),
}


def _get_servers(email: str) -> tuple[str, str]:
    """Auto-detect IMAP/SMTP servers by email domain."""
    domain = email.split("@")[-1].lower()
    if domain in IMAP_SERVERS:
        return IMAP_SERVERS[domain]
    return (f"imap.{domain}", f"smtp.{domain}")


def _encrypt_password(password: str) -> str:
    if not settings.encryption_key:
        return password
    f = Fernet(settings.encryption_key.encode())
    return f.encrypt(password.encode()).decode()


def _decrypt_password(encrypted: str) -> str:
    if not settings.encryption_key:
        return encrypted
    f = Fernet(settings.encryption_key.encode())
    return f.decrypt(encrypted.encode()).decode()


async def draft_email(db: AsyncSession, user_id: str, text: str) -> str:
    """Draft a professional email from user's ramble."""
    # Check if user has email config
    result = await db.execute(
        select(EmailConfig).where(
            EmailConfig.user_id == user_id, EmailConfig.enabled == True
        )
    )
    email_config = result.scalar_one_or_none()

    # Extract email details using Gemini
    extracted = await call_gemini_json(
        """Extract email details from the user's message.
Return JSON:
{
    "to_name": "recipient name if mentioned",
    "to_email": "recipient email if mentioned",
    "subject_hint": "what the email is about",
    "intent": "brief description of what they want to say",
    "language": "language to write the email in (default: English)"
}""",
        text,
        user_id=user_id,
    )

    to_name = extracted.get("to_name", "")
    to_email = extracted.get("to_email", "")
    subject_hint = extracted.get("subject_hint", "")
    intent = extracted.get("intent", text)
    lang = extracted.get("language", "English")

    # Get user info for signature
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    sender_name = user.name if user else "User"

    # Draft the email
    draft = await call_gemini(
        f"""You are a professional email writer. Draft a polished, professional email.
Sender: {sender_name}
Recipient: {to_name or 'the recipient'}
Language: {lang}
Keep it concise and professional. Include a subject line at the top as "Subject: ..."
Sign off with {sender_name}'s name.""",
        f"Write this email: {intent}",
        user_id=user_id,
    )

    # Store pending draft
    _pending_drafts[user_id] = {
        "to_name": to_name,
        "to_email": to_email,
        "draft": draft,
        "has_email_config": email_config is not None,
    }

    reply = f"Draft ready \u2713\n\n{draft}\n\n"
    if to_email and email_config:
        reply += "Bhejun? (Yes/No)"
    elif to_email:
        reply += "Email sending isn't set up yet. You can copy this draft."
    else:
        reply += "Kisko bhejein? Email address batao."

    return reply


async def confirm_send(db: AsyncSession, user_id: str) -> str:
    """Confirm and send the pending draft."""
    draft_data = _pending_drafts.get(user_id)
    if not draft_data:
        return "No pending email draft. Tell me what you want to email!"

    if not draft_data.get("to_email"):
        return "I need the recipient's email address. Please share it."

    # Get email config
    result = await db.execute(
        select(EmailConfig).where(
            EmailConfig.user_id == user_id, EmailConfig.enabled == True
        )
    )
    email_config = result.scalar_one_or_none()

    if not email_config:
        del _pending_drafts[user_id]
        return "Email sending isn't configured yet. Please set up your email first."

    try:
        # Parse subject and body from draft
        draft = draft_data["draft"]
        subject = "Email from Samva"
        body = draft

        if "Subject:" in draft:
            parts = draft.split("\n", 1)
            for p in parts:
                if p.strip().startswith("Subject:"):
                    subject = p.strip().replace("Subject:", "").strip()
                    body = draft.replace(p, "").strip()
                    break

        # Send via SMTP
        password = _decrypt_password(email_config.password_encrypted)

        msg = MIMEMultipart()
        msg["From"] = email_config.email_address
        msg["To"] = draft_data["to_email"]
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        context = ssl.create_default_context()
        with smtplib.SMTP(email_config.smtp_host, email_config.smtp_port) as server:
            server.starttls(context=context)
            server.login(email_config.email_address, password)
            server.send_message(msg)

        del _pending_drafts[user_id]
        return f"Email sent to {draft_data['to_email']} \u2713"

    except Exception as e:
        logger.error(f"Email send error for {user_id}: {e}")
        del _pending_drafts[user_id]
        return f"Couldn't send the email: {str(e)[:100]}. Please check your email settings."


async def cancel_draft(user_id: str) -> str:
    """Cancel the pending draft."""
    if user_id in _pending_drafts:
        del _pending_drafts[user_id]
    return "Draft cancelled."


# ── IMAP Email Reading ───────────────────────────────────────────

async def read_emails(db: AsyncSession, user_id: str, count: int = 5) -> str:
    """Connect to IMAP, read unread emails, return summary."""
    import imaplib
    import email as email_lib
    from email.header import decode_header
    import asyncio

    result = await db.execute(
        select(EmailConfig).where(
            EmailConfig.user_id == user_id, EmailConfig.enabled == True
        )
    )
    email_config = result.scalar_one_or_none()

    if not email_config:
        return (
            "Email abhi connected nahi hai.\n\n"
            "Setup karne ke liye bhejo:\n"
            "*connect email yourname@gmail.com your_app_password*\n\n"
            "Gmail ke liye App Password chahiye — main guide bhej sakti hoon."
        )

    try:
        password = _decrypt_password(email_config.password_encrypted)
        imap_host = email_config.imap_host or _get_servers(email_config.email_address)[0]
        imap_port = email_config.imap_port or 993

        # Run IMAP in thread (blocking IO)
        def _fetch():
            mail = imaplib.IMAP4_SSL(imap_host, imap_port)
            mail.login(email_config.email_address, password)
            mail.select("INBOX")

            # Search for recent emails (last 3 days unseen, fallback to all recent)
            status, data = mail.search(None, "UNSEEN")
            if not data[0]:
                status, data = mail.search(None, "ALL")

            ids = data[0].split()
            if not ids:
                mail.logout()
                return []

            # Get last N
            ids = ids[-count:]
            emails = []

            for eid in reversed(ids):
                _, msg_data = mail.fetch(eid, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue

                msg = email_lib.message_from_bytes(msg_data[0][1])

                # Decode subject
                subject = ""
                raw_subject = msg.get("Subject", "")
                if raw_subject:
                    parts = decode_header(raw_subject)
                    subject = "".join(
                        p.decode(enc or "utf-8") if isinstance(p, bytes) else p
                        for p, enc in parts
                    )

                # Decode sender
                sender = msg.get("From", "")
                date = msg.get("Date", "")

                # Get body snippet
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
                    "from": sender[:60],
                    "subject": subject[:80],
                    "snippet": body[:150].replace("\n", " ").strip(),
                    "date": date[:25],
                })

            mail.logout()
            return emails

        emails_list = await asyncio.get_event_loop().run_in_executor(None, _fetch)

        if not emails_list:
            return "Inbox clean hai — koi naya email nahi! 📭"

        lines = [f"📧 *{len(emails_list)} emails:*\n"]
        for i, e in enumerate(emails_list, 1):
            lines.append(f"*{i}.* {e['from']}")
            lines.append(f"   {e['subject']}")
            if e["snippet"]:
                lines.append(f"   _{e['snippet'][:80]}_")
            lines.append("")

        lines.append("Kisi ko reply karna hai? Main draft kar deti hoon.")
        return "\n".join(lines)

    except imaplib.IMAP4.error as e:
        logger.error(f"IMAP auth error for {user_id}: {e}")
        return "Email login fail ho gaya. Password check karo — Gmail ke liye App Password chahiye, regular password nahi chalega."
    except Exception as e:
        logger.error(f"IMAP error for {user_id}: {e}", exc_info=True)
        return f"Email check mein problem aa gayi. Thodi der mein try karo."


async def connect_email(db: AsyncSession, user_id: str, email_addr: str, password: str) -> str:
    """Connect user's email via IMAP — test connection and save config."""
    import imaplib
    import asyncio

    imap_host, smtp_host = _get_servers(email_addr)

    # Test IMAP connection
    def _test():
        try:
            mail = imaplib.IMAP4_SSL(imap_host, 993)
            mail.login(email_addr, password)
            mail.logout()
            return True, ""
        except imaplib.IMAP4.error as e:
            return False, str(e)
        except Exception as e:
            return False, str(e)

    success, error = await asyncio.get_event_loop().run_in_executor(None, _test)

    if not success:
        return (
            f"Email connect fail: {error[:80]}\n\n"
            "Gmail ke liye:\n"
            "1. Google Account → Security → 2-Step Verification ON\n"
            "2. myaccount.google.com/apppasswords\n"
            "3. App Password generate karo\n"
            "4. Woh 16-char password bhejo"
        )

    # Save config
    encrypted_pass = _encrypt_password(password)

    # Check existing
    result = await db.execute(
        select(EmailConfig).where(
            EmailConfig.user_id == user_id, EmailConfig.email_address == email_addr
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.password_encrypted = encrypted_pass
        existing.imap_host = imap_host
        existing.smtp_host = smtp_host
        existing.enabled = True
    else:
        db.add(EmailConfig(
            user_id=user_id,
            email_address=email_addr,
            imap_host=imap_host,
            imap_port=993,
            smtp_host=smtp_host,
            smtp_port=587,
            password_encrypted=encrypted_pass,
            enabled=True,
        ))

    await db.commit()
    return f"Email connected ✓ — {email_addr}\n\nAb \"check my mail\" bolo kabhi bhi!"
