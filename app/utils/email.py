"""
Email utility for sending lead notifications via SMTP.
"""
import smtplib
import logging
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config import settings

logger = logging.getLogger(__name__)

def send_booking_notification_sync(name: str, client_email: str, start_time_iso: str, history_formatted: str) -> None:
    """
    Synchronous SMTP email sender. Runs in a separate thread via asyncio.to_thread.
    """
    if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password or not settings.notification_email:
        logger.warning("SMTP configuration is incomplete. Skipping lead notification email.")
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = settings.smtp_from_email or settings.smtp_username
        msg['To'] = settings.notification_email
        msg['Subject'] = f"New Consultation Booked: {name}"

        body = f"""New Consultation Booking Confirmed!

Lead Details:
- Name: {name}
- Email: {client_email}
- Proposed Start Time (UTC): {start_time_iso}

--- Chatwoot Conversation History ---
{history_formatted}
"""
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        # Support SSL on port 465, TLS/STARTTLS on others (like 587)
        if settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()

        server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)
        server.quit()
        logger.info("Lead notification email sent successfully to %s", settings.notification_email)
    except Exception as e:
        logger.exception("Failed to send booking notification email via SMTP: %s", e)

async def send_booking_notification(name: str, client_email: str, start_time_iso: str, history: list) -> None:
    """
    Formats the conversation transcript and triggers SMTP email sending in a background thread.
    """
    history_formatted = ""
    for msg in history:
        role = msg.get("role", "unknown").upper()
        if role == "SYSTEM":
            continue
        content = msg.get("content", "")
        # Also clean up reasoning content if present
        import re
        content_clean = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        if content_clean:
            history_formatted += f"[{role}]: {content_clean}\n\n"

    # Fire-and-forget in a background thread to prevent event loop blocking
    await asyncio.to_thread(
        send_booking_notification_sync,
        name,
        client_email,
        start_time_iso,
        history_formatted
    )
