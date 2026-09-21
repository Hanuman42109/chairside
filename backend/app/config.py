"""Centralized app configuration, loaded from environment variables / .env.

Every integration module should read credentials from `settings` (this module),
never from `os.environ` directly, so there is exactly one place that knows
where configuration comes from.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    environment: Literal["development", "production"] = "development"
    log_level: str = "INFO"
    cors_allowed_origins: str = "http://localhost:5173"

    # --- Dental office context ---
    office_name: str = "Chairside Dental"
    office_timezone: str = "America/New_York"
    office_phone: str = ""

    # --- LLM provider switch ---
    llm_provider: Literal["groq", "anthropic", "openai"] = "groq"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # --- Retell AI ---
    retell_api_key: str = ""
    retell_webhook_secret: str = ""

    # --- Cal.com ---
    calcom_api_key: str = ""
    calcom_api_base_url: str = "https://api.cal.com/v2"
    calcom_event_type_id: str = ""

    # --- HubSpot ---
    hubspot_access_token: str = ""
    hubspot_api_base_url: str = "https://api.hubapi.com"

    # --- Twilio ---
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # --- Supabase / Postgres ---
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    database_url: str = ""

    # --- Local demo ---
    # When true, calcom/hubspot/twilio_sms tool calls return fake data instead
    # of hitting real provider APIs -- lets the full booking conversation run
    # end-to-end without those accounts. Flip to false once real keys are set.
    tools_mock_mode: bool = True

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Settings are cached for the process lifetime; construct via this accessor."""
    return Settings()
