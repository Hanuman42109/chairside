"""LLM provider switch.

`get_chat_model()` returns a LangChain-compatible chat model chosen by
`settings.llm_provider`. Every graph node calls this instead of importing a
provider SDK directly, so swapping Groq -> Claude -> GPT-4o-mini is a one-line
config change (`LLM_PROVIDER` in .env), not a code change.
"""

from functools import lru_cache
from typing import Any

from app.config import get_settings


@lru_cache
def get_chat_model(temperature: float = 0.2) -> Any:
    """Return a LangChain BaseChatModel for the configured provider.

    Cached per (temperature) so nodes sharing a temperature reuse one client.
    """
    settings = get_settings()

    if settings.llm_provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            temperature=temperature,
        )

    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            temperature=temperature,
        )

    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            temperature=temperature,
        )

    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")
