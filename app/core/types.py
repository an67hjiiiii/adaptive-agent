from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import time, uuid

@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    # Provider-specific token detail is optional.  ``None`` means the
    # provider did not expose that breakdown; it must not be interpreted as
    # a measured zero.
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

@dataclass
class ProviderResult:
    text: str
    usage: Usage = field(default_factory=Usage)
    request_id: str | None = None
    model: str = "unknown"
    # Providers that do not return usage must say so explicitly.  ``None``
    # keeps backwards-compatible test doubles usable while allowing the
    # runtime to infer availability from non-zero legacy usage values.
    usage_metadata_available: bool | None = None

@dataclass
class Budget:
    max_logical_calls: int = 12
    max_physical_requests: int = 18
    max_workers: int = 3
    max_escalations: int = 1
    max_retries_per_call: int = 1
    call_timeout_seconds: float = 45.0
    # Retry backoff is part of the execution contract.  The application-level
    # factory may override these from the environment or a Pilot manifest;
    # direct test doubles retain the historical defaults.
    retry_base_seconds: float = 1.0
    retry_max_seconds: float = 60.0
    logical_calls: int = 0
    physical_requests: int = 0
    escalations: int = 0

    def can_start_logical(self) -> bool:
        return self.logical_calls < self.max_logical_calls

    def start_logical(self):
        if not self.can_start_logical():
            raise RuntimeError("STOP_BUDGET_LOGICAL_CALLS")
        self.logical_calls += 1

    def can_request(self) -> bool:
        return self.physical_requests < self.max_physical_requests

    @property
    def remaining_logical_calls(self) -> int:
        return max(0, self.max_logical_calls - self.logical_calls)

    @property
    def remaining_physical_requests(self) -> int:
        return max(0, self.max_physical_requests - self.physical_requests)

    def record_request(self):
        if not self.can_request():
            raise RuntimeError("STOP_BUDGET_PHYSICAL_REQUESTS")
        self.physical_requests += 1

    def allow_escalation(self, required_calls: int = 3) -> bool:
        return (
            self.escalations < self.max_escalations
            and self.remaining_logical_calls >= required_calls
            and self.remaining_physical_requests >= required_calls
        )

@dataclass
class RunState:
    strategy: str
    provider: str
    model: str
    task: str
    context: str
    chat_history: str = ""
    retrieval_meta: dict[str, Any] = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex[:12]}")
    started_at: float = field(default_factory=time.perf_counter)
    # ``started_at`` is the accepted-run boundary supplied by the caller.  It
    # may be backdated by the shared context-preparation duration so all
    # compared strategies receive the same documented context attribution.
    finished_at: float | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    agent_executions: int = 0
    usage: Usage = field(default_factory=Usage)
    usage_metadata_available: bool | None = None
    answer: str = ""
    status: str = "running"
    stop_reason: str = ""
    error: str = ""
    # Safe versioned research configuration identity. It intentionally holds
    # no prompts, provider credentials, or other secret material.
    config_identity: dict[str, Any] = field(default_factory=dict)
    incident_records: list[dict[str, Any]] = field(default_factory=list)
    outcome_category: str | None = None

    def event(self, kind: str, title: str, detail: str = "", meta: dict | None = None):
        e={"kind":kind,"title":title,"detail":detail,
           "t_ms":round((time.perf_counter()-self.started_at)*1000),
           "meta":meta or {}}
        self.events.append(e); return e

    def record_usage(self, result: ProviderResult):
        usage = result.usage or Usage()
        available = result.usage_metadata_available
        if available is None:
            available = bool(usage.input_tokens or usage.output_tokens or usage.total_tokens)
        if not available:
            # Once one provider response omits usage, an aggregate total cannot
            # be reconstructed safely. Keep the whole run explicitly unknown.
            self.usage_metadata_available = False
            self.usage = Usage()
            return
        if self.usage_metadata_available is False:
            return
        first_measured_response = self.usage_metadata_available is None
        self.usage_metadata_available = True
        self.usage.input_tokens += int(usage.input_tokens or 0)
        self.usage.output_tokens += int(usage.output_tokens or 0)
        if first_measured_response:
            self.usage.cached_input_tokens = (
                int(usage.cached_input_tokens)
                if usage.cached_input_tokens is not None else None
            )
        elif self.usage.cached_input_tokens is None or usage.cached_input_tokens is None:
            self.usage.cached_input_tokens = None
        else:
            self.usage.cached_input_tokens += int(usage.cached_input_tokens or 0)
        if first_measured_response:
            self.usage.reasoning_tokens = (
                int(usage.reasoning_tokens)
                if usage.reasoning_tokens is not None else None
            )
        elif self.usage.reasoning_tokens is None or usage.reasoning_tokens is None:
            self.usage.reasoning_tokens = None
        else:
            self.usage.reasoning_tokens += int(usage.reasoning_tokens or 0)
