"""
Async LiteLLM AI client.

Provides a simple conversational AI that auto-responds to users
via any LLM supported by LiteLLM (Ollama, OpenAI, Anthropic, etc.).

Maintains per-chat conversation history in memory.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import litellm
from litellm import acompletion

from app.config import settings

logger = logging.getLogger(__name__)

# Drop litellm internal logging if needed
litellm.suppress_debug_info = True

# ── In-memory conversation history ────────────────────────────────────────────
# {conversation_id: [{"role": "system"|"user"|"assistant", "content": "..."}, ...]}
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
    Send a user message to the configured LLM and return the AI response.
    """
    history = _get_history(chat_id)

    # Prepend system prompt on first message
    if not history:
        history.append({"role": "system", "content": settings.ai_system_prompt})

    history.append({"role": "user", "content": user_message})

    try:
        response = await acompletion(
            model=settings.llm_model,
            messages=history,
            api_base=settings.llm_api_base if settings.llm_api_base else None,
            api_key=settings.llm_api_key if settings.llm_api_key else None,
            stream=False,
        )
        
        ai_content: str = response.choices[0].message.content
        
        if not ai_content:
            logger.warning("LLM returned empty response for chat_id=%s", chat_id)
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

    except Exception as exc:
        logger.exception("Unexpected error calling LLM for chat_id=%s: %s", chat_id, exc)
        history.pop()
        return None


def clear_history(chat_id: int) -> None:
    """Reset conversation history for a given chat."""
    _history.pop(chat_id, None)
    logger.debug("Cleared AI history for chat_id=%s", chat_id)
