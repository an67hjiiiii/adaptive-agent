from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.core.pilot import build_pilot_manifest
from app.core.pilot_authorization import (
    AUTHORIZED_PILOT_SCOPE,
    DEFAULT_LIVE_WINDOW_MAX_DURATION_SECONDS,
    DEFAULT_PROJECT_TIMEZONE,
    GROQ_RPD_LIMIT,
    GROQ_RPM_LIMIT,
    GROQ_TPD_LIMIT,
    GROQ_TPM_LIMIT,
    KNOWN_LOCAL_EXPERIMENT_USAGE,
    LocalPilotUsageLedger,
    PILOT_AUTHORIZATION_SCHEMA_ID,
    PILOT_LIVE_WINDOW_SCHEMA_ID,
    PILOT_PACING_POLICY,
    PILOT_PACING_POLICY_ID,
    PILOT_PREFLIGHT_BINDING_SCHEMA_ID,
    PilotAuthorizationError,
    UNAVAILABLE,
    UNKNOWN_PROVIDER_ACCOUNT_WIDE_REMAINING,
    build_authorization_record,
    build_live_window,
    build_preflight_binding,
    normalize_rate_limit_headers,
    parse_retry_after,
    provider_remaining_from_headers,
    retry_after_decision,
    safe_preflight_metadata,
    validate_authorization_record,
    validate_exactly_one_preflight,
    validate_live_window,
    validate_pacing_policy,
    validate_preflight_binding,
)


class PilotAuthorizationMechanismTests(unittest.TestCase):
    def test_frozen_pacing_policy_is_conservative_and_complete(self):
        self.assertTrue(validate_pacing_policy())
        self.assertEqual(PILOT_PACING_POLICY["policy_id"], PILOT_PACING_POLICY_ID)
        self.assertLessEqual(PILOT_PACING_POLICY["max_requests_per_minute"], 20)
        self.assertLessEqual(PILOT_PACING_POLICY["max_requests_per_minute"], GROQ_RPM_LIMIT)
        self.assertLessEqual(PILOT_PACING_POLICY["max_in_flight"], 3)
        self.assertLessEqual(PILOT_PACING_POLICY["tpm_ceiling"], GROQ_TPM_LIMIT)
        self.assertLessEqual(PILOT_PACING_POLICY["rpd_ceiling"], GROQ_RPD_LIMIT)
        self.assertLessEqual(PILOT_PACING_POLICY["tpd_ceiling"], GROQ_TPD_LIMIT)
        for key in (
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
        ):
            self.assertIn(key, PILOT_PACING_POLICY)

    def test_local_rpd_and_tpd_guards_fail_closed_at_reserved_ceiling(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = LocalPilotUsageLedger(Path(directory) / "usage.json", window_id="window-1")
            ledger.record(requests=899, tokens=179999)
            self.assertTrue(ledger.can_issue(requests=1, estimated_tokens=1))
            ledger.record(requests=1, tokens=1)
            with self.assertRaisesRegex(PilotAuthorizationError, "LOCAL_RPD_GUARD"):
                ledger.guard_before_request(requests=1)

            # A fresh window makes the request guard independent of the first
            # check and exercises the token ceiling explicitly.
            token_ledger = LocalPilotUsageLedger(window_id="window-2")
            token_ledger.record(requests=1, tokens=180000)
            with self.assertRaisesRegex(PilotAuthorizationError, "LOCAL_TPD_GUARD"):
                token_ledger.guard_before_request(requests=1, estimated_tokens=1)

    def test_local_usage_distinguishes_known_local_and_provider_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.json"
            ledger = LocalPilotUsageLedger(path, window_id="window-1")
            snapshot = ledger.record(requests=1, tokens=17)
            self.assertEqual(snapshot["source"], KNOWN_LOCAL_EXPERIMENT_USAGE)
            self.assertEqual(snapshot["provider_remaining_requests"], UNKNOWN_PROVIDER_ACCOUNT_WIDE_REMAINING)
            self.assertEqual(snapshot["provider_remaining_tokens"], UNKNOWN_PROVIDER_ACCOUNT_WIDE_REMAINING)
            reopened = LocalPilotUsageLedger(path, window_id="window-1")
            self.assertEqual(reopened.snapshot()["requests_consumed"], 1)
            self.assertEqual(reopened.snapshot()["tokens_consumed"], 17)

    def test_local_usage_rolls_over_by_vietnam_local_day_without_erasing_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.json"
            vietnam = timezone(timedelta(hours=7))
            first_day = datetime(2026, 8, 30, 23, 59, tzinfo=vietnam)
            second_day = datetime(2026, 8, 31, 0, 1, tzinfo=vietnam)
            ledger = LocalPilotUsageLedger(path, window_id="window-1", now=first_day)
            first = ledger.record(requests=2, tokens=20, now=first_day)
            second = ledger.record(requests=1, tokens=7, now=second_day)
            self.assertEqual(first["date"], "2026-08-30")
            self.assertEqual(first["requests_consumed"], 2)
            self.assertEqual(second["date"], "2026-08-31")
            self.assertEqual(second["requests_consumed"], 1)
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                [(entry["date"], entry["requests_consumed"]) for entry in persisted["entries"]],
                [("2026-08-30", 2), ("2026-08-31", 1)],
            )

    def test_missing_rate_headers_are_unavailable_not_zero(self):
        normalized = normalize_rate_limit_headers({})
        self.assertTrue(all(value == UNAVAILABLE for value in normalized.values()))
        remaining = provider_remaining_from_headers({})
        self.assertEqual(remaining["requests"], UNAVAILABLE)
        self.assertEqual(remaining["tokens"], UNAVAILABLE)
        self.assertNotIn(0, remaining.values())

    def test_retry_after_seconds_http_date_and_fallback(self):
        self.assertEqual(parse_retry_after("3"), 3.0)
        now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        self.assertAlmostEqual(
            parse_retry_after("Mon, 31 Aug 2026 12:00:05 GMT", now=now),
            5.0,
            places=3,
        )
        decision = retry_after_decision({}, fallback_seconds=2)
        self.assertEqual(decision["seconds"], 2.0)
        self.assertEqual(decision["source"], "BOUNDED_FALLBACK")
        self.assertEqual(retry_after_decision({"Retry-After": "4"})["seconds"], 4.0)

    def _manifest(self):
        task = {
            "manifest_id": "AUTH-TASK-MANIFEST",
            "version": "1.0",
            "benchmark_version": "AUTH-BENCH@1.0",
            "rubric_version_reference": "AUTH-RUBRIC@1.0",
            "tasks": [{"task_id": "AUTH-T1", "task_hash": "auth-hash"}],
        }
        return build_pilot_manifest(task, repeat_count=1, provider="groq", model="openai/gpt-oss-120b", require_balanced=False)

    def _preflight(self, manifest, **overrides):
        values = {
            "preflight_id": "preflight-1",
            "manifest_id": manifest["manifest_id"],
            "provider": manifest["provider"],
            "model": manifest["model"],
            "model_settings_identity": manifest["model_settings_identity"],
            "freeze_identity": manifest["freeze_identity"],
            "checked_at": datetime.now(timezone.utc),
        }
        values.update(overrides)
        return build_preflight_binding(**values)

    def test_preflight_binding_accepts_one_fresh_match_and_rejects_identity_drift(self):
        manifest = self._manifest()
        binding = self._preflight(manifest)
        self.assertEqual(binding["binding_schema_id"], PILOT_PREFLIGHT_BINDING_SCHEMA_ID)
        self.assertTrue(validate_preflight_binding(binding, manifest=manifest))
        self.assertTrue(validate_exactly_one_preflight([binding], manifest=manifest))
        with self.assertRaisesRegex(PilotAuthorizationError, "MODEL_MISMATCH"):
            validate_preflight_binding({**binding, "model": "wrong-model"}, manifest=manifest)
        with self.assertRaisesRegex(PilotAuthorizationError, "SETTINGS_MISMATCH"):
            validate_preflight_binding({**binding, "model_settings_identity": "wrong-settings"}, manifest=manifest)
        stale = {**binding, "checked_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}
        with self.assertRaisesRegex(PilotAuthorizationError, "FRESH_PILOT_PREFLIGHT_REQUIRED"):
            validate_preflight_binding(stale, manifest=manifest)

    def test_preflight_binding_requires_exactly_one_and_secret_safe_metadata(self):
        manifest = self._manifest()
        binding = self._preflight(manifest)
        with self.assertRaisesRegex(PilotAuthorizationError, "exactly one"):
            validate_exactly_one_preflight([], manifest=manifest)
        safe = safe_preflight_metadata({
            **binding,
            "network_reachable": True,
            "authenticated": True,
            "model_access": True,
            "generation_ok": True,
            "usage_fields": ["total_tokens"],
            "api_key": "must-not-copy",
            "Authorization": "Bearer must-not-copy",
            "response_text": "must-not-copy",
            "rate_limit_headers": {"x-ratelimit-remaining-requests": "7"},
        })
        encoded = json.dumps(safe, ensure_ascii=False).lower()
        self.assertNotIn("must-not-copy", encoded)
        self.assertNotIn("api_key", encoded)
        self.assertNotIn("authorization", encoded)
        self.assertNotIn("response_text", encoded)
        self.assertEqual(safe["rate_limit_headers"]["x-ratelimit-remaining-tokens"], UNAVAILABLE)

    def test_live_window_uses_explicit_timezone_and_future_times(self):
        now = datetime.now().astimezone()
        before = now + timedelta(hours=1)
        after = before + timedelta(hours=2)
        window = build_live_window("window-1", before, after)
        self.assertEqual(window["schema_id"], PILOT_LIVE_WINDOW_SCHEMA_ID)
        self.assertEqual(window["timezone"], DEFAULT_PROJECT_TIMEZONE)
        self.assertEqual(window["max_duration"], DEFAULT_LIVE_WINDOW_MAX_DURATION_SECONDS)
        self.assertTrue(validate_live_window(window, now=now))
        expired_window = build_live_window(
            "window-expired",
            now - timedelta(hours=2),
            now - timedelta(minutes=1),
        )
        with self.assertRaisesRegex(PilotAuthorizationError, "expired"):
            validate_live_window(expired_window, now=now)
        with self.assertRaisesRegex(PilotAuthorizationError, "exceeds max_duration"):
            build_live_window("window-2", before, before + timedelta(hours=5))

    def test_owner_authorization_schema_and_validation_have_no_execution_side_effect(self):
        manifest = self._manifest()
        binding = self._preflight(manifest)
        window = build_live_window(
            "window-1",
            datetime.now().astimezone() + timedelta(hours=1),
            datetime.now().astimezone() + timedelta(hours=2),
        )
        record = build_authorization_record(
            authorization_id="auth-1",
            manifest_id=manifest["manifest_id"],
            freeze_candidate_id=manifest["freeze_identity"],
            preflight_id=binding["preflight_id"],
            window_id=window["window_id"],
        )
        self.assertEqual(record["schema_id"], PILOT_AUTHORIZATION_SCHEMA_ID)
        self.assertEqual(record["role"], "PROJECT_OWNER")
        self.assertEqual(record["authorized_scope"], AUTHORIZED_PILOT_SCOPE)
        self.assertEqual(record["status"], "PENDING")
        self.assertNotIn("owner_name", record)
        # Validation is pure and the module has no provider factory/import;
        # calling it is therefore itself the no-side-effect assertion.
        self.assertTrue(validate_authorization_record(
            record,
            manifest=manifest,
            preflight_binding=binding,
            live_window=window,
        ))


if __name__ == "__main__":
    unittest.main()
