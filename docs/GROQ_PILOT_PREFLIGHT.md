# Groq Pilot preflight — MODEL-PILOT-V1

**Historical capture:** 2026-08-30T17:31:42Z (superseded by the latest integration probe below)

**Purpose:** one minimal live request outside the Pilot sample to verify the
network path, credentials, model access, generation, usage metadata and the
frozen request settings. This is readiness evidence, not a Pilot observation.

## Current integration PREFLIGHT (latest check)

The latest bounded check was run after the final Task H code/config/test
changes at `2026-08-31T04:17:19.200315Z`. It is a successful live check for
the frozen provider/model/settings. No response body, credential, or
authorization header was captured. The adapter did not expose current
rate-limit headers on this response, so the historical safe header snapshot
below remains the only recorded header evidence.

```json
{
  "provider": "groq",
  "model": "openai/gpt-oss-120b",
  "phase": "PREFLIGHT",
  "checked_at": "2026-08-31T04:17:19.200315Z",
  "settings_identity": "MODEL-SETTINGS-V1",
  "network_reachable": true,
  "authenticated": true,
  "model_access": true,
  "generation_ok": true,
  "usage_metadata_available": true,
  "usage_fields": {
    "usage": ["completion_time", "completion_tokens", "completion_tokens_details", "prompt_time", "prompt_tokens", "queue_time", "total_time", "total_tokens"],
    "prompt_tokens_details": [],
    "completion_tokens_details": ["reasoning_tokens"]
  },
  "latency_ms": 2872,
  "error_category": "SUCCESS",
  "safe_message": "Provider generation succeeded.",
  "result": "PASS"
}
```

The command and settings identity remain the same as the historical capture
below. This preflight is still readiness evidence, not a Pilot observation.

## Prior sandbox probe (superseded)

The immediately preceding probe at `2026-08-31T04:10:30.087999Z` was blocked by
the sandbox network (`NETWORK_BLOCKED`). It is retained for audit history only
and does not override the successful live check above.

## Historical bounded PREFLIGHT (superseded)

The single bounded live check below was run from this project's `.venv` with
its local server-side `.env`. It is tagged `phase=PREFLIGHT`; it is not a Pilot
condition and must never be included as research evidence. Only safe quota
headers are retained. Authorization, the API key, and response text were not
printed or persisted.

```json
{
  "provider": "groq",
  "model": "openai/gpt-oss-120b",
  "phase": "PREFLIGHT",
  "checked_at": "2026-08-30T17:31:42Z",
  "settings_identity": "MODEL-SETTINGS-V1",
  "network_reachable": true,
  "authenticated": true,
  "model_access": true,
  "generation_ok": true,
  "usage_metadata_available": true,
  "usage_fields": [
    "completion_time",
    "completion_tokens",
    "completion_tokens_details",
    "prompt_time",
    "prompt_tokens",
    "queue_time",
    "total_time",
    "total_tokens"
  ],
  "status_code": 200,
  "latency_ms": 2105,
  "rate_limit_headers": {
    "x-ratelimit-limit-requests": "1000",
    "x-ratelimit-limit-tokens": "8000",
    "x-ratelimit-remaining-requests": "999",
    "x-ratelimit-remaining-tokens": "3826",
    "x-ratelimit-reset-requests": "1m26.4s",
    "x-ratelimit-reset-tokens": "31.305s"
  },
  "request_parameters_sent": [
    "max_completion_tokens",
    "messages",
    "model",
    "n",
    "reasoning_effort",
    "response_format",
    "service_tier",
    "stream",
    "temperature",
    "top_p"
  ],
  "extra_body_parameters_sent": ["include_reasoning"],
  "result": "PASS"
}
```

The request used the same frozen settings identity and values listed below.
The observed request/token headers match the account snapshot's `RPD=1000`
and combined `TPM=8000`; the public/account distinction for `RPM=30` remains
the conservative operational ceiling. No `retry-after` header was present
because the request was not rate limited.

## Candidate and settings identity

```text
provider              = groq
model                 = openai/gpt-oss-120b
settings identity     = MODEL-SETTINGS-V1
settings version      = 1.1
provider adapter      = openai-compatible
provider timeout      = 60 seconds
SDK max retries       = 0
orchestrator retries  = 1 per logical call
probe wrapper timeout = 90 seconds (readiness command only)
```

The request sent the following non-secret parameters:

```text
temperature=0.6
max_completion_tokens=4096
top_p=1.0
reasoning_effort=medium
include_reasoning=false  (extra_body)
response_format={"type":"text"}
stream=false
n=1
service_tier=on_demand
seed=(not sent; UNUSED_BY_DESIGN)
```

`reasoning_format` was not sent because Groq documents it as unsupported for
GPT-OSS; `stop` remains the documented provider-default `null`. No response
text or credential value is stored in this record. Tool-calling, document/web
search, and stream-option controls are recorded as unused/not applicable; the
API's citation-enabled, `tool_choice=none`, and `parallel_tool_calls=true`
defaults are explicitly recorded as harmless because no documents, search, or
tools are supplied. `store` is unsupported by Groq Chat and is not sent.
Unsupported penalty/logprob and deprecated `max_tokens` controls are also not
sent.

The parameter evidence is the [Groq API reference](https://console.groq.com/docs/api-reference),
[reasoning guide](https://console.groq.com/docs/reasoning), and
[GPT-OSS 120B model page](https://console.groq.com/docs/model/openai/gpt-oss-120b).

## Live result

Command (run with the local secret-bearing `.env`; the command output is safe):

```powershell
.\.venv\Scripts\python.exe scripts\provider_probe.py groq `
  --model openai/gpt-oss-120b --pilot-settings --timeout 90
```

The earlier 14:04 request used the configured dependency runtime before this
project-local environment was established. The fresh header-capture block at
the top of this document is now the canonical bounded readiness result; the
command above remains the canonical Integration rerun (and must be run again
if the provider/model/settings or account changes).

Historical normalized result from the first live request (retained for audit;
the fresh header-capture result above supersedes it for readiness):

```json
{
  "provider": "groq",
  "model": "openai/gpt-oss-120b",
  "checked_at": "2026-08-30T14:04:25Z",
  "settings_identity": "MODEL-SETTINGS-V1",
  "network_reachable": true,
  "authenticated": true,
  "model_access": true,
  "generation_ok": true,
  "usage_metadata_available": true,
  "usage_fields": {
    "usage": [
      "completion_time",
      "completion_tokens",
      "completion_tokens_details",
      "prompt_time",
      "prompt_tokens",
      "queue_time",
      "total_time",
      "total_tokens"
    ],
    "prompt_tokens_details": [],
    "completion_tokens_details": ["reasoning_tokens"]
  },
  "request_parameters_sent": [
    "max_completion_tokens",
    "model",
    "n",
    "reasoning_effort",
    "response_format",
    "service_tier",
    "stream",
    "temperature",
    "top_p"
  ],
  "extra_body_parameters_sent": ["include_reasoning"],
  "result": "PASS",
  "latency_ms": 3058
}
```

The request completed successfully in approximately 3.06 seconds. A second
same-settings inspection returned `prompt_tokens=86`,
`completion_tokens=71`, `total_tokens=157`, and
`completion_tokens_details.reasoning_tokens=61`. This confirms that usage
metadata is available and that reasoning-token detail is distinct from the
reported completion total; the pricing snapshot intentionally has no separate
reasoning rate.

## Rate-limit and 96-run feasibility

The fresh response headers and the account snapshot in
[`docs/PILOT_PROVIDER_LIMITS.md`](PILOT_PROVIDER_LIMITS.md) provide the current
account evidence for `RPD=1000` and combined `TPM=8000`. The user-supplied
organization snapshot also freezes `RPM=30` and `TPD=200000`; separate ITPM/
OTPM values remain explicitly unverified. The current Groq rate-limit reference
says limits are organization-level and that the account Limits page is
authoritative. The separate [supported-models table](https://console.groq.com/docs/models)
shows a higher developer-plan summary, so Integration must re-check the
account-specific headers immediately before authorization. See the [Groq
rate-limits reference](https://console.groq.com/docs/rate-limits).

Measured Fake dry-run call pattern for one comparison unit was:

```text
Single=1, Fixed=6, Static=3, Adaptive=3  => 13 logical/physical calls
```

That gives these planning bounds for 24 units / 96 conditions:

```text
observed no-retry baseline       24 × 13 = 312 physical requests
one retry on each observed call  24 × 26 = 624 physical requests
hard per-condition budget cap    96 × 18 = 1,728 physical requests
```

The measured Fake token total was about 39K for the baseline and 79K under the
one-retry stress estimate, but Fake does not model Groq reasoning tokens. The
4096 completion cap therefore cannot be used as a typical-token estimate; a
cap-sized burst would exceed the published TPM/TPD values.

**Feasibility: PARTIAL / CONDITIONAL.** The 312-request baseline and
624-request one-retry stress count are each below the account 1K RPD request
limit; the hard 1,728-request per-condition ceiling is not. The measured Fake
token estimates (39K baseline / 79K one-retry stress) are below 200K TPD, but
Fake does not model GPT-OSS reasoning usage, so they are not a live-token
guarantee; cap-sized calls can exceed the TPD/TPM limits. The 8K TPM / 30 RPM
limits can also distort concurrent worker timing. Integration should authorize
only with a throttled batch/rest policy: keep at most three in-flight workers,
pace aggregate requests below the account's reported RPM/TPM headers (use a
conservative 20 requests/minute until headers are captured), honor
`retry-after` at the Integration pacing layer (the frozen orchestrator retry
backoff is capped at 30 seconds), and split the block if remaining RPD/TPD
cannot cover the 624-request stress budget. Record response rate-limit headers
and pauses as execution metadata. Do not treat a rate-limited condition as a
model-quality failure.

## Handoff

The historical capture is **PASS** for network, authentication, model access,
generation, usage metadata and frozen-setting acceptance. The latest final
integration probe at `2026-08-31T04:17:19.200315Z` is also **PASS** for those
fields and supersedes the sandbox-blocked probe. Current rate-limit headers
were not exposed by the adapter; the historical safe header snapshot and the
conservative pacing gate therefore remain in force. This preflight still does
not authorize a Pilot by itself.
