"""
Sam's Message Formatter — beautiful WhatsApp messages.

Every Sam message goes through this before being sent.
Adds consistent styling, spacing, and Sam's signature warmth.

WhatsApp formatting:
*bold* _italic_ ~strikethrough~ ```monospace```
"""

import re
import logging

logger = logging.getLogger("samva.formatter")


def format_sam_message(text: str, message_type: str = "chat") -> str:
    """
    Format Sam's message for WhatsApp display.
    Adds consistent spacing, clean structure, and Sam's signature style.
    """
    if not text:
        return text

    # Don't format special signals
    if text.startswith("__PDF__") or text.startswith("__IMAGE__"):
        return text

    # Don't format emergency messages (already formatted)
    if "EMERGENCY" in text:
        return text

    # Clean up excessive newlines (more than 2 in a row → 2)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Clean up excessive spaces
    text = re.sub(r' {3,}', '  ', text)

    # Ensure bullet points are consistent
    text = text.replace('\u2022 ', '\u25b8 ')
    text = text.replace('\n- ', '\n\u25b8 ') if '\n- ' in text else text

    # Clean up markdown artifacts that Gemini sometimes adds
    text = text.replace('**', '*')  # Double bold → single bold (WhatsApp style)
    text = re.sub(r'#{1,3}\s+', '*', text)  # Markdown headers → bold

    # Add Sam's signature spacing for longer messages
    if len(text) > 200 and message_type == "chat":
        # Add thin separator before sign-offs
        signoff_patterns = [
            "kuch aur", "anything else", "aur batao", "let me know",
            "help chahiye", "need anything", "bolo kya", "batao kya",
        ]
        for pattern in signoff_patterns:
            if pattern in text.lower():
                idx = text.lower().rfind(pattern)
                if idx > 0 and text[idx-1] != '\n':
                    text = text[:idx] + '\n\n' + text[idx:]
                break

    return text.strip()


def format_pricing_message(text: str) -> str:
    """Format pricing/financial messages with clean structure."""
    # Already well-formatted from pricing engine
    return text


def format_alert_message(text: str) -> str:
    """Format proactive alert messages."""
    if not text:
        return text
    # Alerts should be concise and action-oriented
    # Already formatted in their respective generators
    return text.strip()
