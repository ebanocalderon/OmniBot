"""
Async Chatwoot REST API client.

Wraps the most important endpoints needed by the bridge:
  - Contact  : find by Telegram ID or create
  - Conversation : find open or create new
  - Message  : post an incoming message on behalf of the contact
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

_BASE = settings.chatwoot_base_url.rstrip("/")
_ACCOUNT = settings.chatwoot_account_id
_HEADERS = {
    "api_access_token": settings.chatwoot_api_token,
    "Content-Type": "application/json",
}


def _api(path: str) -> str:
    return f"{_BASE}/api/v1/accounts/{_ACCOUNT}{path}"


# ── Client ────────────────────────────────────────────────────────────────────


class ChatwootClient:
    """
    Thin async wrapper around the Chatwoot REST API.
    Uses a single shared httpx.AsyncClient for connection pooling.
    Call .aclose() when the application shuts down.
    """

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            headers=_HEADERS,
            timeout=httpx.Timeout(10.0),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # ── Messages ──────────────────────────────────────────────────

    async def send_outgoing_message(
        self,
        conversation_id: int,
        content: str,
        content_type: str = "text",
        private: bool = False,
    ) -> Dict[str, Any]:
        """
        Post an outgoing (agent) message or private note to a Chatwoot conversation.
        message_type=outgoing means it appears on the right / agent side.
        """
        url = _api(f"/conversations/{conversation_id}/messages")
        body = {
            "content": content,
            "message_type": "outgoing",
            "content_type": content_type,
            "private": private,
        }
        resp = await self._http.post(url, json=body)
        resp.raise_for_status()
        msg = resp.json()
        logger.debug(
            "Sent %s message id=%s to conversation_id=%s",
            "private" if private else "outgoing",
            msg.get("id"),
            conversation_id,
        )
        return msg

    async def update_conversation_status(
        self,
        conversation_id: int,
        status: str,
    ) -> Dict[str, Any]:
        """
        Update conversation status (e.g., 'open', 'resolved', 'pending', 'snoozed', 'bot').
        Changing from 'bot' or 'pending' to 'open' hands the conversation to a human.
        Changing to 'resolved' closes the chat.
        """
        url = _api(f"/conversations/{conversation_id}/toggle_status")
        body = {
            "status": status
        }
        resp = await self._http.post(url, json=body)
        resp.raise_for_status()
        conversation = resp.json()
        logger.info(
            "Updated conversation_id=%s to status=%s",
            conversation_id,
            status,
        )
        return conversation

    async def update_contact(
        self,
        contact_id: int,
        name: Optional[str] = None,
        email: Optional[str] = None,
        phone_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update contact details (name, email, and/or phone) in Chatwoot CRM.
        """
        url = _api(f"/contacts/{contact_id}")
        body = {}
        if name:
            body["name"] = name
        if email:
            body["email"] = email
        if phone_number:
            # Clean non-digits (except optional leading +)
            cleaned = "".join(c for c in phone_number if c.isdigit() or c == "+")
            if not cleaned.startswith("+"):
                if len(cleaned) == 10:
                    cleaned = f"+1{cleaned}"
                elif len(cleaned) == 11 and cleaned.startswith("1"):
                    cleaned = f"+{cleaned}"
                else:
                    cleaned = f"+1{cleaned}"
            body["phone_number"] = cleaned
            
        if not body:
            logger.warning("update_contact called with empty body for contact_id=%s", contact_id)
            return {}
            
        headers = _HEADERS.copy()
        if settings.chatwoot_user_token:
            headers["api_access_token"] = settings.chatwoot_user_token
            
        resp = await self._http.put(url, json=body, headers=headers)
        
        # If the email already exists for another contact, Chatwoot may return 422
        resp.raise_for_status()
        
        contact = resp.json()
        logger.info(
            "Updated Chatwoot contact id=%s: %s",
            contact_id,
            body,
        )
        return contact


# ── Singleton ─────────────────────────────────────────────────────────────────

chatwoot_client = ChatwootClient()
