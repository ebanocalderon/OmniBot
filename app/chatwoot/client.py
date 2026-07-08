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
_INBOX = settings.chatwoot_inbox_id
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

    # ── Contacts ──────────────────────────────────────────────────

    async def get_or_create_contact(
        self,
        telegram_chat_id: int,
        first_name: str,
        last_name: Optional[str] = None,
        username: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Search Chatwoot contacts by the custom attribute `telegram_chat_id`.
        If not found, create a new contact and attach the attribute.

        Returns the full contact dict from the Chatwoot API.
        """
        # 1. Search by name / identifier first
        display_name = first_name
        if last_name:
            display_name = f"{first_name} {last_name}"

        identifier = f"telegram_{telegram_chat_id}"

        # Try searching by identifier (unique per contact)
        search_url = _api("/contacts/search")
        resp = await self._http.get(
            search_url,
            params={"q": identifier, "include_contacts": True},
        )
        if resp.is_success:
            payload = resp.json()
            contacts = payload.get("payload", [])
            for c in contacts:
                if c.get("identifier") == identifier:
                    logger.debug("Found existing contact id=%s", c["id"])
                    return c

        # 2. Create new contact
        create_url = _api("/contacts")
        body: Dict[str, Any] = {
            "name": display_name,
            "identifier": identifier,
            "additional_attributes": {
                "telegram_chat_id": telegram_chat_id,
                "telegram_username": username or "",
            },
        }
        resp = await self._http.post(create_url, json=body)
        resp.raise_for_status()
        contact = resp.json()
        logger.info(
            "Created Chatwoot contact id=%s for Telegram chat_id=%s",
            contact["id"],
            telegram_chat_id,
        )
        return contact

    # ── Conversations ─────────────────────────────────────────────

    async def get_or_create_conversation(
        self,
        contact_id: int,
        telegram_chat_id: int,
    ) -> Dict[str, Any]:
        """
        Find an open conversation in the configured inbox for the given contact,
        or create a new one.

        Returns the full conversation dict.
        """
        # Search open conversations for this contact
        list_url = _api(f"/contacts/{contact_id}/conversations")
        resp = await self._http.get(list_url)
        if resp.is_success:
            payload = resp.json()
            conversations = payload.get("payload", [])
            for conv in conversations:
                if (
                    conv.get("inbox_id") == _INBOX
                    and conv.get("status") == "open"
                ):
                    logger.debug("Reusing conversation id=%s", conv["id"])
                    return conv

        # Create new conversation
        create_url = _api("/conversations")
        body = {
            "inbox_id": _INBOX,
            "contact_id": contact_id,
            "source_id": f"telegram_{telegram_chat_id}",
            "status": "open",
            "additional_attributes": {
                "telegram_chat_id": telegram_chat_id,
            },
        }
        resp = await self._http.post(create_url, json=body)
        resp.raise_for_status()
        conversation = resp.json()
        logger.info(
            "Created conversation id=%s for contact_id=%s",
            conversation["id"],
            contact_id,
        )
        return conversation

    # ── Messages ──────────────────────────────────────────────────

    async def send_incoming_message(
        self,
        conversation_id: int,
        content: str,
        content_type: str = "text",
    ) -> Dict[str, Any]:
        """
        Post an incoming (customer) message to a Chatwoot conversation.
        message_type=incoming means it appears on the left / customer side.
        """
        url = _api(f"/conversations/{conversation_id}/messages")
        body = {
            "content": content,
            "message_type": "incoming",
            "content_type": content_type,
            "private": False,
        }
        resp = await self._http.post(url, json=body)
        resp.raise_for_status()
        msg = resp.json()
        logger.debug(
            "Sent incoming message id=%s to conversation_id=%s",
            msg.get("id"),
            conversation_id,
        )
        return msg


# ── Singleton ─────────────────────────────────────────────────────────────────

chatwoot_client = ChatwootClient()
