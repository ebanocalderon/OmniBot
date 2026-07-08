"""
Async SQLite session store.
Maps: telegram_chat_id  ←→  chatwoot_conversation_id + chatwoot_contact_id

The DB is created (and migrated) automatically on first startup.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)

# ── Schema ────────────────────────────────────────────────────────────────────

_CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    telegram_chat_id          INTEGER PRIMARY KEY,
    chatwoot_conversation_id  INTEGER NOT NULL,
    chatwoot_contact_id       INTEGER NOT NULL,
    created_at                TEXT    DEFAULT (datetime('now')),
    updated_at                TEXT    DEFAULT (datetime('now'))
);
"""

_CREATE_REVERSE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_conversation_id
    ON sessions (chatwoot_conversation_id);
"""

# ── Lifecycle ─────────────────────────────────────────────────────────────────


async def init_db() -> None:
    """Create tables if they don't exist yet."""
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(_CREATE_SESSIONS_TABLE)
        await db.execute(_CREATE_REVERSE_INDEX)
        await db.commit()
    logger.info("Database initialised at '%s'", settings.database_path)


# ── Read ──────────────────────────────────────────────────────────────────────


async def get_session_by_chat_id(
    telegram_chat_id: int,
) -> Optional[Tuple[int, int]]:
    """
    Return (chatwoot_conversation_id, chatwoot_contact_id) for a given
    Telegram chat ID, or None if no session exists yet.
    """
    async with aiosqlite.connect(settings.database_path) as db:
        async with db.execute(
            "SELECT chatwoot_conversation_id, chatwoot_contact_id "
            "FROM sessions WHERE telegram_chat_id = ?",
            (telegram_chat_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return (row[0], row[1]) if row else None


async def get_chat_id_by_conversation(
    chatwoot_conversation_id: int,
) -> Optional[int]:
    """
    Return the Telegram chat ID linked to a Chatwoot conversation ID,
    or None if not found.
    """
    async with aiosqlite.connect(settings.database_path) as db:
        async with db.execute(
            "SELECT telegram_chat_id FROM sessions "
            "WHERE chatwoot_conversation_id = ?",
            (chatwoot_conversation_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


# ── Write ─────────────────────────────────────────────────────────────────────


async def upsert_session(
    telegram_chat_id: int,
    chatwoot_conversation_id: int,
    chatwoot_contact_id: int,
) -> None:
    """
    Insert or update the session row for a given Telegram chat ID.
    On conflict (same chat_id) the conversation and contact IDs are updated.
    """
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(
            """
            INSERT INTO sessions
                (telegram_chat_id, chatwoot_conversation_id, chatwoot_contact_id, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(telegram_chat_id) DO UPDATE SET
                chatwoot_conversation_id = excluded.chatwoot_conversation_id,
                chatwoot_contact_id      = excluded.chatwoot_contact_id,
                updated_at               = datetime('now')
            """,
            (telegram_chat_id, chatwoot_conversation_id, chatwoot_contact_id),
        )
        await db.commit()
    logger.debug(
        "Session upserted: chat_id=%s → conversation_id=%s",
        telegram_chat_id,
        chatwoot_conversation_id,
    )


async def delete_session(telegram_chat_id: int) -> None:
    """
    Delete the session for a given Telegram chat ID.
    Used when a conversation is deleted in Chatwoot to force a new session.
    """
    async with aiosqlite.connect(settings.database_path) as db:
        await db.execute(
            "DELETE FROM sessions WHERE telegram_chat_id = ?",
            (telegram_chat_id,),
        )
        await db.commit()
    logger.info("Session deleted for chat_id=%s", telegram_chat_id)
