"""Provider connectivity diagnostics with safe, normalized error taxonomy.

This module deliberately knows nothing about orchestration.  It probes one
provider with one bounded generation request and returns facts that are safe to
show in the local UI or persist as the last live-check result.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import json
import re
import socket
import time
from typing import Any, Callable

try:  # httpx is a runtime dependency, but keep classification import-safe.
    import httpx
except Exception:  # pragma: no cover - only relevant to a broken installation.
    httpx = None


ERROR_CATEGORIES = (
    "NOT_CONFIGURED",
    "NETWORK_BLOCKED",
    "DNS_ERROR",
    "TIMEOUT",
    "AUTHENTICATION_FAILED",
    "PERMISSION_DENIED",
    "MODEL_NOT_FOUND",
    "RATE_LIMITED",
    "QUOTA_EXHAUSTED",
    "CREDIT_EXHAUSTED",
    "PROVIDER_ERROR",
    "SUCCESS",
)


@dataclass(frozen=True)
class ProviderDiagnostic:
    provider: str
    configured: bool
    network_reachable: bool | None
    authenticated: bool | None
    model_access: bool | None
    generation_ok: bool
    usage_metadata_available: bool
    latency_ms: int | None
    error_category: str | None
    safe_message: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


SAFE_MESSAGES = {
    "NOT_CONFIGURED": "Provider API key is not configured.",
    "NETWORK_BLOCKED": "Outbound network access is blocked; run the smoke command on a network-enabled machine.",
    "DNS_ERROR": "Provider hostname could not be resolved; check DNS or proxy settings.",
    "TIMEOUT": "Provider request timed out; check network latency and retry.",
    "AUTHENTICATION_FAILED": "Provider rejected the configured credentials.",
    "PERMISSION_DENIED": "Provider denied access to this operation or model.",
    "MODEL_NOT_FOUND": "The requested model was not found or is unavailable to this account.",
    "RATE_LIMITED": "Provider rate limit reached; wait before retrying.",
    "QUOTA_EXHAUSTED": "Provider quota is exhausted; check quota limits or use another provider.",
    "CREDIT_EXHAUSTED": "Provider credit balance is exhausted; add credits or use another configured provider.",
    "PROVIDER_ERROR": "Provider returned an upstream error; inspect the category and retry later.",
    "SUCCESS": "Provider generation succeeded.",
}


def _status_code(error: BaseException) -> int | None:
    for value in (
        getattr(error, "status_code", None),
        getattr(error, "status", None),
        getattr(getattr(error, "response", None), "status_code", None),
    ):
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _error_blob(error: BaseException) -> str:
    """Collect classification hints without ever returning this text to users."""
    values = [str(error), str(getattr(error, "code", ""))]
    # OpenAI-compatible SDKs wrap transport failures (for example an
    # ``httpx.ConnectError``) in ``APIConnectionError``.  Include the
    # exception chain so a blocked connection is not mislabeled as a generic
    # provider failure.  The blob is used only for local classification and
    # is never returned to the caller.
    seen: set[int] = set()
    cause = getattr(error, "__cause__", None)
    context = getattr(error, "__context__", None)
    for nested in (cause, context):
        if nested is not None and id(nested) not in seen:
            seen.add(id(nested))
            values.extend([str(nested), nested.__class__.__name__])
    body = getattr(error, "body", None)
    if body:
        try:
            values.append(json.dumps(body, ensure_ascii=False, sort_keys=True))
        except Exception:
            values.append(str(body))
    response = getattr(error, "response", None)
    if response is not None:
        try:
            values.append(json.dumps(response.json(), ensure_ascii=False, sort_keys=True))
        except Exception:
            pass
    return " ".join(values).lower()


def _has_any(blob: str, *patterns: str) -> bool:
    return any(re.search(pattern, blob, re.IGNORECASE) for pattern in patterns)


def classify_provider_error(error: BaseException) -> tuple[str, str]:
    """Map adapter/network exceptions to a stable category and safe message.

    Classification deliberately uses status/code/message hints only.  The raw
    exception is never returned by this function, so an upstream body cannot
    leak an API key through the diagnostic endpoint.
    """
    status = _status_code(error)
    blob = _error_blob(error)
    error_type = error.__class__.__name__.lower()

    if _has_any(blob, r"not configured", r"api key.{0,20}missing", r"missing.{0,20}api key"):
        return "NOT_CONFIGURED", SAFE_MESSAGES["NOT_CONFIGURED"]

    # Billing/credit signals must win over the generic 4xx/429 branches.
    if _has_any(
        blob,
        r"credit[_ ]balance[_ ]exhausted",
        r"billing[_ ]hard[_ ]limit",
        r"billing.{0,20}(?:limit|credit)",
        r"credit.{0,20}exhaust",
    ):
        return "CREDIT_EXHAUSTED", SAFE_MESSAGES["CREDIT_EXHAUSTED"]

    if _has_any(
        blob,
        r"insufficient[_ ]quota",
        r"quota.{0,20}(?:exhaust|exceeded|depleted)",
        r"resource[_ ]exhausted",
    ):
        return "QUOTA_EXHAUSTED", SAFE_MESSAGES["QUOTA_EXHAUSTED"]

    if status == 401 or _has_any(
        blob,
        r"invalid[_ ]api[_ ]key",
        r"incorrect api key",
        r"unauthori[sz]ed",
        r"authentication(?:_error| error| failed)",
        r"invalid.{0,20}(?:credential|token|key)",
    ):
        return "AUTHENTICATION_FAILED", SAFE_MESSAGES["AUTHENTICATION_FAILED"]

    if status == 403 or _has_any(blob, r"permission[_ ]denied", r"forbidden", r"access denied"):
        return "PERMISSION_DENIED", SAFE_MESSAGES["PERMISSION_DENIED"]

    if status == 404 or _has_any(
        blob,
        r"model[_ ]not[_ ]found",
        r"unknown model",
        r"model.{0,20}(?:does not exist|unavailable|not found)",
    ):
        return "MODEL_NOT_FOUND", SAFE_MESSAGES["MODEL_NOT_FOUND"]

    if status == 429 and not _has_any(blob, r"quota", r"resource[_ ]exhausted"):
        return "RATE_LIMITED", SAFE_MESSAGES["RATE_LIMITED"]
    if _has_any(blob, r"rate[_ ]limit", r"too many requests", r"rate_limit_exceeded"):
        return "RATE_LIMITED", SAFE_MESSAGES["RATE_LIMITED"]

    timeout_type = (
        isinstance(error, (TimeoutError, asyncio.TimeoutError))
        or (httpx is not None and isinstance(error, httpx.TimeoutException))
        or "timeout" in error_type
        or "timed out" in blob
    )
    if timeout_type:
        return "TIMEOUT", SAFE_MESSAGES["TIMEOUT"]

    dns_error = (
        isinstance(error, socket.gaierror)
        or "gaierror" in error_type
        or _has_any(
            blob,
            r"name or service not known",
            r"getaddrinfo failed",
            r"nodename nor servname",
            r"temporary failure in name resolution",
            r"dns",
        )
    )
    if dns_error:
        return "DNS_ERROR", SAFE_MESSAGES["DNS_ERROR"]

    network_blocked = (
        isinstance(error, (PermissionError, ConnectionError, OSError))
        or "connecterror" in error_type
        or "apiconnectionerror" in error_type
        or "network" in blob
        or _has_any(
            blob,
            r"operation not permitted",
            r"connection refused",
            r"connection reset",
            r"all connection attempts failed",
            r"connection error",
            r"proxy.*(?:blocked|denied|error)",
            r"outbound.*blocked",
        )
    )
    if network_blocked:
        return "NETWORK_BLOCKED", SAFE_MESSAGES["NETWORK_BLOCKED"]

    if status is not None and status >= 500:
        return "PROVIDER_ERROR", SAFE_MESSAGES["PROVIDER_ERROR"]
    return "PROVIDER_ERROR", SAFE_MESSAGES["PROVIDER_ERROR"]


def _failure_flags(category: str) -> tuple[bool | None, bool | None, bool | None]:
    """Return network/auth/model flags for a failed probe."""
    if category in {"NETWORK_BLOCKED", "DNS_ERROR"}:
        return False, None, None
    if category == "TIMEOUT":
        return None, None, None
    if category == "AUTHENTICATION_FAILED":
        return True, False, None
    if category in {"PERMISSION_DENIED", "MODEL_NOT_FOUND"}:
        return True, None, False
    if category in {"RATE_LIMITED", "QUOTA_EXHAUSTED", "CREDIT_EXHAUSTED"}:
        return True, True, None
    return True, None, None


def _latency_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


async def run_provider_diagnostic(
    *,
    provider_name: str,
    configured: bool,
    model: str | None,
    provider_factory: Callable[..., Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    """Probe a provider once and return the normalized diagnostic schema."""
    started = time.perf_counter()
    if not configured:
        return ProviderDiagnostic(
            provider=provider_name,
            configured=False,
            network_reachable=None,
            authenticated=None,
            model_access=None,
            generation_ok=False,
            usage_metadata_available=False,
            latency_ms=None,
            error_category="NOT_CONFIGURED",
            safe_message=SAFE_MESSAGES["NOT_CONFIGURED"],
        ).as_dict()

    try:
        provider = provider_factory(provider_name, model=model)
        result = await asyncio.wait_for(
            provider.generate(
                system="Provider connectivity diagnostic. Reply exactly OK.",
                user="Reply exactly OK.",
            ),
            timeout=max(0.1, float(timeout_seconds)),
        )
        if not str(getattr(result, "text", "") or "").strip():
            raise ValueError("Provider returned an empty response")
    except Exception as error:
        category, safe_message = classify_provider_error(error)
        network, authenticated, model_access = _failure_flags(category)
        if category == "NOT_CONFIGURED":
            configured = False
        return ProviderDiagnostic(
            provider=provider_name,
            configured=configured,
            network_reachable=network,
            authenticated=authenticated,
            model_access=model_access,
            generation_ok=False,
            usage_metadata_available=False,
            latency_ms=_latency_ms(started),
            error_category=category,
            safe_message=safe_message,
        ).as_dict()

    usage = getattr(result, "usage", None)
    declared_usage = getattr(result, "usage_metadata_available", None)
    usage_available = (
        bool(declared_usage)
        if declared_usage is not None
        else bool(
            usage is not None
            and (
                getattr(usage, "input_tokens", 0)
                or getattr(usage, "output_tokens", 0)
                or getattr(usage, "total_tokens", 0)
            )
        )
    )
    is_fake = provider_name == "fake"
    return ProviderDiagnostic(
        provider=provider_name,
        configured=True,
        # Fake is intentionally offline; no network claim is made for it.
        network_reachable=None if is_fake else True,
        authenticated=None if is_fake else True,
        model_access=True,
        generation_ok=True,
        usage_metadata_available=usage_available,
        latency_ms=_latency_ms(started),
        error_category="SUCCESS",
        safe_message=SAFE_MESSAGES["SUCCESS"] if not is_fake else "Fake provider generation succeeded locally; network was not required.",
    ).as_dict()


def diagnostic_for_category(
    provider: str,
    configured: bool,
    category: str,
    *,
    latency_ms: int | None = None,
    preflight: bool = False,
) -> dict[str, Any]:
    """Build a deterministic result for validation/model errors before probing."""
    if category not in ERROR_CATEGORIES or category == "SUCCESS":
        raise ValueError("Unsupported diagnostic category")
    network, authenticated, model_access = _failure_flags(category)
    # A locally rejected model selection has not reached the provider yet.
    if preflight:
        network, authenticated = None, None
    return ProviderDiagnostic(
        provider=provider,
        configured=configured,
        network_reachable=network,
        authenticated=authenticated,
        model_access=model_access,
        generation_ok=False,
        usage_metadata_available=False,
        latency_ms=latency_ms,
        error_category=category,
        safe_message=SAFE_MESSAGES[category],
    ).as_dict()
