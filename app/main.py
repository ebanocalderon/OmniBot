"""
FastAPI application — entry point for the bridge server.

Responsibilities:
  - Initialise the SQLite database on startup
  - Start the Telegram polling loop as a background asyncio.Task
  - Mount the Chatwoot webhook router
  - Expose GET /health for liveness checks
"""
from __future__ import annotations

import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.chatwoot.client import chatwoot_client
from app.chatwoot.webhook import router as chatwoot_router
from app.config import settings
from app.database import init_db

# ── Logging setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Lifespan ──────────────────────────────────────────────────────────────────

_telegram_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Startup / shutdown logic executed by FastAPI around the application lifetime.
    """
    global _telegram_task

    # ── Startup ───────────────────────────────────────────────────
    logger.info("=== Bridge starting up ===")

    # 1. Create DB tables if they don't exist
    await init_db()

    # 2. Launch Telegram polling in the background
    from app.telegram.bot import run_telegram_polling  # noqa: PLC0415

    _telegram_task = asyncio.create_task(
        run_telegram_polling(), name="telegram-polling"
    )
    logger.info("Telegram polling task started")

    yield  # ← application runs here

    # ── Shutdown ──────────────────────────────────────────────────
    logger.info("=== Bridge shutting down ===")

    if _telegram_task and not _telegram_task.done():
        _telegram_task.cancel()
        try:
            await _telegram_task
        except asyncio.CancelledError:
            pass
        logger.info("Telegram polling task stopped")

    await chatwoot_client.aclose()
    logger.info("Chatwoot HTTP client closed")


# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Chatwoot ↔ Telegram Bridge",
    description=(
        "A local webhook server that bi-directionally connects a "
        "self-hosted Chatwoot instance to a Telegram bot."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(chatwoot_router)

# ── Health endpoint ───────────────────────────────────────────────────────────


@app.get("/health", tags=["system"], summary="Liveness check")
async def health() -> JSONResponse:
    """
    Returns 200 OK when the server is running.
    Used by load balancers, Docker health checks, and monitoring tools.
    """
    polling_alive = _telegram_task is not None and not _telegram_task.done()
    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "telegram_polling": polling_alive,
        },
    )


@app.get("/", include_in_schema=False)
async def root() -> JSONResponse:
    return JSONResponse({"message": "Chatwoot ↔ Telegram Bridge is running. See /docs."})
