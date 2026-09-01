from __future__ import annotations
import os
from openai import AsyncOpenAI
from app.providers.base import Provider
from app.core.types import ProviderResult, Usage

class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("OPENAI_MODEL","gpt-5.6-luna")
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not configured")
        self.client = AsyncOpenAI(api_key=self.api_key, max_retries=0)

    async def generate(self, *, system: str, user: str) -> ProviderResult:
        response = await self.client.responses.create(
            model=self.model,
            instructions=system,
            input=user,
        )
        usage = getattr(response, "usage", None)
        usage_available = usage is not None and any(
            getattr(usage, key, None) is not None for key in ("input_tokens", "output_tokens")
        )
        inp = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        out = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
        text=getattr(response,"output_text","") or ""
        if not text.strip():
            raise ValueError("OpenAI returned an empty response")
        return ProviderResult(
            text=text,
            usage=Usage(inp,out),
            request_id=getattr(response, "_request_id", None),
            model=self.model,
            usage_metadata_available=usage_available,
        )
