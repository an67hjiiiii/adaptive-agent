import os
from collections.abc import Mapping
from app.providers.fake import FakeProvider


def get_provider(name: str, model: str | None = None, *, generation_settings: Mapping | None = None):
    name=(name or os.getenv("DEFAULT_PROVIDER","fake")).lower()
    settings = dict(generation_settings or {})
    timeout_seconds = None
    if isinstance(settings.get("request_parameters"), Mapping):
        timeout_seconds = settings.get("provider_timeout_seconds")
    elif "provider_timeout_seconds" in settings:
        timeout_seconds = settings.get("provider_timeout_seconds")
    if name=="fake": return FakeProvider()
    if name=="openai":
        from app.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(model=model)
    if name=="gemini":
        from app.providers.gemini_provider import GeminiProvider
        return GeminiProvider(model=model)
    if name=="groq":
        from app.providers.compatible import groq_provider
        return groq_provider(model=model, generation_settings=generation_settings, timeout_seconds=timeout_seconds)
    if name=="openrouter":
        from app.providers.compatible import openrouter_provider
        return openrouter_provider(model=model, generation_settings=generation_settings, timeout_seconds=timeout_seconds)
    raise ValueError(f"Unknown provider: {name}")
