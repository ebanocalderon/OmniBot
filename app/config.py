"""
Configuration management via pydantic-settings.
All values are loaded from environment variables (or a .env file).
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Chatwoot ──────────────────────────────────────────────────
    chatwoot_base_url: str = Field(..., description="Base URL of the Chatwoot instance (no trailing slash)")
    chatwoot_api_token: str = Field(..., description="Chatwoot Agent Bot access token")
    chatwoot_account_id: int = Field(..., description="Chatwoot numeric account ID")

    # ── Server ────────────────────────────────────────────────────
    server_host: str = Field(default="0.0.0.0", description="Host to bind the webhook server")
    server_port: int = Field(default=8000, description="Port for the webhook server")
    webhook_secret: str = Field(default="", description="Shared secret for Chatwoot webhook validation")

    # ── AI Agent (LiteLLM) ─────────────────────────────────────────
    llm_model: str = Field(default="ollama/qwen:3.50.8b", description="LiteLLM model name (e.g. gpt-4o, ollama/qwen)")
    llm_api_base: str = Field(default="http://localhost:11434", description="API base URL (for local models or proxies)")
    llm_api_key: str = Field(default="", description="API Key for the provider (OpenAI, Anthropic, etc.)")
    ai_system_prompt: str = Field(
        default="You are a helpful support assistant. Be concise, friendly, and answer in the same language the user writes to you. Do not output any thinking process or <think> tags; answer directly.",
        description="System prompt for the AI model",
    )
    ai_max_history: int = Field(default=20, description="Max conversation turns to keep in memory per chat")

    # ── Logging ───────────────────────────────────────────────────
    log_level: str = Field(default="INFO", description="Python logging level")

    # ── Cal.com ───────────────────────────────────────────────────
    cal_api_key: str = Field(default="", description="Cal.com API key (e.g., cal_live_...)")
    cal_event_type_id: int = Field(default=0, description="Numeric event type ID from Cal.com")

    # ── Notification Email (Gmail API) ────────────────────────────
    notification_email: str = Field(default="", description="Recipient email address for lead notifications")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    import os
    s = Settings()
    prompt_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "system_prompt.txt")
    if os.path.exists(prompt_file):
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                s.ai_system_prompt = f.read().strip()
        except Exception:
            pass
    return s


# Convenient module-level alias
settings = get_settings()
