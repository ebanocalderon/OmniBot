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
import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.config import settings

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
      - message_type == "incoming"   (sent by a customer)
      - private      == False        (not an internal note)

    On match, the AI generates a reply and posts it back as an agent.
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

    try:
        payload: Dict[str, Any] = json.loads(raw_body)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON body",
        )

    event = payload.get("event", "")
    message_type = payload.get("message_type", "")
    is_private = payload.get("private", True)

    logger.debug("Received Chatwoot event: %s (type=%s)", event, message_type)

    # ── Filter: only incoming customer messages ────────────────────
    if event != "message_created":
        return {"status": "ignored", "reason": "event not message_created"}

    if message_type != "incoming":
        return {"status": "ignored", "reason": "not an incoming customer message"}

    if is_private:
        return {"status": "ignored", "reason": "private note"}

    content: str = payload.get("content", "").strip()
    if not content:
        return {"status": "ignored", "reason": "empty content"}

    conversation = payload.get("conversation", {})
    conversation_id: int = conversation.get("id", 0)
    if not conversation_id:
        return {"status": "ignored", "reason": "missing conversation id"}

    # ── Fetch AI Response ──────────────────────────────────────────
    from app.ai.client import get_ai_response
    from app.chatwoot.client import chatwoot_client

    logger.info("Processing message for conversation_id=%s", conversation_id)
    
    # Process asynchronously to not block the webhook response,
    # but for simplicity and Chatwoot's timeout, we await it. 
    # If the LLM is slow, we might need a background task. 
    # For now, we await it directly.
    ai_reply = await get_ai_response(conversation_id, content)

    if not ai_reply:
        logger.warning("AI did not return a response for conversation_id=%s", conversation_id)
        return {"status": "ignored", "reason": "AI response was empty or disabled"}

    # ── Reply back to Chatwoot ─────────────────────────────────────
    try:
        await chatwoot_client.send_outgoing_message(
            conversation_id=conversation_id,
            content=ai_reply
        )
        logger.info("Successfully replied to conversation_id=%s", conversation_id)
        return {"status": "ok"}
    except Exception as exc:
        logger.exception("Failed to send AI reply to Chatwoot: %s", exc)
        return {"status": "error", "reason": str(exc)}
