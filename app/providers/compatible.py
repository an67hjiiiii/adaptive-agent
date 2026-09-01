from __future__ import annotations
import os
from collections.abc import Mapping
from openai import AsyncOpenAI
from app.providers.base import Provider
from app.core.types import ProviderResult, Usage


class OpenAICompatibleProvider(Provider):
    """Small adapter for providers exposing an OpenAI-compatible Chat API."""

    _REQUEST_PARAMETER_KEYS = {
        "temperature",
        "max_completion_tokens",
        "top_p",
        "reasoning_effort",
        "response_format",
        "stream",
        "n",
        "seed",
        "service_tier",
        "stop",
    }

    def __init__(
        self,
        *,
        name: str,
        model: str,
        api_key: str,
        base_url: str,
        extra_headers: dict | None = None,
        generation_settings: Mapping | None = None,
        timeout_seconds: float | None = None,
    ):
        if not api_key:
            raise ValueError(f"{name.upper()}_API_KEY is not configured")
        self.name = name
        self.model = model
        settings = dict(generation_settings or {})
        # ``pilot_config_snapshot`` passes a full generation-settings block;
        # direct callers may pass only the request parameters.
        if isinstance(settings.get("request_parameters"), Mapping):
            self.generation_settings_identity = settings.get("model_settings_id")
            self.generation_settings_version = settings.get("model_settings_version")
            timeout_seconds = settings.get("provider_timeout_seconds", timeout_seconds)
            settings = dict(settings["request_parameters"])
        else:
            self.generation_settings_identity = None
            self.generation_settings_version = None
        self.generation_settings = settings
        self.provider_timeout_seconds = float(timeout_seconds) if timeout_seconds is not None else None
        client_kwargs = {
            "api_key": api_key,
            "base_url": base_url,
            "default_headers": extra_headers or None,
        }
        if self.provider_timeout_seconds is not None:
            client_kwargs["timeout"] = self.provider_timeout_seconds
        # Provider-level retries stay off; the orchestrator owns the logical-
        # call retry budget and physical-request accounting.
        self.client = AsyncOpenAI(max_retries=0, **client_kwargs)
        self.last_request_parameters: dict = {}
        self.last_usage_fields: dict[str, list[str]] = {}

    @staticmethod
    def _nested_value(value, key):
        if isinstance(value, Mapping):
            return value.get(key)
        return getattr(value, key, None)

    @staticmethod
    def _field_names(value) -> list[str]:
        if value is None:
            return []
        if hasattr(value, "model_dump"):
            try:
                data = value.model_dump()
            except Exception:
                data = {}
        elif isinstance(value, Mapping):
            data = dict(value)
        else:
            data = {
                key: getattr(value, key)
                for key in dir(value)
                if not key.startswith("_") and not callable(getattr(value, key, None))
            }
        return sorted(str(key) for key, item in data.items() if item is not None)

    async def generate(self, *, system: str, user: str) -> ProviderResult:
        request = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        extra_body = {}
        for key, value in self.generation_settings.items():
            if value is None:
                # ``None`` is retained in the config as an intentional
                # omission (for example an unused seed), not sent as a
                # provider value.
                continue
            if key == "include_reasoning":
                # Groq exposes this field but the installed OpenAI SDK does
                # not type it yet; ``extra_body`` still serializes it exactly
                # as an API request parameter.
                extra_body[key] = value
            elif key in self._REQUEST_PARAMETER_KEYS:
                request[key] = value
        if extra_body:
            request["extra_body"] = extra_body
        self.last_request_parameters = {
            key: value for key, value in request.items() if key not in {"messages"}
        }
        response = await self.client.chat.completions.create(**request)
        choice = (response.choices or [None])[0]
        text = getattr(getattr(choice, "message", None), "content", "") or ""
        if not text.strip():
            raise ValueError(f"{self.name} returned an empty response")
        usage = getattr(response, "usage", None)
        usage_available = usage is not None and any(
            getattr(usage, key, None) is not None for key in ("prompt_tokens", "completion_tokens")
        )
        inp = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        out = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        prompt_details = getattr(usage, "prompt_tokens_details", None) if usage else None
        completion_details = getattr(usage, "completion_tokens_details", None) if usage else None
        cached = self._nested_value(prompt_details, "cached_tokens")
        reasoning = self._nested_value(completion_details, "reasoning_tokens")
        self.last_usage_fields = {
            "usage": self._field_names(usage),
            "prompt_tokens_details": self._field_names(prompt_details),
            "completion_tokens_details": self._field_names(completion_details),
        }
        return ProviderResult(
            text=text,
            usage=Usage(
                inp,
                out,
                cached_input_tokens=int(cached) if cached is not None else None,
                reasoning_tokens=int(reasoning) if reasoning is not None else None,
            ),
            request_id=getattr(response, "id", None),
            model=getattr(response, "model", None) or self.model,
            usage_metadata_available=usage_available,
        )


def groq_provider(model: str | None = None, *, generation_settings: Mapping | None = None, timeout_seconds: float | None = None):
    return OpenAICompatibleProvider(
        name="groq",
        model=model or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        api_key=os.getenv("GROQ_API_KEY", ""),
        base_url="https://api.groq.com/openai/v1",
        generation_settings=generation_settings,
        timeout_seconds=timeout_seconds,
    )


def openrouter_provider(model: str | None = None, *, generation_settings: Mapping | None = None, timeout_seconds: float | None = None):
    headers = {}
    if os.getenv("OPENROUTER_APP_URL"):
        headers["HTTP-Referer"] = os.getenv("OPENROUTER_APP_URL")
    if os.getenv("OPENROUTER_APP_NAME"):
        headers["X-Title"] = os.getenv("OPENROUTER_APP_NAME")
    return OpenAICompatibleProvider(
        name="openrouter",
        model=model or os.getenv("OPENROUTER_MODEL", "openrouter/free"),
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
        base_url="https://openrouter.ai/api/v1",
        extra_headers=headers,
        generation_settings=generation_settings,
        timeout_seconds=timeout_seconds,
    )
