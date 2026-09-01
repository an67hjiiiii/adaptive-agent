from __future__ import annotations
import os
import httpx
from app.core.types import ProviderResult, Usage
from app.providers.base import Provider


class GeminiProvider(Provider):
    """Gemini Interactions API provider (recommended API for new Gemini projects)."""

    name = "gemini"

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.timeout_seconds = float(os.getenv("CALL_TIMEOUT_SECONDS", "60"))
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

    @staticmethod
    def _output_text(data: dict) -> str:
        chunks = []
        for step in data.get("steps") or []:
            if step.get("type") != "model_output":
                continue
            for item in step.get("content") or []:
                if item.get("type") == "text" and item.get("text"):
                    chunks.append(item["text"])
        # Be tolerant of the earlier Interactions schema while users migrate.
        for item in data.get("outputs") or []:
            if item.get("type") == "text" and item.get("text"):
                chunks.append(item["text"])
        return "".join(chunks).strip()

    async def generate(self, *, system: str, user: str) -> ProviderResult:
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "input": user,
            "system_instruction": system,
            "generation_config": {
                "max_output_tokens": int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "2048")),
                "thinking_level": os.getenv("GEMINI_THINKING_LEVEL", "low").lower(),
            },
        }
        if "return json only" in system.lower():
            payload["response_format"] = {"type": "text", "mime_type": "application/json"}

        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/interactions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        text = self._output_text(data)
        if not text:
            raise ValueError("Gemini returned an empty response")
        usage = data.get("usage") or {}
        usage_available = any(key in usage for key in
                              ("total_input_tokens", "prompt_tokens", "total_output_tokens", "completion_tokens"))
        inp = int(usage.get("total_input_tokens") or usage.get("prompt_tokens") or 0)
        out = int(usage.get("total_output_tokens") or usage.get("completion_tokens") or 0)
        return ProviderResult(
            text=text,
            usage=Usage(inp, out),
            request_id=data.get("id") or response.headers.get("x-request-id"),
            model=data.get("model") or self.model,
            usage_metadata_available=usage_available,
        )
