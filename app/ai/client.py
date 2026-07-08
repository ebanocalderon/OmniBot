"""
Async Ollama AI client.

Provides a simple conversational AI that auto-responds to users
via a locally-running Ollama instance.

Maintains per-chat conversation history in memory.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ── In-memory conversation history ────────────────────────────────────────────
# {chat_id: [{"role": "system"|"user"|"assistant", "content": "..."}, ...]}
_history: Dict[int, List[Dict[str, str]]] = {}


def _get_history(chat_id: int) -> List[Dict[str, str]]:
    if chat_id not in _history:
        _history[chat_id] = []
    return _history[chat_id]


def _trim_history(chat_id: int) -> None:
    msgs = _history.get(chat_id, [])
    max_msgs = settings.ai_max_history * 2 + 1  # +1 for system prompt
    while len(msgs) > max_msgs:
        idx = 1 if msgs[0].get("role") == "system" else 0
        msgs.pop(idx)


# ── Public API ────────────────────────────────────────────────────────────────


async def get_ai_response(chat_id: int, user_message: str) -> Optional[str]:
    """
    Send a user message to Ollama and return the AI response.

    Returns None if AI is disabled or an error occurs.
    """
    if not settings.ai_enabled:
        return None

    history = _get_history(chat_id)

    # Prepend system prompt on first message
    if not history:
        history.append({"role": "system", "content": settings.ai_system_prompt})

    history.append({"role": "user", "content": user_message})

    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    body = {
        "model": settings.ollama_model,
        "messages": history,
        "stream": False,
        # Disable thinking/reasoning for faster responses on Qwen models
        "think": False,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
            ai_content: str = data.get("message", {}).get("content", "")

            if not ai_content:
                logger.warning("Ollama returned empty response for chat_id=%s", chat_id)
                history.pop()  # remove the user message we added
                return None

            history.append({"role": "assistant", "content": ai_content})
            _trim_history(chat_id)

            logger.info(
                "AI response generated for chat_id=%s (%d chars)",
                chat_id,
                len(ai_content),
            )
            return ai_content

    except httpx.ConnectError:
        logger.error(
            "Cannot connect to Ollama at %s — is it running?", settings.ollama_base_url
        )
        history.pop()
        return None
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Ollama HTTP error %s for chat_id=%s: %s",
            exc.response.status_code,
            chat_id,
            exc.response.text,
        )
        history.pop()
        return None
    except Exception as exc:
        logger.exception("Unexpected error calling Ollama for chat_id=%s: %s", chat_id, exc)
        history.pop()
        return None


def clear_history(chat_id: int) -> None:
    """Reset conversation history for a given chat."""
    _history.pop(chat_id, None)
    logger.debug("Cleared AI history for chat_id=%s", chat_id)
