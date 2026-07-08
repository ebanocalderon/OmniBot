"""
FastAPI router for incoming Chatwoot webhook events.

Mounted at: /chatwoot
Handles:    POST /webhook

Flow:
    Chatwoot fires a webhook when an agent sends an outgoing (non-private)
    message.  We look up which Telegram chat corresponds to that conversation
    and forward the message via the Telegram bot.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.config import settings
from app.database import get_chat_id_by_conversation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chatwoot", tags=["chatwoot"])

# ── Security ──────────────────────────────────────────────────────────────────


def _verify_signature(raw_body: bytes, signature_header: str) -> bool:
    """
    Validate the HMAC-SHA256 signature sent by Chatwoot when WEBHOOK_SECRET
    is configured.  Chatwoot sets the header: X-Chatwoot-Signature
    """
    expected = hmac.new(
        settings.webhook_secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def chatwoot_webhook(
    request: Request,
    x_chatwoot_signature: str = Header(default=""),
) -> Dict[str, str]:
    """
    Receive webhook events from Chatwoot.

    Only processes `message_created` events where:
      - message_type == "outgoing"   (sent by an agent)
      - private      == False        (not an internal note)

    On match, the agent reply is forwarded to the correct Telegram chat.
    """
    raw_body = await request.body()

    # ── Optional signature verification ───────────────────────────
    if settings.webhook_secret:
        if not x_chatwoot_signature:
            logger.warning("Webhook received without signature header — rejected")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-Chatwoot-Signature header",
            )
        if not _verify_signature(raw_body, x_chatwoot_signature):
            logger.warning("Webhook signature mismatch — rejected")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid webhook signature",
            )

    # ── Parse payload ─────────────────────────────────────────────
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON body",
        )

    event = payload.get("event", "")
    message_type = payload.get("message_type", "")
    is_private = payload.get("private", True)

    logger.debug("Received Chatwoot event: %s (type=%s)", event, message_type)

    # ── Filter: only agent replies ────────────────────────────────
    if event != "message_created":
        return {"status": "ignored", "reason": "event not message_created"}

    if message_type != "outgoing":
        return {"status": "ignored", "reason": "not an outgoing message"}

    if is_private:
        return {"status": "ignored", "reason": "private note"}

    content: str = payload.get("content", "").strip()
    if not content:
        return {"status": "ignored", "reason": "empty content"}

    conversation = payload.get("conversation", {})
    conversation_id: int = conversation.get("id", 0)
    if not conversation_id:
        return {"status": "ignored", "reason": "missing conversation id"}

    # ── Look up the Telegram chat ─────────────────────────────────
    telegram_chat_id = await get_chat_id_by_conversation(conversation_id)
    if telegram_chat_id is None:
        logger.warning(
            "No Telegram session for conversation_id=%s — cannot forward",
            conversation_id,
        )
        return {"status": "ignored", "reason": "no telegram session found"}

    # ── Forward to Telegram ───────────────────────────────────────
    # Import here to avoid circular imports (bot module imports this router indirectly)
    from app.telegram.bot import send_telegram_message  # noqa: PLC0415

    sender_name = payload.get("sender", {}).get("name", "Agent")
    formatted = f"💬 *{sender_name}*:\n{content}"

    await send_telegram_message(
        chat_id=telegram_chat_id,
        text=formatted,
    )
    logger.info(
        "Forwarded agent reply from conversation_id=%s to Telegram chat_id=%s",
        conversation_id,
        telegram_chat_id,
    )
    return {"status": "ok"}
