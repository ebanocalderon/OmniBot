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
import asyncio
import re

from app.config import settings

logger = logging.getLogger(__name__)

# Drop litellm internal logging if needed
litellm.suppress_debug_info = True

async def acompletion_with_retry(*args, **kwargs):
    max_attempts = 4
    for attempt in range(max_attempts):
        try:
            return await acompletion(*args, **kwargs)
        except litellm.exceptions.RateLimitError as e:
            if attempt == max_attempts - 1:
                raise e
            wait_time = 10.0
            try:
                err_msg = str(e)
                match = re.search(r'try again in (\d+\.?\d*)s', err_msg)
                if match:
                    wait_time = float(match.group(1)) + 0.5
            except Exception:
                pass
            logger.warning("Rate limit hit. Waiting for %.2f seconds before retry %d...", wait_time, attempt + 1)
            await asyncio.sleep(wait_time)

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


import os
USE_GOOGLE_CALENDAR = os.getenv("USE_GOOGLE_CALENDAR", "false").lower() in ("true", "1", "yes")

if USE_GOOGLE_CALENDAR:
    from app.ai.gcal_client import fetch_slots, create_booking, check_existing_bookings, cancel_booking
    logger.info("Using Google Calendar integration")
else:
    from app.ai.cal_client import fetch_slots, create_booking, check_existing_bookings, cancel_booking
    logger.info("Using Cal.com integration")
from app.chatwoot.client import chatwoot_client
import json
import re

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_available_slots",
            "description": "Fetch available booking slots for a specific date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "The date to check slots for, in YYYY-MM-DD format (e.g. '2026-07-15')."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book an appointment.",
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
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_existing_bookings",
            "description": "Check if a client already has active upcoming bookings using their email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "The client email to check."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_booking",
            "description": "Cancel an existing booking using its UID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_uid": {
                        "type": "string",
                        "description": "The UID of the booking to cancel."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "handoff_to_human",
            "description": "Hand off the conversation to a human agent.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_conversation",
            "description": "Mark the conversation as resolved (closed).",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_contact_name",
            "description": "Save the client's full name to the CRM. Call this immediately after the client provides their name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The full name of the client."
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_contact_phone",
            "description": "Save the client's phone number to the CRM. Call this immediately after the client provides their phone number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "The phone number of the client."
                    }
                },
                "required": ["phone"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_contact_email",
            "description": "Save the client's email address to the CRM. Call this immediately after the client provides their email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "The email address of the client."
                    }
                },
                "required": ["email"]
            }
        }
    }
]

async def _execute_tool_call(tool_call, contact_id: Optional[int] = None, chat_id: Optional[int] = None) -> str:
    """Execute a single tool call and return its result as a string."""
    func_name = tool_call.function.name
    try:
        args = json.loads(tool_call.function.arguments)
        logger.info("Executing tool %s with args %s", func_name, args)
        
        if func_name == "get_available_slots":
            date = args.get("date")
            if not date:
                return "Error: Please specify the 'date' parameter in YYYY-MM-DD format (e.g., '2026-07-15')."
            return await fetch_slots(date)
        elif func_name == "check_existing_bookings":
            email = args.get("email")
            if not email:
                return "Error: Please specify the 'email' parameter."
            if contact_id:
                try:
                    logger.info("Automatically saving CRM email inside check_existing_bookings contact_id=%s: email=%s", contact_id, email)
                    await chatwoot_client.update_contact(contact_id, email=email)
                except Exception as e:
                    logger.error("Failed to automatically save email inside check_existing_bookings: %s", e)
            return await check_existing_bookings(email)
        elif func_name == "cancel_booking":
            booking_uid = args.get("booking_uid")
            if not booking_uid:
                return "Error: Please specify the 'booking_uid' parameter."
            return await cancel_booking(booking_uid)
        elif func_name == "book_appointment":
            name = args.get("name")
            email = args.get("email")
            date_time_iso = args.get("date_time_iso")
            
            if not name or not email or not date_time_iso:
                return "Error: Missing required parameters ('name', 'email', 'date_time_iso') for booking."
            
            # If contact_id is provided, update Chatwoot CRM contact
            if contact_id:
                try:
                    logger.info("Updating Chatwoot CRM contact_id=%s with name=%s, email=%s", contact_id, name, email)
                    await chatwoot_client.update_contact(contact_id, name=name, email=email)
                except Exception as e:
                    logger.error("Failed to update Chatwoot CRM contact: %s", e)
            
            booking_result = await create_booking(name, email, date_time_iso)
            
            # Send booking notification email in the background
            if chat_id and "Successfully booked" in booking_result:
                try:
                    from app.utils.email import send_booking_notification
                    history = _get_history(chat_id)
                    asyncio.create_task(send_booking_notification(name, email, date_time_iso, list(history)))
                except Exception as ex:
                    logger.error("Failed to trigger booking notification task: %s", ex)
                    
            return booking_result
        elif func_name == "save_contact_name":
            name = args.get("name")
            if contact_id and name:
                try:
                    logger.info("Executing tool save_contact_name with args %s", args)
                    await chatwoot_client.update_contact(contact_id, name=name)
                    return "Success: Contact name successfully updated in the CRM."
                except Exception as e:
                    logger.error("Failed to save contact name to CRM: %s", e)
                    return f"Error saving contact name: {e}"
            return "Error: contact_id or name not provided."
        elif func_name == "save_contact_phone":
            phone = args.get("phone")
            if contact_id and phone:
                try:
                    logger.info("Executing tool save_contact_phone with args %s", args)
                    await chatwoot_client.update_contact(contact_id, phone_number=phone)
                    return "Success: Contact phone successfully updated in the CRM."
                except Exception as e:
                    logger.error("Failed to save contact phone to CRM: %s", e)
                    return f"Error saving contact phone: {e}"
            return "Error: contact_id or phone not provided."
        elif func_name == "save_contact_email":
            email = args.get("email")
            if contact_id and email:
                try:
                    logger.info("Executing tool save_contact_email with args %s", args)
                    await chatwoot_client.update_contact(contact_id, email=email)
                    return "Success: Contact email successfully updated in the CRM."
                except Exception as e:
                    logger.error("Failed to save contact email to CRM: %s", e)
                    return f"Error saving contact email: {e}"
            return "Error: contact_id or email not provided."
        elif func_name == "handoff_to_human":
            if chat_id:
                try:
                    await chatwoot_client.update_conversation_status(chat_id, "open")
                    await chatwoot_client.send_outgoing_message(
                        conversation_id=chat_id,
                        content="⚠️ The AI has handed off this conversation to a human agent.",
                        private=True
                    )
                    return "Success: Conversation handed off to human agent. You MUST stop generating responses now."
                except Exception as e:
                    logger.error("Failed to handoff conversation: %s", e)
                    return f"Error handing off: {e}"
            return "Error: chat_id not provided for handoff."
        elif func_name == "resolve_conversation":
            if chat_id:
                try:
                    await chatwoot_client.update_conversation_status(chat_id, "resolved")
                    return "Success: Conversation marked as resolved. You MUST stop generating responses now."
                except Exception as e:
                    logger.error("Failed to resolve conversation: %s", e)
                    return f"Error resolving: {e}"
            return "Error: chat_id not provided for resolution."
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
    
    # If the history contains a handoff tool call, it means the conversation was previously handed off.
    # If we are here processing a new message, it means the conversation was set back to pending.
    # In this case, we clear the history so the bot resumes fresh.
    has_handoff = False
    for msg in history:
        if msg.get("role") == "tool" and msg.get("name") == "handoff_to_human":
            has_handoff = True
            break
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg.get("tool_calls"):
                # Handle dict or object
                tc_name = tc.get("function", {}).get("name") if isinstance(tc, dict) else getattr(getattr(tc, "function", None), "name", None)
                if tc_name == "handoff_to_human":
                    has_handoff = True
                    break
            if has_handoff:
                break
                
    if has_handoff:
        logger.info("Previous handoff detected in history for chat_id=%s. Clearing history to resume fresh.", chat_id)
        clear_history(chat_id)
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
            response = await acompletion_with_retry(
                model=settings.llm_model,
                messages=history,
                api_base=settings.llm_api_base if settings.llm_api_base else None,
                api_key=settings.llm_api_key if settings.llm_api_key else None,
                tools=TOOLS_SCHEMA,
                stream=False,
                num_retries=3,
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
        max_tool_iterations = 5
        iterations = 0
        while hasattr(message, "tool_calls") and message.tool_calls and iterations < max_tool_iterations:
            logger.info("LLM requested native tool calls for chat_id=%s (iteration %d)", chat_id, iterations+1)
            # Append the assistant's tool call request to history
            history.append(message.model_dump(exclude_none=True))
            
            # Execute all tools
            for tool_call in message.tool_calls:
                result = await _execute_tool_call(tool_call, contact_id=contact_id, chat_id=chat_id)
                # Append tool result
                history.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.function.name,
                    "content": result
                })
                
            # Next LLM call to get final response or another tool call
            response = await acompletion_with_retry(
                model=settings.llm_model,
                messages=history,
                api_base=settings.llm_api_base if settings.llm_api_base else None,
                api_key=settings.llm_api_key if settings.llm_api_key else None,
                tools=TOOLS_SCHEMA,
                stream=False,
                num_retries=3,
            )
            message = response.choices[0].message
            iterations += 1

        if hasattr(message, "tool_calls") and message.tool_calls:
            logger.warning("Max tool iterations reached for chat_id=%s", chat_id)
            try:
                await chatwoot_client.update_conversation_status(chat_id, "open")
                await chatwoot_client.send_outgoing_message(
                    conversation_id=chat_id,
                    content="⚠️ The AI reached the maximum number of tool iterations (possible loop) and has deactivated itself. Human intervention required.",
                    private=True
                )
            except Exception as handoff_e:
                logger.error("Failed to handoff after max iterations: %s", handoff_e)
            return None

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
                elif func_name == "check_existing_bookings":
                    tool_result = await check_existing_bookings(args.get("email"))
                elif func_name == "cancel_booking":
                    tool_result = await cancel_booking(args.get("booking_uid"))
                elif func_name == "save_contact_info":
                    name = args.get("name")
                    phone = args.get("phone")
                    email = args.get("email")
                    if not name and not phone and not email:
                        tool_result = "Error: At least one contact parameter ('name', 'phone', 'email') must be provided."
                    elif contact_id:
                        try:
                            logger.info("Saving contact info for CRM contact_id=%s: name=%s, phone=%s, email=%s (fallback)", contact_id, name, phone, email)
                            await chatwoot_client.update_contact(contact_id, name=name, email=email, phone_number=phone)
                            tool_result = "Success: Contact information successfully updated in the CRM."
                        except Exception as e:
                            logger.error("Failed to save contact info to CRM (fallback): %s", e)
                            tool_result = f"Error saving contact info: {e}"
                    else:
                        tool_result = "Error: contact_id not provided for saving contact info."
                elif func_name == "book_appointment":
                    name = args.get("name")
                    email = args.get("email")
                    date_time_iso = args.get("date_time_iso")
                    
                    if not name or not email or not date_time_iso:
                        tool_result = "Error: Missing required parameters ('name', 'email', 'date_time_iso') for booking."
                    else:
                        # Update Chatwoot CRM contact
                        if contact_id:
                            try:
                                logger.info("Updating Chatwoot CRM contact_id=%s with name=%s, email=%s (fallback)", contact_id, name, email)
                                await chatwoot_client.update_contact(contact_id, name=name, email=email)
                            except Exception as e:
                                logger.error("Failed to update Chatwoot CRM contact (fallback): %s", e)
                                
                        tool_result = await create_booking(name, email, date_time_iso)
                        
                        # Send booking notification email in the background
                        if chat_id and "Successfully booked" in tool_result:
                            try:
                                from app.utils.email import send_booking_notification
                                history = _get_history(chat_id)
                                asyncio.create_task(send_booking_notification(name, email, date_time_iso, list(history)))
                            except Exception as ex:
                                logger.error("Failed to trigger fallback booking notification task: %s", ex)
                elif func_name == "handoff_to_human":
                    try:
                        await chatwoot_client.update_conversation_status(chat_id, "open")
                        await chatwoot_client.send_outgoing_message(
                            conversation_id=chat_id,
                            content="⚠️ The AI has handed off this conversation to a human agent.",
                            private=True
                        )
                        tool_result = "Success: Conversation handed off to human agent. You MUST stop generating responses now."
                    except Exception as e:
                        logger.error("Failed to handoff conversation: %s", e)
                        tool_result = f"Error handing off: {e}"
                elif func_name == "resolve_conversation":
                    try:
                        await chatwoot_client.update_conversation_status(chat_id, "resolved")
                        tool_result = "Success: Conversation marked as resolved. You MUST stop generating responses now."
                    except Exception as e:
                        logger.error("Failed to resolve conversation: %s", e)
                        tool_result = f"Error resolving: {e}"
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
            response = await acompletion_with_retry(
                model=settings.llm_model,
                messages=history,
                api_base=settings.llm_api_base if settings.llm_api_base else None,
                api_key=settings.llm_api_key if settings.llm_api_key else None,
                tools=TOOLS_SCHEMA,
                stream=False,
                num_retries=3,
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
        try:
            await chatwoot_client.update_conversation_status(chat_id, "open")
            await chatwoot_client.send_outgoing_message(
                conversation_id=chat_id,
                content=f"⚠️ The AI encountered a critical error and has deactivated itself. Human intervention required. Error: {str(exc)}",
                private=True
            )
        except Exception as handoff_e:
            logger.error("Failed to handoff on exception: %s", handoff_e)
        history.pop()
        return None


def clear_history(chat_id: int) -> None:
    """Reset conversation history for a given chat."""
    _history.pop(chat_id, None)
    logger.debug("Cleared AI history for chat_id=%s", chat_id)
