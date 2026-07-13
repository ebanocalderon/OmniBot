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


from app.ai.cal_client import fetch_slots, create_booking
from app.chatwoot.client import chatwoot_client
import json
import re

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_available_slots",
            "description": "Fetch available booking slots for a specific date on Cal.com.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "The date to check slots for, in YYYY-MM-DD format (e.g. '2026-07-15')."
                    }
                },
                "required": ["date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book an appointment on Cal.com.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The full name of the client."
                    },
                    "email": {
                        "type": "string",
                        "description": "The email address of the client."
                    },
                    "date_time_iso": {
                        "type": "string",
                        "description": "The exact start time of the booking in ISO 8601 format (UTC), e.g. '2026-07-15T09:00:00Z'."
                    }
                },
                "required": ["name", "email", "date_time_iso"]
            }
        }
    }
]

async def _execute_tool_call(tool_call, contact_id: Optional[int] = None) -> str:
    """Execute a single tool call and return its result as a string."""
    func_name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments)
        logger.info("Executing tool %s with args %s", func_name, args)
        
        if func_name == "get_available_slots":
            return await fetch_slots(args.get("date"))
        elif func_name == "book_appointment":
            name = args.get("name")
            email = args.get("email")
            
            # If contact_id is provided, update Chatwoot CRM contact
            if contact_id:
                try:
                    logger.info("Updating Chatwoot CRM contact_id=%s with name=%s, email=%s", contact_id, name, email)
                    await chatwoot_client.update_contact(contact_id, name, email)
                except Exception as e:
                    logger.error("Failed to update Chatwoot CRM contact: %s", e)
            
            return await create_booking(name, email, args.get("date_time_iso"))
        else:
            return f"Error: Unknown tool {func_name}"
    except Exception as e:
        logger.exception("Error executing tool %s", func_name)
        return f"Error executing {func_name}: {str(e)}"


async def get_ai_response(chat_id: int, user_message: str, contact_id: Optional[int] = None) -> Optional[str]:
    """
    Send a user message to the configured LLM and return the AI response.
    Supports tool calling for Cal.com integration.
    """
    history = _get_history(chat_id)

    # Prepend system prompt on first message
    if not history:
        from datetime import datetime, timezone, timedelta
        # Default to Eastern Time (UTC-4) for US clients
        us_eastern = timezone(timedelta(hours=-4))
        today_str = datetime.now(us_eastern).strftime("%Y-%m-%d")
        system_content = f"{settings.ai_system_prompt}\n\nToday's date is {today_str}."
        history.append({"role": "system", "content": system_content})

    history.append({"role": "user", "content": user_message})

    try:
        # First LLM call
        try:
            response = await acompletion(
                model=settings.llm_model,
                messages=history,
                api_base=settings.llm_api_base if settings.llm_api_base else None,
                api_key=settings.llm_api_key if settings.llm_api_key else None,
                tools=TOOLS_SCHEMA,
                stream=False,
            )
            message = response.choices[0].message
        except litellm.exceptions.BadRequestError as e:
            logger.warning("Caught BadRequestError from LLM, attempting to extract failed_generation: %s", str(e))
            err_str = str(e)
            failed_gen = ""
            if "failed_generation" in err_str:
                try:
                    json_start = err_str.find("{")
                    if json_start != -1:
                        err_json = json.loads(err_str[json_start:])
                        failed_gen = err_json.get("error", {}).get("failed_generation", "")
                except Exception:
                    pass
            if not failed_gen:
                raise e
            
            # Create a mock message with the failed generation text
            class MockMessage:
                def __init__(self, content):
                    self.content = content
                    self.tool_calls = None
                def model_dump(self, **kwargs):
                    return {"role": "assistant", "content": self.content}
            message = MockMessage(failed_gen)
        
        # Check if model wants to call tools natively
        if hasattr(message, "tool_calls") and message.tool_calls:
            logger.info("LLM requested native tool calls for chat_id=%s", chat_id)
            # Append the assistant's tool call request to history
            history.append(message.model_dump(exclude_none=True))
            
            # Execute all tools
            for tool_call in message.tool_calls:
                result = await _execute_tool_call(tool_call, contact_id=contact_id)
                # Append tool result
                history.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": result
                })
                
            # Second LLM call to get final response after tool execution
            response = await acompletion(
                model=settings.llm_model,
                messages=history,
                api_base=settings.llm_api_base if settings.llm_api_base else None,
                api_key=settings.llm_api_key if settings.llm_api_key else None,
                tools=TOOLS_SCHEMA,
                stream=False,
            )
            message = response.choices[0].message

        ai_content: str = message.content or ""
        
        # Check if the LLM returned a text-based function call instead of native tool_calls (fallback)
        text_tool_match = re.search(r'<function=(\w+).*?(\{.*?\})', ai_content, re.DOTALL)
        if text_tool_match:
            func_name = text_tool_match.group(1)
            args_str = text_tool_match.group(2).strip()
            logger.info("Found text-based tool call fallback: %s with args %s", func_name, args_str)
            
            try:
                args = json.loads(args_str)
                if func_name == "get_available_slots":
                    tool_result = await fetch_slots(args.get("date"))
                elif func_name == "book_appointment":
                    name = args.get("name")
                    email = args.get("email")
                    
                    # Update Chatwoot CRM contact
                    if contact_id:
                        try:
                            logger.info("Updating Chatwoot CRM contact_id=%s with name=%s, email=%s (fallback)", contact_id, name, email)
                            await chatwoot_client.update_contact(contact_id, name, email)
                        except Exception as e:
                            logger.error("Failed to update Chatwoot CRM contact (fallback): %s", e)
                            
                    tool_result = await create_booking(name, email, args.get("date_time_iso"))
                else:
                    tool_result = f"Error: Unknown tool {func_name}"
            except Exception as e:
                tool_result = f"Error parsing args or executing fallback: {str(e)}"
                
            # Append intermediate response and tool result to history
            history.append({"role": "assistant", "content": ai_content})
            history.append({
                "role": "user",
                "content": f"Tool output [{func_name}]: {tool_result}"
            })
            
            # Second LLM call for text fallback
            response = await acompletion(
                model=settings.llm_model,
                messages=history,
                api_base=settings.llm_api_base if settings.llm_api_base else None,
                api_key=settings.llm_api_key if settings.llm_api_key else None,
                tools=TOOLS_SCHEMA,
                stream=False,
            )
            message = response.choices[0].message
            ai_content = message.content or ""

        if ai_content:
            # Strip <think>...</think> reasoning blocks if present
            ai_content = re.sub(r'<think>.*?</think>', '', ai_content, flags=re.DOTALL).strip()
        
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
