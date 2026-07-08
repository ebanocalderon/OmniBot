"""
Telegram bot — handlers and polling runner.

This module:
  1. Defines all python-telegram-bot handlers (start, text, media, etc.)
  2. Exposes `send_telegram_message()` so the webhook router can push
     agent replies back to Telegram.
  3. Exposes `run_telegram_polling()` — an async coroutine that starts
     long-polling and runs until cancelled.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.ai.client import clear_history as clear_ai_history
from app.ai.client import get_ai_response
from app.chatwoot.client import chatwoot_client
from app.config import settings
from app.database import delete_session, get_session_by_chat_id, upsert_session

logger = logging.getLogger(__name__)

# ── Build the Application (lazy singleton) ────────────────────────────────────
# We build once and reuse; the Application object owns the Bot instance.

_application: Application | None = None


def get_application() -> Application:
    global _application
    if _application is None:
        _application = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .build()
        )
    return _application


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _ensure_chatwoot_session(update: Update) -> int | None:
    """
    Guarantee that a Chatwoot contact + conversation exists for this
    Telegram user.  Returns the Chatwoot conversation_id, or None on error.
    """
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return None

    chat_id: int = chat.id

    # Check local DB first
    session = await get_session_by_chat_id(chat_id)
    if session:
        conversation_id, _ = session
        return conversation_id

    # Create / fetch Chatwoot contact
    try:
        contact = await chatwoot_client.get_or_create_contact(
            telegram_chat_id=chat_id,
            first_name=user.first_name or "Telegram User",
            last_name=user.last_name,
            username=user.username,
        )
        contact_id: int = contact["id"]

        # Create / fetch conversation
        conversation = await chatwoot_client.get_or_create_conversation(
            contact_id=contact_id,
            telegram_chat_id=chat_id,
        )
        conversation_id = conversation["id"]

        # Persist mapping
        await upsert_session(chat_id, conversation_id, contact_id)
        return conversation_id

    except Exception as exc:
        logger.exception("Failed to set up Chatwoot session for chat_id=%s: %s", chat_id, exc)
        return None


async def _send_to_chatwoot(update: Update, content: str, content_type: str = "text") -> bool:
    """
    Send a message to Chatwoot, transparently recovering if the conversation
    was deleted on the Chatwoot side.
    """
    chat_id = update.effective_chat.id
    conversation_id = await _ensure_chatwoot_session(update)
    if not conversation_id:
        return False

    try:
        await chatwoot_client.send_incoming_message(
            conversation_id=conversation_id,
            content=content,
            content_type=content_type,
        )
        return True
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            logger.warning("Conversation %s not found (likely deleted). Resetting session for chat_id=%s.", conversation_id, chat_id)
            await delete_session(chat_id)
            # Retry once with a fresh session
            conversation_id = await _ensure_chatwoot_session(update)
            if conversation_id:
                try:
                    await chatwoot_client.send_incoming_message(
                        conversation_id=conversation_id,
                        content=content,
                        content_type=content_type,
                    )
                    return True
                except Exception as exc2:
                    logger.exception("Failed to send message to Chatwoot after retry: %s", exc2)
        else:
            logger.exception("HTTP error sending to Chatwoot: %s", exc)
    except Exception as exc:
        logger.exception("Failed to send message to Chatwoot: %s", exc)
    
    return False


# ── Command Handlers ──────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start  — welcome message and Chatwoot session bootstrap.
    """
    user = update.effective_user
    if not user:
        return

    first_name = user.first_name or "there"
    await update.message.reply_text(
        f"👋 Hi {first_name}! You're now connected to our support team.\n"
        "Type your message and an agent will get back to you shortly.",
        parse_mode=ParseMode.HTML,
    )

    # Make sure a conversation exists right away
    await _ensure_chatwoot_session(update)
    # Reset AI conversation history on /start
    clear_ai_history(update.effective_chat.id)
    logger.info("User %s started the bot (chat_id=%s)", user.username or user.id, update.effective_chat.id)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /help  — show usage info.
    """
    await update.message.reply_text(
        "ℹ️ <b>How to use this support bot:</b>\n\n"
        "• Just type your message — our team will reply here.\n"
        "• Use /start to restart the session.\n"
        "• Use /status to check if you're connected.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /status  — confirm the bridge is working.
    """
    chat_id = update.effective_chat.id
    session = await get_session_by_chat_id(chat_id)
    if session:
        conversation_id, _ = session
        await update.message.reply_text(
            f"✅ Connected — Conversation #{conversation_id} is active.",
        )
    else:
        await update.message.reply_text(
            "⚠️ No active session. Send /start to create one.",
        )


# ── Message Handlers ──────────────────────────────────────────────────────────


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Forward any plain text message from Telegram → Chatwoot,
    then get an AI response and reply directly in Telegram.
    """
    text = update.message.text or ""
    if not text.strip():
        return

    chat_id = update.effective_chat.id

    # 1. Forward to Chatwoot for agent visibility
    success = await _send_to_chatwoot(update, text, "text")
    if success:
        logger.info("Forwarded text from chat_id=%s", chat_id)
    else:
        await update.message.reply_text(
            "❌ Failed to send your message. Please try again.",
        )

    # 2. Get AI response if enabled
    if settings.ai_enabled:
        bot: Bot = get_application().bot
        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass

        ai_reply = await get_ai_response(chat_id, text)

        if ai_reply:
            await send_telegram_message(chat_id=chat_id, text=ai_reply)

            # 3. Also post AI response to Chatwoot so agents see it
            conversation_id = await _ensure_chatwoot_session(update)
            if conversation_id:
                try:
                    await chatwoot_client.send_outgoing_message(
                        conversation_id=conversation_id,
                        content=f"[AI] {ai_reply}",
                    )
                except Exception as exc:
                    logger.warning(
                        "Could not send AI reply to Chatwoot conversation %s: %s",
                        conversation_id,
                        exc,
                    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Notify agent that a photo was sent (file forwarding requires extra infra).
    """
    caption = update.message.caption or ""
    content = f"[📷 Photo received]"
    if caption:
        content += f"\nCaption: {caption}"

    await _send_to_chatwoot(update, content)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Notify agent that a file was sent.
    """
    doc = update.message.document
    file_name = doc.file_name if doc else "unknown"
    content = f"[📎 File received: {file_name}]"

    await _send_to_chatwoot(update, content)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Notify agent that a voice message was sent.
    """
    await _send_to_chatwoot(update, "[🎤 Voice message received]")


async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Notify agent that a sticker was sent.
    """
    sticker = update.message.sticker
    emoji = sticker.emoji if sticker else ""
    content = f"[Sticker sent{': ' + emoji if emoji else ''}]"

    await _send_to_chatwoot(update, content)


# ── Public API ────────────────────────────────────────────────────────────────


async def send_telegram_message(chat_id: int, text: str) -> None:
    """
    Send a message to a Telegram user from the bot.
    Called by the Chatwoot webhook handler when an agent replies.
    """
    bot: Bot = get_application().bot
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as exc:
        logger.exception(
            "Failed to send Telegram message to chat_id=%s: %s", chat_id, exc
        )


# ── Polling runner ────────────────────────────────────────────────────────────


async def run_telegram_polling() -> None:
    """
    Start the Telegram long-polling loop.  This coroutine runs as a background
    asyncio.Task inside the FastAPI lifespan and is cancelled on shutdown.
    """
    app = get_application()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))

    logger.info("Starting Telegram long-polling …")
    async with app:
        await app.start()
        # run_polling() blocks until the application is stopped
        await app.updater.start_polling(drop_pending_updates=True)
        # Keep the coroutine alive until cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            logger.info("Telegram polling cancelled — shutting down")
        finally:
            await app.updater.stop()
            await app.stop()
