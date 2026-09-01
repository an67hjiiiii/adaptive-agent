# Pilot provider limits — Groq

**Snapshot ID:** `GROQ-PILOT-LIMITS-V1`  
**Snapshot version:** `1.0`  
**Provider:** `groq`  
**Model:** `openai/gpt-oss-120b`  
**Verified at:** `2026-08-30T17:31:42Z` (fresh bounded response/header check)

This is a no-credential operational snapshot for the Pilot candidate. The
organization values below are the current verified account limits supplied for
Task C and corroborated by the fresh response headers where a header is
available. The Groq account Limits page remains authoritative if values change.
The frozen operational tuple is `RPM=30`, `RPD=1000`, `TPM=8000`, and
`TPD=200000`.

## Frozen limits

| Scope | Limit | Value | Evidence/status |
| --- | --- | ---: | --- |
| Organization | Requests per minute (RPM) | `30` | Verified account snapshot; use as the conservative request ceiling. |
| Organization | Requests per day (RPD) | `1000` | Verified account snapshot; fresh `x-ratelimit-limit-requests=1000`. |
| Organization | Tokens per minute (TPM) | `8000` | Verified account snapshot; fresh `x-ratelimit-limit-tokens=8000`. |
| Organization | Tokens per day (TPD) | `200000` | Verified account snapshot. |
| Project | Override | `NONE` | Project inherits organization limits. |
| Account | Separate input TPM (ITPM) | `SEPARATE_ITPM_OTPM_NOT_VERIFIED` | No reliable separate numeric value captured. |
| Account | Separate output TPM (OTPM) | `SEPARATE_ITPM_OTPM_NOT_VERIFIED` | No reliable separate numeric value captured. |

Operational pacing uses the combined `TPM=8000` ceiling. It does not invent an
ITPM/OTPM split and does not treat an unavailable split as zero. A fresh
preflight may record `x-ratelimit-remaining-*`, `x-ratelimit-reset-*`, and
`retry-after` values, but those are observations for pacing rather than new
frozen quotas.

## Provenance and handling

- Account/project scope: Task C verified organization snapshot; project has no
  override and inherits the organization values.
- Header evidence: [`docs/GROQ_PILOT_PREFLIGHT.md`](GROQ_PILOT_PREFLIGHT.md),
  `phase=PREFLIGHT`, `2026-08-30T17:31:42Z`.
- Provider reference: [Groq rate limits](https://console.groq.com/docs/rate-limits).
- No API key, authorization header, response text, or credential fingerprint is
  stored in this snapshot.

## Feasibility guardrails

The measured Fake call pattern is `Single=1`, `Fixed=6`, `Static=3`, and
`Adaptive=3` per comparison unit (13 calls). For 24 units / 96 conditions this
is 312 physical requests without retries, 624 under one retry per observed call,
and a hard 1,728-request per-condition budget ceiling. The first two request
counts fit below `RPD=1000`; the hard ceiling does not. Fake does not model
GPT-OSS reasoning usage, so token estimates are not a live quota guarantee.

The retained Fake dry-run also measured approximately `110` tokens for Single,
`812` for Fixed, `361` for Static, and `361` for Adaptive per unit (1,644
combined tokens). If that engineering-only shape held, 24 units would be about
39,456 tokens without retries or 78,912 with one retry, below `TPD=200000` but
still requiring roughly five to ten minutes at the combined `TPM=8000` ceiling.
The conservative 20-request/minute gate is the slower bound for request volume
(about 16 minutes baseline or 31 minutes with one retry). These are planning
estimates only; GPT-OSS reasoning and prompt-cache behavior must be measured
from live usage headers/metadata, not inferred from Fake.

Integration must therefore pace the aggregate block conservatively: no more
than three in-flight workers, no more than 20 requests/minute until a fresh
header observation supports another rate, honor `retry-after`, and split or
pause the block when remaining RPD/TPD/TPM cannot cover the planned attempt
budget. A rate-limited or quota-exhausted condition is retained as operational
missingness/provider incident, not converted into a quality failure.

The machine-readable pacing policy is
`config/pilot/PILOT_PACING_POLICY_V1.json` (`GROQ-PILOT-PACING-V1@1.0`). It
retains a local ten-percent daily reserve: the local guards stop at 900
requests/day and 180,000 tokens/day even though the provider snapshot remains
RPD=1,000 and TPD=200,000. This reserve is an operational headroom rule, not an
invented provider limit. `app/core/pilot_authorization.py` persists the local
request/token/date/window counters when a ledger path is supplied. It labels
those counters `KNOWN_LOCAL_EXPERIMENT_USAGE`; provider-wide remaining values
are `UNKNOWN_PROVIDER_ACCOUNT_WIDE_REMAINING`. Missing or unexposed headers are
`UNAVAILABLE`, never zero.
