from __future__ import annotations

import asyncio
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.core.rag import frozen_snapshot
from app.main import execute_once
from app.core.security import redact_secrets


FULL_REFERENCE = """# API Reference

Authentication uses a Bearer token. Access tokens expire after 60 minutes.
Refresh tokens may be used only by confidential clients. Public clients must
re-authenticate after access-token expiry.

Collection endpoints use cursor pagination. The default page size is 25 and
the maximum is 100.

401 means missing or expired authentication. 429 means rate limit exceeded.
"""

CASES = [
    (
        "simple",
        "Theo tài liệu, access token hết hạn sau bao lâu?",
        "Access tokens expire after 60 minutes.",
        "DIRECT",
        0,
    ),
    (
        "multi_aspect",
        "Tóm tắt authentication, pagination và error handling thành ba mục độc lập.",
        "Authentication uses a Bearer token.\n\nPagination uses cursors.\n\n401 is auth failure; 429 is rate limit.",
        "PARALLEL",
        0,
    ),
    (
        "dependency_heavy",
        "Phân tích authentication, pagination và error handling; từ đó lập thứ tự kiểm tra, sau đó kết luận.",
        "Authentication uses a Bearer token.\n\nPagination uses cursors.\n\n401 is auth failure; 429 is rate limit.",
        "PLANNED",
        0,
    ),
    (
        "conflict_sensitive",
        "Refresh token chỉ dùng cho confidential clients nhưng public clients phải re-authenticate. "
        "Hãy giải thích đúng rule cho từng trường hợp, xử lý mâu thuẫn và ngoại lệ để tránh nhầm.",
        FULL_REFERENCE,
        "PLANNED",
        1,
    ),
]


async def main(provider_name: str, case_name: str | None = None, model_name: str | None = None) -> int:
    failures = []
    for label, task, reference, expected_mode, expected_escalations in CASES:
        if case_name and label != case_name:
            continue
        snapshot, meta = frozen_snapshot(task, reference)

        async def sink(_):
            return None

        try:
            data = await execute_once(
                strategy="adaptive",
                provider_name=provider_name,
                model_name=model_name,
                message=task,
                frozen_context=snapshot,
                retrieval_meta=meta,
                history=[],
                emit=sink,
            )
        except Exception as exc:
            failures.append(label)
            print(f"{label}: FAIL | provider={provider_name} | error="
                  f"{redact_secrets(type(exc).__name__ + ': ' + str(exc))}")
            continue
        route = next(
            (event["meta"].get("mode") for event in data["events"] if event["title"] == "AUTO route selected"),
            None,
        )
        passed = (
            data["status"] == "completed"
            and data["stop_reason"] == "STOP_SUFFICIENT"
            and route == expected_mode
            and (
                data["metrics"]["escalations"] == expected_escalations
                if provider_name == "fake"
                else data["metrics"]["escalations"] in {0, 1}
            )
        )
        if not passed:
            failures.append(label)
        print(
            f"{label}: {'PASS' if passed else 'FAIL'} | provider={provider_name} | mode={route} | "
            f"stop={data['stop_reason']} | escalations={data['metrics']['escalations']} | "
            f"tokens={data['metrics']['total_tokens']} | run_id={data['run_id']}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("fake", "gemini", "groq", "openrouter", "openai"), default="fake")
    parser.add_argument("--case", choices=tuple(case[0] for case in CASES))
    parser.add_argument("--model", help="Optional model id; otherwise use the provider .env default.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.provider,args.case,args.model)))
