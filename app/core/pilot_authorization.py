"""Mechanisms for the Pilot pacing and authorization gate.

This module is deliberately side-effect free with respect to providers.  It
contains the small, machine-readable control records that Integration can use
when it makes the final Pilot decision:

* a conservative Groq pacing policy;
* local (this-experiment) request/token accounting;
* safe handling of optional provider rate-limit headers;
* a fresh, manifest-bound preflight validator;
* owner authorization and live-window record validators.

None of the builders below starts a provider request or executes a Pilot
condition.  Persistence is limited to the optional local accounting ledger,
which contains counters and safe metadata only.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

try:  # pragma: no cover - the standard library supplies this on supported Python
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


# The values are the verified organization tuple recorded in
# ``docs/PILOT_PROVIDER_LIMITS.md``.  They are duplicated here intentionally so
# this gate can be imported without importing the runtime/orchestrator.
GROQ_PROVIDER = "groq"
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_RPM_LIMIT = 30
GROQ_RPD_LIMIT = 1000
GROQ_TPM_LIMIT = 8000
GROQ_TPD_LIMIT = 200000
GROQ_PROJECT_OVERRIDE = "NONE"
GROQ_ITPM_OTPM_STATUS = "SEPARATE_ITPM_OTPM_NOT_VERIFIED"

PILOT_PACING_POLICY_ID = "GROQ-PILOT-PACING-V1"
PILOT_PACING_POLICY_VERSION = "1.0"
PILOT_AUTHORIZATION_SCHEMA_ID = "PILOT-AUTHORIZATION-V1"
PILOT_AUTHORIZATION_SCHEMA_VERSION = "1.0"
PILOT_LIVE_WINDOW_SCHEMA_ID = "PILOT-LIVE-WINDOW-V1"
PILOT_LIVE_WINDOW_SCHEMA_VERSION = "1.0"
PILOT_PREFLIGHT_BINDING_SCHEMA_ID = "PILOT-PREFLIGHT-BINDING-V1"
PILOT_PREFLIGHT_BINDING_SCHEMA_VERSION = "1.0"
PILOT_LOCAL_USAGE_SCHEMA_ID = "PILOT-LOCAL-USAGE-V1"
PILOT_LOCAL_USAGE_SCHEMA_VERSION = "1.0"

AUTHORIZED_PILOT_SCOPE = "AUTHORIZE_PILOT_EXECUTION"
PILOT_OWNER_ROLE = "PROJECT_OWNER"
UNKNOWN_PROVIDER_ACCOUNT_WIDE_REMAINING = "UNKNOWN_PROVIDER_ACCOUNT_WIDE_REMAINING"
UNAVAILABLE = "UNAVAILABLE"
KNOWN_LOCAL_EXPERIMENT_USAGE = "KNOWN_LOCAL_EXPERIMENT_USAGE"
PARTIAL_KNOWN_LOCAL_EXPERIMENT_USAGE = "PARTIAL_KNOWN_LOCAL_EXPERIMENT_USAGE"
DEFAULT_PROJECT_TIMEZONE = "Asia/Saigon"
DEFAULT_LIVE_WINDOW_MAX_DURATION_SECONDS = 4 * 60 * 60
PILOT_PREFLIGHT_MAX_AGE_SECONDS = 15 * 60


# Keep the legacy aliases in the policy because existing Pilot manifests and
# the executor use those names.  The canonical fields are the unambiguous
# ``max_requests_per_minute``, ``max_in_flight`` and ``*_ceiling`` fields.
PILOT_PACING_POLICY: dict[str, Any] = {
    "policy_id": PILOT_PACING_POLICY_ID,
    "version": PILOT_PACING_POLICY_VERSION,
    "provider": GROQ_PROVIDER,
    "model": GROQ_MODEL,
    "max_requests_per_minute": 20,
    "max_in_flight": 3,
    "tpm_ceiling": GROQ_TPM_LIMIT,
    "rpd_ceiling": GROQ_RPD_LIMIT,
    "tpd_ceiling": GROQ_TPD_LIMIT,
    "reserve_policy": {
        "kind": "DAILY_HEADROOM",
        "fraction": 0.10,
        "rpd_reserve_requests": 100,
        "tpd_reserve_tokens": 20000,
        "effective_rpd_ceiling": 900,
        "effective_tpd_ceiling": 180000,
        "basis": (
            "Retain ten percent of the verified daily ceilings for provider "
            "overhead and non-Pilot traffic; these are local safety ceilings, "
            "not provider quota claims."
        ),
    },
    "retry_after_behavior": {
        "honor": True,
        "accepted_forms": ["seconds", "http-date"],
        "missing_header": "FALL_BACK_TO_BOUNDED_EXPONENTIAL_BACKOFF",
        "negative_or_invalid": "IGNORE_AND_USE_FALLBACK",
    },
    "pause_behavior": {
        "local_safe_ceiling": "FAIL_CLOSED",
        "provider_remaining_unavailable": "PAUSE_BEFORE_NEW_BLOCK_OR_OWNER_REVIEW",
        "daily_ceiling": "PAUSE_UNTIL_NEXT_WINDOW_OR_OWNER_REVIEW",
        "rate_limit": "PAUSE_AND_REASSESS_AFTER_RETRY_AFTER",
    },
    "rate_limit_incident_behavior": (
        "RECORD_PROVIDER_INCIDENT_MISSINGNESS_NOT_QUALITY_FAILURE"
    ),
    "header_absence_behavior": "UNAVAILABLE_NOT_ZERO",
    # Compatibility aliases used by PILOT-R4's existing executor/config.
    "max_in_flight_workers": 3,
    "conservative_requests_per_minute_until_header_observation": 20,
    "aggregate_token_ceiling_per_minute": GROQ_TPM_LIMIT,
    "honor_retry_after": True,
    "rate_limit_incident_is_quality_failure": False,
    "enforcement": "AsyncRequestPacer shared by all roles in one executor",
    "request_gate_scope": "provider_account_and_process",
}


RATE_LIMIT_HEADER_NAMES = (
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-tokens",
    "retry-after",
)


class PilotAuthorizationError(ValueError):
    """A fail-closed Pilot control-record or quota validation error."""


class PreflightBindingError(PilotAuthorizationError):
    """A preflight is missing, stale, or does not match the manifest."""


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _aware_datetime(value: Any, *, field: str, timezone_name: str | None = None) -> datetime:
    """Parse a timestamp without silently assigning UTC to owner input."""

    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise PilotAuthorizationError(f"{field} is required")
        try:
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PilotAuthorizationError(f"{field} is not a valid ISO timestamp") from exc
    else:
        raise PilotAuthorizationError(f"{field} is required")
    if result.tzinfo is None or result.utcoffset() is None:
        if timezone_name is None:
            raise PilotAuthorizationError(
                f"{field} must include a timezone offset; UTC is not assumed"
            )
        # A window may be authored as local wall-clock time.  Bind it to the
        # declared project/owner timezone explicitly rather than treating it as
        # UTC.  Preflight/auth timestamps do not pass timezone_name and remain
        # strict.
        result = result.replace(tzinfo=_zone(timezone_name))
    return result


def _zone(timezone_name: str):
    name = _safe_text(timezone_name)
    if not name:
        raise PilotAuthorizationError("timezone is required")
    if ZoneInfo is None:  # pragma: no cover - platform-dependent import
        if name == "Asia/Saigon":
            return timezone(timedelta(hours=7), name="Asia/Saigon")
        raise PilotAuthorizationError("timezone database is unavailable")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        # Some Windows tzdata packages expose the canonical Ho Chi Minh name
        # but not the historical alias used by this project.
        if name == "Asia/Saigon":
            try:
                return ZoneInfo("Asia/Ho_Chi_Minh")
            except ZoneInfoNotFoundError:
                # Vietnam has used UTC+07 without daylight-saving transitions
                # throughout the experiment's date range.  This explicit
                # fallback preserves owner-facing local wall-clock semantics
                # on Windows installations that do not bundle IANA tzdata.
                return timezone(timedelta(hours=7), name="Asia/Saigon")
        raise PilotAuthorizationError(f"Unknown timezone: {name}") from exc


def validate_pacing_policy(policy: Mapping[str, Any] | None = None) -> bool:
    """Validate a conservative policy against the verified Groq ceilings."""

    candidate = policy or PILOT_PACING_POLICY
    required = (
        "policy_id",
        "version",
        "max_requests_per_minute",
        "max_in_flight",
        "tpm_ceiling",
        "rpd_ceiling",
        "tpd_ceiling",
        "reserve_policy",
        "retry_after_behavior",
        "pause_behavior",
        "rate_limit_incident_behavior",
    )
    missing = [key for key in required if key not in candidate]
    if missing:
        raise PilotAuthorizationError("Pacing policy is missing: " + ", ".join(missing))
    if str(candidate.get("policy_id")) != PILOT_PACING_POLICY_ID:
        raise PilotAuthorizationError("Unexpected Pilot pacing policy identity")
    if str(candidate.get("version")) != PILOT_PACING_POLICY_VERSION:
        raise PilotAuthorizationError("Unexpected Pilot pacing policy version")

    def positive_int(key: str) -> int:
        value = candidate.get(key)
        if isinstance(value, bool):
            raise PilotAuthorizationError(f"Pacing {key} must be an integer")
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise PilotAuthorizationError(f"Pacing {key} must be an integer") from exc
        if result < 1:
            raise PilotAuthorizationError(f"Pacing {key} must be positive")
        return result

    rpm = positive_int("max_requests_per_minute")
    in_flight = positive_int("max_in_flight")
    tpm = positive_int("tpm_ceiling")
    rpd = positive_int("rpd_ceiling")
    tpd = positive_int("tpd_ceiling")
    if rpm > 20 or rpm > GROQ_RPM_LIMIT:
        raise PilotAuthorizationError("Pacing RPM exceeds the conservative Groq target")
    if in_flight > 3:
        raise PilotAuthorizationError("Pacing max_in_flight exceeds the frozen safe target")
    if tpm > GROQ_TPM_LIMIT or rpd > GROQ_RPD_LIMIT or tpd > GROQ_TPD_LIMIT:
        raise PilotAuthorizationError("Pacing policy exceeds the verified Groq ceiling")

    reserve = candidate.get("reserve_policy")
    if not isinstance(reserve, Mapping):
        raise PilotAuthorizationError("reserve_policy must be an object")
    reserve_required = (
        "rpd_reserve_requests",
        "tpd_reserve_tokens",
        "effective_rpd_ceiling",
        "effective_tpd_ceiling",
    )
    missing_reserve = [key for key in reserve_required if key not in reserve]
    if missing_reserve:
        raise PilotAuthorizationError(
            "reserve_policy is missing: " + ", ".join(missing_reserve)
        )
    for key in ("rpd_reserve_requests", "tpd_reserve_tokens"):
        value = reserve.get(key)
        if isinstance(value, bool):
            raise PilotAuthorizationError(f"{key} must be numeric")
        try:
            numeric = int(value)
        except (TypeError, ValueError) as exc:
            raise PilotAuthorizationError(f"{key} must be numeric") from exc
        if numeric < 0:
            raise PilotAuthorizationError(f"{key} cannot be negative")
    if int(reserve.get("rpd_reserve_requests", 0)) >= rpd:
        raise PilotAuthorizationError("RPD reserve leaves no usable local ceiling")
    if int(reserve.get("tpd_reserve_tokens", 0)) >= tpd:
        raise PilotAuthorizationError("TPD reserve leaves no usable local ceiling")
    effective_rpd = int(reserve.get("effective_rpd_ceiling", rpd - int(reserve["rpd_reserve_requests"])))
    effective_tpd = int(reserve.get("effective_tpd_ceiling", tpd - int(reserve["tpd_reserve_tokens"])))
    if effective_rpd != rpd - int(reserve["rpd_reserve_requests"]):
        raise PilotAuthorizationError("effective_rpd_ceiling does not match the reserve")
    if effective_tpd != tpd - int(reserve["tpd_reserve_tokens"]):
        raise PilotAuthorizationError("effective_tpd_ceiling does not match the reserve")
    if effective_rpd < 1 or effective_tpd < 1:
        raise PilotAuthorizationError("Daily reserve leaves no usable local ceiling")
    return True


def _header_lookup(headers: Mapping[str, Any] | None, name: str) -> Any:
    if not isinstance(headers, Mapping):
        return None
    wanted = name.lower()
    for key, value in headers.items():
        if str(key).lower() == wanted:
            return value
    return None


def normalize_rate_limit_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    """Return only safe rate-limit headers, marking absent fields UNAVAILABLE."""

    result: dict[str, str] = {}
    for name in RATE_LIMIT_HEADER_NAMES:
        value = _header_lookup(headers, name)
        text = _safe_text(value)
        # Header values are operational hints, not arbitrary provider bodies.
        result[name] = text[:120] if text else UNAVAILABLE
    return result


def provider_remaining_from_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    """Expose observed remaining values without ever converting absence to 0."""

    normalized = normalize_rate_limit_headers(headers)
    requests = normalized["x-ratelimit-remaining-requests"]
    tokens = normalized["x-ratelimit-remaining-tokens"]
    return {
        "requests": requests,
        "tokens": tokens,
        "requests_status": "OBSERVED" if requests != UNAVAILABLE else UNAVAILABLE,
        "tokens_status": "OBSERVED" if tokens != UNAVAILABLE else UNAVAILABLE,
        "source": "PROVIDER_HEADERS" if requests != UNAVAILABLE or tokens != UNAVAILABLE else UNAVAILABLE,
    }


def parse_retry_after(value: Any, *, now: datetime | None = None) -> float | None:
    """Parse a Retry-After seconds value or HTTP-date into a non-negative delay."""

    text = _safe_text(value)
    if not text:
        return None
    try:
        seconds = float(text)
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except (TypeError, ValueError):
        pass
    try:
        target = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None or reference.utcoffset() is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return max(0.0, (target - reference).total_seconds())


def retry_after_seconds(
    headers: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    fallback_seconds: float | None = None,
) -> float | None:
    """Read Retry-After and optionally return the caller's bounded fallback."""

    parsed = parse_retry_after(_header_lookup(headers, "retry-after"), now=now)
    if parsed is not None:
        return parsed
    if fallback_seconds is None:
        return None
    try:
        fallback = float(fallback_seconds)
    except (TypeError, ValueError):
        return None
    return max(0.0, fallback) if math.isfinite(fallback) else None


def retry_after_decision(
    headers: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    fallback_seconds: float | None = None,
) -> dict[str, Any]:
    """Return a safe, machine-readable Retry-After decision."""

    raw = _header_lookup(headers, "retry-after")
    parsed = parse_retry_after(raw, now=now)
    if parsed is not None:
        return {"seconds": parsed, "source": "RETRY_AFTER_HEADER", "honored": True}
    if fallback_seconds is not None:
        value = retry_after_seconds({}, fallback_seconds=fallback_seconds)
        return {"seconds": value, "source": "BOUNDED_FALLBACK", "honored": False}
    return {"seconds": None, "source": UNAVAILABLE, "honored": False}


def _effective_daily_limits(policy: Mapping[str, Any]) -> tuple[int, int]:
    reserve = policy["reserve_policy"]
    return (
        int(reserve["effective_rpd_ceiling"]),
        int(reserve["effective_tpd_ceiling"]),
    )


class LocalPilotUsageLedger:
    """Persistent counters for *this* Pilot execution only.

    Provider-wide remaining quota is intentionally never inferred from these
    counters.  If a response has no token usage, the request remains counted
    and ``unknown_token_observations`` records that the local token total is
    incomplete; no zero is substituted.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        policy: Mapping[str, Any] | None = None,
        timezone_name: str = DEFAULT_PROJECT_TIMEZONE,
        window_id: str = "UNBOUND",
        now: datetime | None = None,
    ):
        self.path = Path(path) if path is not None else None
        self.policy = deepcopy(dict(policy or PILOT_PACING_POLICY))
        validate_pacing_policy(self.policy)
        self.timezone_name = _safe_text(timezone_name) or DEFAULT_PROJECT_TIMEZONE
        self._timezone = _zone(self.timezone_name)
        self.window_id = _safe_text(window_id) or "UNBOUND"
        self._entries: list[dict[str, Any]] = []
        self._current_key: tuple[str, str] | None = None
        self._load()
        self._select(now=now)

    def _local_now(self, now: datetime | None = None) -> datetime:
        if now is None:
            return datetime.now(self._timezone)
        value = _aware_datetime(now, field="now", timezone_name=self.timezone_name)
        return value.astimezone(self._timezone)

    def _entry_key(self, now: datetime) -> tuple[str, str]:
        return now.date().isoformat(), self.window_id

    def _new_entry(self, now: datetime) -> dict[str, Any]:
        return {
            "date": now.date().isoformat(),
            "window_id": self.window_id,
            "requests_consumed": 0,
            "tokens_consumed": 0,
            "unknown_token_observations": 0,
            "provider_rate_limit_headers": normalize_rate_limit_headers(None),
            "request_observations": [],
        }

    def _select(self, *, now: datetime | None = None) -> None:
        local = self._local_now(now)
        key = self._entry_key(local)
        self._current_key = key
        for entry in self._entries:
            if (str(entry.get("date")), str(entry.get("window_id"))) == key:
                return
        self._entries.append(self._new_entry(local))

    @property
    def _entry(self) -> dict[str, Any]:
        if self._current_key is None:
            self._select()
        assert self._current_key is not None
        for entry in self._entries:
            if (str(entry.get("date")), str(entry.get("window_id"))) == self._current_key:
                return entry
        # Defensive recovery if a caller modified the in-memory list.
        local = self._local_now()
        entry = self._new_entry(local)
        self._entries.append(entry)
        self._current_key = self._entry_key(local)
        return entry

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise PilotAuthorizationError("Local Pilot usage ledger is unreadable") from exc
        if not isinstance(payload, Mapping):
            raise PilotAuthorizationError("Local Pilot usage ledger must be an object")
        if payload.get("schema_id") not in {None, PILOT_LOCAL_USAGE_SCHEMA_ID}:
            raise PilotAuthorizationError("Unexpected local Pilot usage schema")
        entries = payload.get("entries")
        if entries is None and payload.get("date") is not None:
            entries = [payload]
        if not isinstance(entries, list):
            raise PilotAuthorizationError("Local Pilot usage ledger entries are missing")
        for item in entries:
            if not isinstance(item, Mapping):
                raise PilotAuthorizationError("Local Pilot usage entry is not an object")
            if not _safe_text(item.get("date")) or not _safe_text(item.get("window_id")):
                raise PilotAuthorizationError("Local Pilot usage entry lacks date/window")
            self._entries.append({
                "date": str(item["date"]),
                "window_id": str(item["window_id"]),
                "requests_consumed": max(0, int(item.get("requests_consumed", 0))),
                "tokens_consumed": max(0, int(item.get("tokens_consumed", 0))),
                "unknown_token_observations": max(0, int(item.get("unknown_token_observations", 0))),
                "provider_rate_limit_headers": normalize_rate_limit_headers(
                    item.get("provider_rate_limit_headers")
                ),
                "request_observations": [
                    {
                        "request_record_id": _safe_text(observation.get("request_record_id")),
                        "timestamp": _safe_text(observation.get("timestamp")),
                        "unit_id": _safe_text(observation.get("unit_id")),
                        "attempt_id": _safe_text(observation.get("attempt_id")),
                        "condition_id": _safe_text(observation.get("condition_id")),
                        "tokens": (
                            max(0, int(observation.get("tokens")))
                            if observation.get("tokens") is not None
                            else None
                        ),
                    }
                    for observation in (item.get("request_observations") or [])
                    if isinstance(observation, Mapping)
                ],
            })

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_id": PILOT_LOCAL_USAGE_SCHEMA_ID,
            "schema_version": PILOT_LOCAL_USAGE_SCHEMA_VERSION,
            "provider": GROQ_PROVIDER,
            "model": GROQ_MODEL,
            "timezone": self.timezone_name,
            "source": KNOWN_LOCAL_EXPERIMENT_USAGE,
            "provider_remaining_requests": UNKNOWN_PROVIDER_ACCOUNT_WIDE_REMAINING,
            "provider_remaining_tokens": UNKNOWN_PROVIDER_ACCOUNT_WIDE_REMAINING,
            "entries": deepcopy(self._entries),
        }
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    @staticmethod
    def _nonnegative_int(value: Any, *, field: str) -> int:
        if isinstance(value, bool):
            raise PilotAuthorizationError(f"{field} must be a non-negative integer")
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise PilotAuthorizationError(f"{field} must be a non-negative integer") from exc
        if result < 0:
            raise PilotAuthorizationError(f"{field} must be a non-negative integer")
        return result

    def _limits(self) -> tuple[int, int]:
        return _effective_daily_limits(self.policy)

    def guard_before_request(
        self,
        *,
        requests: int = 1,
        estimated_tokens: int | None = None,
        tokens: int | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Fail closed when known local usage would exceed safe daily limits.

        ``estimated_tokens`` and ``tokens`` are synonyms for callers that have
        a bounded request estimate.  If no estimate is available, only the
        known local request guard is evaluated; the subsequent record retains
        an explicit unknown-token count rather than fabricating zero.
        """

        self._select(now=now)
        request_count = self._nonnegative_int(requests, field="requests")
        token_value = tokens if estimated_tokens is None else estimated_tokens
        if token_value is not None:
            token_value = self._nonnegative_int(token_value, field="estimated_tokens")
        rpd_ceiling, tpd_ceiling = self._limits()
        entry = self._entry
        if int(entry["requests_consumed"]) + request_count > rpd_ceiling:
            raise PilotAuthorizationError(
                "LOCAL_RPD_GUARD: known local Pilot requests exceed the safe ceiling"
            )
        if token_value is not None and int(entry["tokens_consumed"]) + token_value > tpd_ceiling:
            raise PilotAuthorizationError(
                "LOCAL_TPD_GUARD: known local Pilot tokens exceed the safe ceiling"
            )
        return True

    # Readable aliases for integration callers and tests.
    guard = guard_before_request

    def can_issue(
        self,
        *,
        requests: int = 1,
        estimated_tokens: int | None = None,
        tokens: int | None = None,
        now: datetime | None = None,
    ) -> bool:
        try:
            self.guard_before_request(
                requests=requests,
                estimated_tokens=estimated_tokens,
                tokens=tokens,
                now=now,
            )
        except PilotAuthorizationError:
            return False
        return True

    def record(
        self,
        *,
        requests: int = 1,
        tokens: int | None = None,
        provider_headers: Mapping[str, Any] | None = None,
        now: datetime | None = None,
        unit_id: str | None = None,
        attempt_id: str | None = None,
        condition_id: str | None = None,
    ) -> dict[str, Any]:
        """Record local consumption; ``tokens=None`` remains explicitly unknown."""

        self._select(now=now)
        request_count = self._nonnegative_int(requests, field="requests")
        token_value = None if tokens is None else self._nonnegative_int(tokens, field="tokens")
        self.guard_before_request(
            requests=request_count,
            estimated_tokens=token_value,
            now=now,
        )
        entry = self._entry
        entry["requests_consumed"] = int(entry["requests_consumed"]) + request_count
        if token_value is None:
            entry["unknown_token_observations"] = int(entry["unknown_token_observations"]) + request_count
        else:
            entry["tokens_consumed"] = int(entry["tokens_consumed"]) + token_value
        observations = entry.setdefault("request_observations", [])
        local_now = self._local_now(now)
        for _index in range(request_count):
            observations.append({
                "request_record_id": f"{entry['date']}:{entry['window_id']}:{len(observations) + 1}",
                "timestamp": local_now.isoformat(),
                "unit_id": _safe_text(unit_id),
                "attempt_id": _safe_text(attempt_id),
                "condition_id": _safe_text(condition_id),
                "tokens": token_value,
            })
        if provider_headers is not None:
            entry["provider_rate_limit_headers"] = normalize_rate_limit_headers(provider_headers)
        self._persist()
        return self.snapshot(now=now)

    record_request = record

    def record_token_observation(
        self,
        tokens: int,
        *,
        now: datetime | None = None,
        unit_id: str | None = None,
        attempt_id: str | None = None,
        condition_id: str | None = None,
    ) -> dict[str, Any]:
        """Attach a known token count to a prior unknown observation."""

        self._select(now=now)
        value = self._nonnegative_int(tokens, field="tokens")
        entry = self._entry
        unknown = int(entry["unknown_token_observations"])
        if unknown > 0:
            entry["unknown_token_observations"] = unknown - 1
        # Adding an observation cannot make an already-accounted request appear
        # twice; it only completes its token measurement.
        _rpd, tpd = self._limits()
        if int(entry["tokens_consumed"]) + value > tpd:
            raise PilotAuthorizationError(
                "LOCAL_TPD_GUARD: observed local Pilot tokens exceed the safe ceiling"
            )
        entry["tokens_consumed"] = int(entry["tokens_consumed"]) + value
        expected = {
            "unit_id": _safe_text(unit_id),
            "attempt_id": _safe_text(attempt_id),
            "condition_id": _safe_text(condition_id),
        }
        for observation in entry.get("request_observations") or []:
            if observation.get("tokens") is not None:
                continue
            if any(expected[key] and observation.get(key) != expected[key] for key in expected):
                continue
            observation["tokens"] = value
            break
        self._persist()
        return self.snapshot(now=now)

    def set_provider_headers(self, headers: Mapping[str, Any] | None) -> dict[str, Any]:
        self._entry["provider_rate_limit_headers"] = normalize_rate_limit_headers(headers)
        self._persist()
        return self.snapshot()

    def snapshot(
        self,
        *,
        provider_headers: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self._select(now=now)
        entry = self._entry
        if provider_headers is not None:
            observed_headers = normalize_rate_limit_headers(provider_headers)
        else:
            observed_headers = normalize_rate_limit_headers(entry.get("provider_rate_limit_headers"))
        rpd_ceiling, tpd_ceiling = self._limits()
        unknown = int(entry.get("unknown_token_observations", 0))
        tokens_status = (
            KNOWN_LOCAL_EXPERIMENT_USAGE
            if unknown == 0
            else PARTIAL_KNOWN_LOCAL_EXPERIMENT_USAGE
        )
        return {
            "schema_id": PILOT_LOCAL_USAGE_SCHEMA_ID,
            "schema_version": PILOT_LOCAL_USAGE_SCHEMA_VERSION,
            "provider": GROQ_PROVIDER,
            "model": GROQ_MODEL,
            "date": str(entry["date"]),
            "window_id": str(entry["window_id"]),
            "source": KNOWN_LOCAL_EXPERIMENT_USAGE,
            "requests_consumed": int(entry["requests_consumed"]),
            "tokens_consumed": int(entry["tokens_consumed"]),
            "tokens_status": tokens_status,
            "unknown_token_observations": unknown,
            "rpd_guard_ceiling": rpd_ceiling,
            "tpd_guard_ceiling": tpd_ceiling,
            "rpd_remaining_local": max(0, rpd_ceiling - int(entry["requests_consumed"])),
            "tpd_remaining_local": (
                max(0, tpd_ceiling - int(entry["tokens_consumed"]))
                if unknown == 0
                else UNAVAILABLE
            ),
            "provider_remaining_requests": UNKNOWN_PROVIDER_ACCOUNT_WIDE_REMAINING,
            "provider_remaining_tokens": UNKNOWN_PROVIDER_ACCOUNT_WIDE_REMAINING,
            "rate_limit_headers": observed_headers,
            "provider_remaining_from_headers": provider_remaining_from_headers(observed_headers),
            "request_observations": deepcopy(entry.get("request_observations") or []),
        }

    def remaining(self) -> dict[str, Any]:
        return self.snapshot()


def can_issue(
    ledger: LocalPilotUsageLedger,
    *,
    requests: int = 1,
    estimated_tokens: int | None = None,
    tokens: int | None = None,
    now: datetime | None = None,
) -> bool:
    """Module-level convenience wrapper for a local guard check."""

    if not isinstance(ledger, LocalPilotUsageLedger):
        raise PilotAuthorizationError("can_issue requires a LocalPilotUsageLedger")
    return ledger.can_issue(
        requests=requests,
        estimated_tokens=estimated_tokens,
        tokens=tokens,
        now=now,
    )


def _timestamp_for_record(value: str | datetime | None, *, field: str = "timestamp") -> str:
    dt = _aware_datetime(value or datetime.now(timezone.utc), field=field)
    return dt.isoformat().replace("+00:00", "Z")


def build_preflight_binding(
    *,
    preflight_id: str,
    manifest_id: str,
    provider: str,
    model: str,
    model_settings_identity: str,
    freeze_identity: str,
    checked_at: str | datetime,
    phase: str = "PREFLIGHT",
    success: bool = True,
    config_identity: str | None = None,
) -> dict[str, Any]:
    """Build one manifest-bound preflight record without invoking a provider."""

    for field, value in (
        ("preflight_id", preflight_id),
        ("manifest_id", manifest_id),
        ("provider", provider),
        ("model", model),
        ("model_settings_identity", model_settings_identity),
        ("freeze_identity", freeze_identity),
    ):
        if not _safe_text(value):
            raise PreflightBindingError(f"{field} is required")
    normalized_phase = str(phase).upper()
    if normalized_phase != "PREFLIGHT":
        raise PreflightBindingError("preflight binding phase must be PREFLIGHT")
    if not isinstance(success, bool):
        raise PreflightBindingError("preflight success must be boolean")
    timestamp = _timestamp_for_record(checked_at, field="checked_at")
    result = "PASS" if success else "FAIL"
    binding_id = f"pfb_{_fingerprint({'preflight_id': str(preflight_id), 'manifest_id': str(manifest_id), 'checked_at': timestamp})[:12]}"
    record: dict[str, Any] = {
        "binding_id": binding_id,
        "binding_schema_id": PILOT_PREFLIGHT_BINDING_SCHEMA_ID,
        "binding_schema_version": PILOT_PREFLIGHT_BINDING_SCHEMA_VERSION,
        "preflight_id": str(preflight_id),
        "manifest_id": str(manifest_id),
        "provider": str(provider).lower(),
        "model": str(model),
        "model_settings_identity": str(model_settings_identity),
        "settings_identity": str(model_settings_identity),
        "freeze_identity": str(freeze_identity),
        "config_identity": _safe_text(config_identity),
        "phase": normalized_phase,
        "success": success,
        "result": result,
        "status": result,
        "checked_at": timestamp,
        "timestamp": timestamp,
    }
    return record


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    import hashlib
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_preflight_binding(
    binding: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any] | None = None,
    provider: str | None = None,
    model: str | None = None,
    model_settings_identity: str | None = None,
    freeze_identity: str | None = None,
    now: str | datetime | None = None,
    max_age_seconds: float = PILOT_PREFLIGHT_MAX_AGE_SECONDS,
) -> bool:
    """Fail closed unless exactly one successful, fresh binding matches."""

    if not isinstance(binding, Mapping):
        raise PreflightBindingError("preflight binding must be an object")
    for key in ("preflight_id", "manifest_id", "provider", "model", "freeze_identity"):
        if not _safe_text(binding.get(key)):
            raise PreflightBindingError(f"preflight binding lacks {key}")
    binding_settings = _safe_text(binding.get("model_settings_identity") or binding.get("settings_identity"))
    if not binding_settings:
        raise PreflightBindingError("preflight binding lacks model settings identity")
    if str(binding.get("phase") or "").upper() != "PREFLIGHT":
        raise PreflightBindingError("preflight binding phase is not PREFLIGHT")
    if binding.get("success") is not True or str(binding.get("result") or "").upper() not in {"PASS", "SUCCESS"}:
        raise PreflightBindingError("preflight binding is not a successful preflight")
    status = str(binding.get("status") or "PASS").upper()
    if status not in {"PASS", "SUCCESS", "VALID", "OK"}:
        raise PreflightBindingError("preflight binding status is not successful")

    expected = {
        "manifest_id": _safe_text(manifest.get("manifest_id")) if manifest else None,
        "provider": _safe_text(manifest.get("provider")) if manifest else None,
        "model": _safe_text(manifest.get("model")) if manifest else None,
        "model_settings_identity": _safe_text(manifest.get("model_settings_identity")) if manifest else None,
        "freeze_identity": _safe_text(manifest.get("freeze_identity")) if manifest else None,
    }
    expected.update({
        key: _safe_text(value)
        for key, value in {
            "provider": provider,
            "model": model,
            "model_settings_identity": model_settings_identity,
            "freeze_identity": freeze_identity,
        }.items()
        if value is not None
    })
    for key, value in expected.items():
        if value is None:
            continue
        actual_key = "model_settings_identity" if key == "model_settings_identity" else key
        actual = _safe_text(binding.get(actual_key))
        if key == "provider":
            actual = actual.lower() if actual else actual
            value = value.lower()
        if actual != value:
            label = "SETTINGS" if key == "model_settings_identity" else key.upper()
            raise PreflightBindingError(f"PILOT_PREFLIGHT_{label}_MISMATCH")
    checked_at = binding.get("checked_at") or binding.get("timestamp")
    try:
        checked = _aware_datetime(checked_at, field="checked_at")
        reference = _aware_datetime(now or datetime.now(timezone.utc), field="now")
    except PilotAuthorizationError as exc:
        raise PreflightBindingError(str(exc)) from exc
    try:
        age = (reference - checked).total_seconds()
        maximum = float(max_age_seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PreflightBindingError("preflight freshness window is invalid") from exc
    if not math.isfinite(maximum) or maximum < 0 or age < -60 or age > maximum:
        raise PreflightBindingError(
            "FRESH_PILOT_PREFLIGHT_REQUIRED: diagnostic is missing, stale, or outside the acceptance window"
        )
    return True


def validate_exactly_one_preflight(
    bindings: Iterable[Mapping[str, Any]],
    **kwargs: Any,
) -> bool:
    """Require one (and only one) successful fresh preflight binding."""

    items = list(bindings)
    if len(items) != 1:
        raise PreflightBindingError("exactly one successful fresh preflight binding is required")
    return validate_preflight_binding(items[0], **kwargs)


def safe_preflight_metadata(preflight: Mapping[str, Any]) -> dict[str, Any]:
    """Copy an allowlist of diagnostic metadata; never copy secrets/bodies."""

    if not isinstance(preflight, Mapping):
        raise PreflightBindingError("preflight metadata must be an object")
    result: dict[str, Any] = {}
    string_fields = (
        "binding_id",
        "binding_schema_id",
        "binding_schema_version",
        "preflight_id",
        "manifest_id",
        "provider",
        "model",
        "model_settings_identity",
        "settings_identity",
        "freeze_identity",
        "config_identity",
        "phase",
        "result",
        "status",
        "checked_at",
        "timestamp",
    )
    boolean_fields = (
        "success",
        "network_reachable",
        "authenticated",
        "model_access",
        "generation_ok",
        "usage_metadata_available",
    )
    numeric_fields = ("latency_ms", "status_code")
    for key in string_fields:
        value = _safe_text(preflight.get(key))
        if value is not None:
            result[key] = value[:240]
    for key in boolean_fields:
        if isinstance(preflight.get(key), bool):
            result[key] = preflight[key]
    for key in numeric_fields:
        value = preflight.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            result[key] = value
    usage_fields = preflight.get("usage_fields") or preflight.get("usage_field_names")
    if isinstance(usage_fields, (list, tuple)):
        result["usage_fields"] = [str(item)[:120] for item in usage_fields[:100] if _safe_text(item)]
    headers = preflight.get("rate_limit_headers") or preflight.get("safe_rate_limit_headers")
    result["rate_limit_headers"] = normalize_rate_limit_headers(headers)
    result["secrets"] = "excluded by design"
    return result


# Alias used by callers that describe the operation as sanitization.
sanitize_preflight_metadata = safe_preflight_metadata


_AUTHORIZATION_STATUSES = {"PENDING", "AUTHORIZED", "REVOKED", "EXPIRED"}
_LIVE_WINDOW_STATUSES = {"SCHEDULED", "ACTIVE", "EXPIRED", "CANCELLED"}


def build_authorization_record(
    *,
    authorization_id: str,
    manifest_id: str,
    freeze_candidate_id: str,
    preflight_id: str,
    window_id: str,
    timestamp: str | datetime | None = None,
    status: str = "PENDING",
    role: str = PILOT_OWNER_ROLE,
    authorized_scope: str = AUTHORIZED_PILOT_SCOPE,
) -> dict[str, Any]:
    """Create a pure owner-authorization record; it performs no execution."""

    fields = {
        "authorization_id": authorization_id,
        "manifest_id": manifest_id,
        "freeze_candidate_id": freeze_candidate_id,
        "preflight_id": preflight_id,
        "window_id": window_id,
    }
    for field, value in fields.items():
        if not _safe_text(value):
            raise PilotAuthorizationError(f"{field} is required")
    if str(role) != PILOT_OWNER_ROLE:
        raise PilotAuthorizationError("owner role must be PROJECT_OWNER")
    if str(authorized_scope) != AUTHORIZED_PILOT_SCOPE:
        raise PilotAuthorizationError("authorization scope must be AUTHORIZE_PILOT_EXECUTION")
    normalized_status = str(status).upper()
    if normalized_status not in _AUTHORIZATION_STATUSES:
        raise PilotAuthorizationError("unsupported owner authorization status")
    record = {
        "schema_id": PILOT_AUTHORIZATION_SCHEMA_ID,
        "schema_version": PILOT_AUTHORIZATION_SCHEMA_VERSION,
        "authorization_id": str(authorization_id),
        "role": PILOT_OWNER_ROLE,
        "authorized_scope": AUTHORIZED_PILOT_SCOPE,
        "manifest_id": str(manifest_id),
        "freeze_candidate_id": str(freeze_candidate_id),
        # This spelling mirrors the task language while the canonical machine
        # field above remains easy to consume in Python/JSON tooling.
        "freeze/candidate_id": str(freeze_candidate_id),
        "preflight_id": str(preflight_id),
        "window_id": str(window_id),
        "timestamp": _timestamp_for_record(timestamp, field="timestamp"),
        "status": normalized_status,
    }
    return record


create_authorization_record = build_authorization_record


def validate_authorization_record(
    record: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any] | None = None,
    preflight_binding: Mapping[str, Any] | None = None,
    live_window: Mapping[str, Any] | None = None,
    now: str | datetime | None = None,
) -> bool:
    """Validate references and shape only; never call the Pilot executor."""

    if not isinstance(record, Mapping):
        raise PilotAuthorizationError("authorization record must be an object")
    required = (
        "authorization_id",
        "role",
        "authorized_scope",
        "manifest_id",
        "preflight_id",
        "window_id",
        "timestamp",
        "status",
    )
    for key in required:
        if not _safe_text(record.get(key)):
            raise PilotAuthorizationError(f"authorization record lacks {key}")
    freeze_value = _safe_text(record.get("freeze_candidate_id") or record.get("freeze/candidate_id"))
    if not freeze_value:
        raise PilotAuthorizationError("authorization record lacks freeze_candidate_id")
    if str(record.get("role")) != PILOT_OWNER_ROLE:
        raise PilotAuthorizationError("authorization role must be PROJECT_OWNER")
    if str(record.get("authorized_scope")) != AUTHORIZED_PILOT_SCOPE:
        raise PilotAuthorizationError("authorization scope must be AUTHORIZE_PILOT_EXECUTION")
    if str(record.get("status")).upper() not in _AUTHORIZATION_STATUSES:
        raise PilotAuthorizationError("unsupported owner authorization status")
    try:
        _aware_datetime(record.get("timestamp"), field="timestamp")
    except PilotAuthorizationError as exc:
        raise PilotAuthorizationError(str(exc)) from exc

    if manifest is not None:
        for key in ("manifest_id",):
            if _safe_text(manifest.get(key)) != _safe_text(record.get(key)):
                raise PilotAuthorizationError(f"authorization {key} mismatch")
        expected_freeze = _safe_text(manifest.get("freeze_identity"))
        if expected_freeze and expected_freeze != freeze_value:
            raise PilotAuthorizationError("authorization freeze/candidate mismatch")
    if preflight_binding is not None:
        if _safe_text(preflight_binding.get("preflight_id")) != _safe_text(record.get("preflight_id")):
            raise PilotAuthorizationError("authorization preflight mismatch")
    if live_window is not None:
        if _safe_text(live_window.get("window_id")) != _safe_text(record.get("window_id")):
            raise PilotAuthorizationError("authorization live window mismatch")
        validate_live_window(live_window, now=now, require_future=False)
    return True


def _duration_seconds(value: Any) -> int:
    if isinstance(value, timedelta):
        seconds = value.total_seconds()
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
    elif isinstance(value, str):
        text = value.strip().upper()
        # Small ISO-8601 duration parser (hours/minutes/seconds are sufficient
        # for a four-hour Pilot window and avoid another dependency).
        match = re.fullmatch(
            r"PT(?:(?P<h>[0-9]+(?:\.[0-9]+)?)H)?(?:(?P<m>[0-9]+(?:\.[0-9]+)?)M)?(?:(?P<s>[0-9]+(?:\.[0-9]+)?)S)?",
            text,
        )
        if not match or not any(match.group(name) for name in ("h", "m", "s")):
            raise PilotAuthorizationError("max_duration must be seconds or an ISO-8601 duration")
        seconds = float(match.group("h") or 0) * 3600 + float(match.group("m") or 0) * 60 + float(match.group("s") or 0)
    else:
        raise PilotAuthorizationError("max_duration must be seconds or an ISO-8601 duration")
    if not math.isfinite(float(seconds)) or seconds <= 0:
        raise PilotAuthorizationError("max_duration must be positive")
    return int(math.ceil(float(seconds)))


def build_live_window(
    window_id: str,
    not_before: str | datetime,
    not_after: str | datetime,
    *,
    timezone_name: str = DEFAULT_PROJECT_TIMEZONE,
    timezone: str | None = None,
    max_duration: int | float | str | timedelta = DEFAULT_LIVE_WINDOW_MAX_DURATION_SECONDS,
    authorization_scope: str = AUTHORIZED_PILOT_SCOPE,
    status: str = "SCHEDULED",
    manifest_id: str | None = None,
    freeze_candidate_id: str | None = None,
    authorization_id: str | None = None,
) -> dict[str, Any]:
    """Build an explicitly scheduled window; no expiring default times are used."""

    zone_name = _safe_text(timezone) or _safe_text(timezone_name) or DEFAULT_PROJECT_TIMEZONE
    _zone(zone_name)
    if not _safe_text(window_id):
        raise PilotAuthorizationError("window_id is required")
    if authorization_scope != AUTHORIZED_PILOT_SCOPE:
        raise PilotAuthorizationError("live window authorization scope is invalid")
    normalized_status = str(status).upper()
    if normalized_status not in _LIVE_WINDOW_STATUSES:
        raise PilotAuthorizationError("unsupported live window status")
    before = _aware_datetime(not_before, field="not_before", timezone_name=zone_name)
    after = _aware_datetime(not_after, field="not_after", timezone_name=zone_name)
    duration = (after - before).total_seconds()
    maximum = _duration_seconds(max_duration)
    if duration <= 0:
        raise PilotAuthorizationError("not_after must be after not_before")
    if duration > maximum:
        raise PilotAuthorizationError("live window exceeds max_duration")
    result = {
        "schema_id": PILOT_LIVE_WINDOW_SCHEMA_ID,
        "schema_version": PILOT_LIVE_WINDOW_SCHEMA_VERSION,
        "window_id": str(window_id),
        "timezone": zone_name,
        "not_before": before.isoformat(),
        "not_after": after.isoformat(),
        "max_duration": maximum,
        "authorization_scope": AUTHORIZED_PILOT_SCOPE,
        "status": normalized_status,
    }
    if manifest_id is not None:
        result["manifest_id"] = _safe_text(manifest_id)
    if freeze_candidate_id is not None:
        result["freeze_candidate_id"] = _safe_text(freeze_candidate_id)
        result["freeze/candidate_id"] = _safe_text(freeze_candidate_id)
    if authorization_id is not None:
        result["authorization_id"] = _safe_text(authorization_id)
    return result


create_live_window = build_live_window


def validate_live_window(
    window: Mapping[str, Any],
    *,
    now: str | datetime | None = None,
    require_future: bool = True,
) -> bool:
    """Validate an actual future owner window without assuming UTC."""

    if not isinstance(window, Mapping):
        raise PilotAuthorizationError("live window must be an object")
    required = (
        "window_id",
        "timezone",
        "not_before",
        "not_after",
        "max_duration",
        "authorization_scope",
        "status",
    )
    for key in required:
        if window.get(key) is None or (isinstance(window.get(key), str) and not window.get(key).strip()):
            raise PilotAuthorizationError(f"live window lacks {key}")
    zone_name = _safe_text(window.get("timezone"))
    _zone(zone_name)
    if str(window.get("authorization_scope")) != AUTHORIZED_PILOT_SCOPE:
        raise PilotAuthorizationError("live window authorization scope is invalid")
    if str(window.get("status")).upper() not in _LIVE_WINDOW_STATUSES:
        raise PilotAuthorizationError("unsupported live window status")
    # Validation intentionally rejects naive serialized timestamps: a caller
    # must preserve the explicit zone/offset that was bound at creation time.
    before = _aware_datetime(window.get("not_before"), field="not_before")
    after = _aware_datetime(window.get("not_after"), field="not_after")
    maximum = _duration_seconds(window.get("max_duration"))
    duration = (after - before).total_seconds()
    if duration <= 0:
        raise PilotAuthorizationError("not_after must be after not_before")
    if duration > maximum:
        raise PilotAuthorizationError("live window exceeds max_duration")
    if require_future:
        reference = _aware_datetime(now or datetime.now(_zone(zone_name)), field="now", timezone_name=zone_name)
        if after <= reference:
            raise PilotAuthorizationError("live window has already expired")
        if str(window.get("status")).upper() in {"SCHEDULED", "ACTIVE"} and before < reference - timedelta(seconds=60):
            raise PilotAuthorizationError("live window not_before is in the past")
    return True


__all__ = [
    "AUTHORIZED_PILOT_SCOPE",
    "DEFAULT_LIVE_WINDOW_MAX_DURATION_SECONDS",
    "DEFAULT_PROJECT_TIMEZONE",
    "GROQ_ITPM_OTPM_STATUS",
    "GROQ_MODEL",
    "GROQ_PROJECT_OVERRIDE",
    "GROQ_PROVIDER",
    "GROQ_RPD_LIMIT",
    "GROQ_RPM_LIMIT",
    "GROQ_TPD_LIMIT",
    "GROQ_TPM_LIMIT",
    "KNOWN_LOCAL_EXPERIMENT_USAGE",
    "LocalPilotUsageLedger",
    "PARTIAL_KNOWN_LOCAL_EXPERIMENT_USAGE",
    "PILOT_AUTHORIZATION_SCHEMA_ID",
    "PILOT_AUTHORIZATION_SCHEMA_VERSION",
    "PILOT_LIVE_WINDOW_SCHEMA_ID",
    "PILOT_LIVE_WINDOW_SCHEMA_VERSION",
    "PILOT_LOCAL_USAGE_SCHEMA_ID",
    "PILOT_LOCAL_USAGE_SCHEMA_VERSION",
    "PILOT_OWNER_ROLE",
    "PILOT_PACING_POLICY",
    "PILOT_PACING_POLICY_ID",
    "PILOT_PACING_POLICY_VERSION",
    "PILOT_PREFLIGHT_BINDING_SCHEMA_ID",
    "PILOT_PREFLIGHT_BINDING_SCHEMA_VERSION",
    "PILOT_PREFLIGHT_MAX_AGE_SECONDS",
    "PilotAuthorizationError",
    "PreflightBindingError",
    "UNAVAILABLE",
    "UNKNOWN_PROVIDER_ACCOUNT_WIDE_REMAINING",
    "build_authorization_record",
    "build_live_window",
    "build_preflight_binding",
    "can_issue",
    "create_authorization_record",
    "create_live_window",
    "normalize_rate_limit_headers",
    "parse_retry_after",
    "provider_remaining_from_headers",
    "retry_after_decision",
    "retry_after_seconds",
    "safe_preflight_metadata",
    "sanitize_preflight_metadata",
    "validate_authorization_record",
    "validate_exactly_one_preflight",
    "validate_live_window",
    "validate_pacing_policy",
    "validate_preflight_binding",
]
