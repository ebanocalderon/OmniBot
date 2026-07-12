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
    ) -> Dict[str, Any]:
        """
        Post an outgoing (agent) message to a Chatwoot conversation.
        message_type=outgoing means it appears on the right / agent side.
        Useful for AI responses so agents see both sides of the conversation.
        """
        url = _api(f"/conversations/{conversation_id}/messages")
        body = {
            "content": content,
            "message_type": "outgoing",
            "content_type": content_type,
            "private": False,
        }
        resp = await self._http.post(url, json=body)
        resp.raise_for_status()
        msg = resp.json()
        logger.debug(
            "Sent outgoing message id=%s to conversation_id=%s",
            msg.get("id"),
            conversation_id,
        )
        return msg


# ── Singleton ─────────────────────────────────────────────────────────────────

chatwoot_client = ChatwootClient()
