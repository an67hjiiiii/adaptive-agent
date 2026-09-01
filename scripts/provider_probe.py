from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main(
    provider_name: str,
    model_name: str | None = None,
    timeout_seconds: float = 90,
    *,
    pilot_settings: bool = False,
) -> int:
    load_dotenv(ROOT / ".env")
    from app.core.provider_diagnostics import run_provider_diagnostic
    from app.providers.factory import get_provider
    from app.main import model_catalog, provider_configured, validated_model
    from app.core.pilot import pilot_config_snapshot

    configured = provider_configured(provider_name)
    defaults, _ = model_catalog()
    model = model_name or defaults.get(provider_name)
    if configured:
        try:
            model = validated_model(provider_name, model)
        except Exception:
            # The API endpoint emits the same normalized MODEL_NOT_FOUND result;
            # keep this standalone smoke command schema-compatible.
            from app.core.provider_diagnostics import diagnostic_for_category
            diagnostic = diagnostic_for_category(provider_name, True, "MODEL_NOT_FOUND", latency_ms=0, preflight=True)
            print(json.dumps(diagnostic, ensure_ascii=False, sort_keys=True))
            return 1

    generation_settings = None
    settings_identity = None
    if pilot_settings:
        snapshot = pilot_config_snapshot(provider=provider_name, model=model)
        generation_settings = snapshot.get("generation_settings")
        settings_identity = generation_settings.get("model_settings_id") if isinstance(generation_settings, dict) else None

    created_provider = None

    def provider_factory(name: str, *, model: str | None = None):
        nonlocal created_provider
        created_provider = get_provider(name, model=model, generation_settings=generation_settings)
        return created_provider

    diagnostic = await run_provider_diagnostic(
        provider_name=provider_name,
        configured=configured,
        model=model,
        provider_factory=provider_factory,
        timeout_seconds=timeout_seconds,
    )
    if pilot_settings:
        diagnostic = {
            **diagnostic,
            "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "settings_identity": settings_identity,
            "usage_fields": getattr(created_provider, "last_usage_fields", {}) if created_provider else {},
            "request_parameters_sent": sorted(
                key for key in (getattr(created_provider, "last_request_parameters", {}) or {})
                if key != "extra_body"
            ) if created_provider else [],
            "extra_body_parameters_sent": sorted(
                (getattr(created_provider, "last_request_parameters", {}) or {}).get("extra_body", {})
            ) if created_provider else [],
            "result": "PASS" if diagnostic.get("error_category") == "SUCCESS" else "FAIL",
        }
    print(json.dumps(diagnostic, ensure_ascii=False, sort_keys=True))
    return 0 if diagnostic["error_category"] == "SUCCESS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=("fake", "gemini", "groq", "openrouter", "openai"))
    parser.add_argument("--model", help="Optional model id; otherwise use the .env default.")
    parser.add_argument("--timeout", type=float, default=90, help="Probe timeout in seconds (default: 90).")
    parser.add_argument(
        "--pilot-settings",
        action="store_true",
        help="Use the frozen MODEL-PILOT-V1 request settings and emit a safe settings/usage summary.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.provider, args.model, max(1, args.timeout), pilot_settings=args.pilot_settings)))
