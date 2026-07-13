"""
Email utility for sending lead notifications via Google Gmail API.
"""
import base64
import logging
import asyncio
import os
from email.message import EmailMessage
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from app.config import settings

logger = logging.getLogger(__name__)

def _get_gmail_service():
    """
    Initialize Gmail API service using token.json.
    """
    if os.path.exists("token.json"):
        # We request both calendar and gmail.send scopes, but we can reuse the same token
        creds = Credentials.from_authorized_user_file("token.json", [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/gmail.send"
        ])
        if creds and creds.expired and creds.refresh_token:
            logger.info("Google credentials expired. Refreshing token for Gmail...")
            creds.refresh(Request())
            # Save refreshed token
            with open("token.json", "w") as token:
                token.write(creds.to_json())
        return build('gmail', 'v1', credentials=creds)
    else:
        raise Exception("Google token.json not found on the server.")

def send_booking_notification_sync(name: str, client_email: str, start_time_iso: str, history_formatted: str) -> None:
    """
    Send the email using Gmail API. Runs in a thread via asyncio.to_thread.
    """
    if not settings.notification_email:
        logger.warning("NOTIFICATION_EMAIL is not set. Skipping lead notification email.")
        return

    try:
        service = _get_gmail_service()
        
        # Build MIME message
        message = EmailMessage()
        message.set_content(f"""New Consultation Booking Confirmed!

Lead Details:
- Name: {name}
- Email: {client_email}
- Proposed Start Time (UTC): {start_time_iso}

--- Chatwoot Conversation History ---
{history_formatted}
""")
        message['To'] = settings.notification_email
        message['Subject'] = f"New Consultation Booked: {name}"
        
        # Encoded raw message for Gmail API
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        body = {'raw': raw_message}
        
        send_query = service.users().messages().send(userId="me", body=body)
        send_query.execute()
        
        logger.info("Lead notification email sent successfully via Gmail API to %s", settings.notification_email)
    except Exception as e:
        logger.exception("Failed to send booking notification email via Gmail API: %s", e)

async def send_booking_notification(name: str, client_email: str, start_time_iso: str, history: list) -> None:
    """
    Formats the conversation transcript and triggers Gmail API sending in a background thread.
    """
    history_formatted = ""
    for msg in history:
        role = msg.get("role", "unknown").upper()
        if role == "SYSTEM":
            continue
        content = msg.get("content", "")
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
