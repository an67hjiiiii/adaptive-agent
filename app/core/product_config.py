"""Normal-product provider, model, and processing-mode configuration.

This module is intentionally separate from the Pilot configuration.  The
product picker may select a provider/model/mode for one chat request, while
the research executor continues to obtain its identity from its frozen
manifest.
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Mapping


PRODUCT_PROVIDERS = ("fake", "gemini", "groq", "openrouter", "openai")

# The catalog is code-backed rather than inferred from an environment value.
# Environment model defaults are accepted only when they are one of the
# explicitly listed product choices; an unknown value must not silently become
# a selectable model.
_MODEL_OPTIONS = {
    "fake": [
        {"id": "fake-research-v2", "label": "Fake Research v2", "tier": "offline"},
    ],
    "gemini": [
        {"id": "gemini-3.7-flash", "label": "Gemini 3.7 Flash", "tier": "recommended"},
        {"id": "gemini-3.6-flash", "label": "Gemini 3.6 Flash", "tier": "balanced"},
        {"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash-Lite", "tier": "economy"},
    ],
    "groq": [
        {"id": "openai/gpt-oss-120b", "label": "GPT-OSS 120B · Groq", "tier": "fast"},
        {"id": "openai/gpt-oss-20b", "label": "GPT-OSS 20B · Groq", "tier": "faster"},
        {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B · Groq", "tier": "general"},
    ],
    "openrouter": [
        {"id": "openrouter/free", "label": "OpenRouter Free Router", "tier": "dev-only"},
    ],
    "openai": [
        {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna", "tier": "economy"},
        {"id": "gpt-5.6-terra", "label": "GPT-5.6 Terra", "tier": "balanced"},
        {"id": "gpt-5.6-sol", "label": "GPT-5.6 Sol", "tier": "quality"},
    ],
}

_DEFAULT_ENV_KEYS = {
    "gemini": "GEMINI_MODEL",
    "groq": "GROQ_MODEL",
    "openrouter": "OPENROUTER_MODEL",
    "openai": "OPENAI_MODEL",
}

PRODUCT_MODE_OPTIONS = (
    {
        "id": "adaptive-auto",
        "label": "Tự động",
        "description": "Analyzer chọn DIRECT, PARALLEL hoặc PLANNED.",
    },
    {
        "id": "DIRECT",
        "label": "Trực tiếp",
        "description": "Một Direct Solver xử lý task rồi qua Verifier.",
    },
    {
        "id": "PARALLEL",
        "label": "Song song",
        "description": "Các phần độc lập chạy theo ready-set song song.",
    },
    {
        "id": "PLANNED",
        "label": "Theo kế hoạch",
        "description": "Planner dựng DAG trước khi thực thi.",
    },
)

PRODUCT_MODE_IDS = frozenset(item["id"] for item in PRODUCT_MODE_OPTIONS)
_MODE_ALIASES = {
    "auto": "adaptive-auto",
    "adaptive": "adaptive-auto",
    "adaptive-auto": "adaptive-auto",
    "direct": "DIRECT",
    "parallel": "PARALLEL",
    "planned": "PLANNED",
}


class ProductSelectionError(ValueError):
    """Safe, user-facing product selection validation error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def product_model_catalog(environ: Mapping[str, str] | None = None):
    """Return a fresh, code-backed product model catalog and defaults.

    ``environ`` is injectable for deterministic tests.  Invalid environment
    model IDs fall back to the first explicitly supported choice and are not
    inserted into the advertised options.
    """

    env = environ if environ is not None else os.environ
    options = deepcopy(_MODEL_OPTIONS)
    defaults = {
        "fake": options["fake"][0]["id"],
        "gemini": options["gemini"][0]["id"],
        "groq": options["groq"][0]["id"],
        "openrouter": options["openrouter"][0]["id"],
        "openai": options["openai"][0]["id"],
    }
    for provider, env_key in _DEFAULT_ENV_KEYS.items():
        configured = str(env.get(env_key, "") or "").strip()
        if configured and configured in {item["id"] for item in options[provider]}:
            defaults[provider] = configured
    return defaults, options


def product_mode_options():
    return deepcopy(list(PRODUCT_MODE_OPTIONS))


def normalize_product_mode(value: str | None) -> str:
    """Normalize the public product mode enum and reject unknown values."""

    raw = str(value or "adaptive-auto").strip()
    canonical = _MODE_ALIASES.get(raw.lower())
    if canonical is None:
        raise ProductSelectionError(
            "INVALID_PROCESSING_MODE",
            "Unsupported processing mode selection.",
        )
    return canonical


def validate_product_provider(provider: str | None) -> str:
    canonical = str(provider or "").strip().lower()
    if canonical not in PRODUCT_PROVIDERS:
        raise ProductSelectionError("UNSUPPORTED_PROVIDER", "Unsupported provider selection.")
    return canonical


def validate_product_model(provider: str | None, requested: str | None = None) -> str:
    canonical_provider = validate_product_provider(provider)
    defaults, options = product_model_catalog()
    model = str(requested or defaults[canonical_provider]).strip()
    allowed = {item["id"] for item in options[canonical_provider]}
    if model not in allowed:
        raise ProductSelectionError(
            "UNSUPPORTED_MODEL_SELECTION",
            "Unsupported model selection for this provider.",
        )
    return model


def product_mode_to_orchestrator_mode(mode: str | None) -> str | None:
    """Return the optional forced topology; AUTO remains controller-routed."""

    canonical = normalize_product_mode(mode)
    return None if canonical == "adaptive-auto" else canonical
