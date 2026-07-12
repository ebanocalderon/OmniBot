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

# ── Logging setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Startup / shutdown logic executed by FastAPI around the application lifetime.
    """
    # ── Startup ───────────────────────────────────────────────────
    logger.info("=== Bridge starting up ===")
    yield  # ← application runs here

    # ── Shutdown ──────────────────────────────────────────────────
    logger.info("=== Bridge shutting down ===")

    await chatwoot_client.aclose()
    logger.info("Chatwoot HTTP client closed")


# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Chatwoot AI Agent Bot",
    description=(
        "A local webhook server that bi-directionally connects a "
        "self-hosted Chatwoot instance to any LLM (Ollama, OpenAI, Anthropic)."
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
    return JSONResponse(
        status_code=200,
        content={
            "status": "ok"
        },
    )


@app.get("/", include_in_schema=False)
async def root() -> JSONResponse:
    return JSONResponse({"message": "Chatwoot AI Agent Bot is running. See /docs."})
