"""Safe run-level incident records and the Pilot outcome taxonomy.

Provider SDK exceptions frequently contain response bodies or headers.  This
module extracts only a small allowlist of reproducibility fields.  The raw
exception and response body are intentionally never returned or persisted.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Mapping

from app.core.provider_diagnostics import classify_provider_error
from app.core.security import redact_secrets


INCIDENT_TAXONOMY_VERSION = "INCIDENT-TAXONOMY-V1"

RUN_OUTCOME_CATEGORIES = (
    "SUCCESS",
    "STRATEGY_TERMINAL_FAILURE",
    "RATE_LIMITED",
    "TIMEOUT",
    "NETWORK_OR_DNS",
    "AUTHENTICATION_OR_PERMISSION",
    "QUOTA_OR_CREDIT",
    "MODEL_NOT_FOUND",
    "PROVIDER_ERROR",
    "EXPERIMENT_INFRASTRUCTURE_ERROR",
    "INVALID_INPUT_OR_SCOPE",
    "INTERRUPTED_OR_STALE",
)

_PROVIDER_TO_RUN_CATEGORY = {
    "RATE_LIMITED": "RATE_LIMITED",
    "TIMEOUT": "TIMEOUT",
    "NETWORK_BLOCKED": "NETWORK_OR_DNS",
    "DNS_ERROR": "NETWORK_OR_DNS",
    "AUTHENTICATION_FAILED": "AUTHENTICATION_OR_PERMISSION",
    "PERMISSION_DENIED": "AUTHENTICATION_OR_PERMISSION",
    "MODEL_NOT_FOUND": "MODEL_NOT_FOUND",
    "QUOTA_EXHAUSTED": "QUOTA_OR_CREDIT",
    "CREDIT_EXHAUSTED": "QUOTA_OR_CREDIT",
    "PROVIDER_ERROR": "PROVIDER_ERROR",
    "NOT_CONFIGURED": "AUTHENTICATION_OR_PERMISSION",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _status_code(error: BaseException | None) -> int | None:
    if error is None:
        return None
    response = getattr(error, "response", None)
    for value in (
        getattr(error, "status_code", None),
        getattr(error, "status", None),
        getattr(response, "status_code", None),
    ):
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _safe_headers(error: BaseException | None) -> dict[str, str]:
    """Copy only rate-limit/request headers; never authorization/cookies/body."""

    if error is None:
        return {}
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return {}
    result: dict[str, str] = {}
    try:
        items = headers.items()
    except Exception:
        return result
    for key, value in items:
        normalized = str(key).lower()
        if normalized == "retry-after" or normalized.startswith("x-ratelimit-"):
            # Header values are bounded and redacted in case a proxy emits an
            # unexpected token-like value.
            text = redact_secrets(str(value)).strip()
            if len(text) <= 120 and not re.search(r"authorization|cookie|api[-_]?key", normalized):
                result[normalized] = text
    return result


def _retry_after(error: BaseException | None, headers: Mapping[str, str]) -> float | None:
    value = headers.get("retry-after")
    if value is None and error is not None:
        response = getattr(error, "response", None)
        value = getattr(getattr(response, "headers", None), "get", lambda *_: None)("retry-after")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def run_category_for_provider(provider_category: str | None) -> str:
    return _PROVIDER_TO_RUN_CATEGORY.get(str(provider_category or ""), "PROVIDER_ERROR")


def safe_provider_incident(
    error: BaseException,
    *,
    provider: str,
    model: str,
    attempt: int | None = None,
    retry: int | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build a structured, secret-safe provider incident record."""

    provider_category, safe_message = classify_provider_error(error)
    headers = _safe_headers(error)
    response = getattr(error, "response", None)
    safe_request_id = request_id
    if not safe_request_id:
        try:
            response_headers = getattr(response, "headers", None)
            safe_request_id = str(
                (response_headers.get("x-request-id") if response_headers is not None else None)
                or (response_headers.get("request-id") if response_headers is not None else None)
                or ""
            ) or None
            if safe_request_id and len(safe_request_id) > 160:
                safe_request_id = None
        except Exception:
            safe_request_id = None
    record: dict[str, Any] = {
        "taxonomy_version": INCIDENT_TAXONOMY_VERSION,
        "origin": "provider",
        "category": run_category_for_provider(provider_category),
        "provider_error_category": provider_category,
        "provider": str(provider),
        "model": str(model),
        "http_status": _status_code(error),
        "safe_message": safe_message,
        "request_id": safe_request_id,
        "attempt": attempt,
        "retry": retry,
        "retry_after_seconds": _retry_after(error, headers),
        "safe_rate_limit_headers": headers,
        "recorded_at": _now(),
    }
    # A provider response object can contain a request ID in its body, but
    # that body is intentionally ignored.  This record is the complete raw
    # incident evidence allowlist.
    return record


def safe_runtime_incident(
    *,
    category: str,
    safe_message: str,
    provider: str | None = None,
    model: str | None = None,
    origin: str = "runtime",
    **extra: Any,
) -> dict[str, Any]:
    """Build an allowlisted non-provider runtime incident."""

    if category not in RUN_OUTCOME_CATEGORIES:
        raise ValueError(f"Unsupported run outcome category: {category}")
    record: dict[str, Any] = {
        "taxonomy_version": INCIDENT_TAXONOMY_VERSION,
        "origin": origin,
        "category": category,
        "provider": provider,
        "model": model,
        "http_status": None,
        "safe_message": redact_secrets(safe_message)[:500],
        "request_id": None,
        "attempt": extra.get("attempt"),
        "retry": extra.get("retry"),
        "retry_after_seconds": None,
        "safe_rate_limit_headers": {},
        "recorded_at": _now(),
    }
    return record


__all__ = [
    "INCIDENT_TAXONOMY_VERSION",
    "RUN_OUTCOME_CATEGORIES",
    "run_category_for_provider",
    "safe_provider_incident",
    "safe_runtime_incident",
]
