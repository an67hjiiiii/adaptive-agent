"""Small, dependency-free runtime diagnostic for the local app.

It intentionally prints only endpoint status and model ids. Provider keys and
provider response bodies never appear in its output.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid


def request(base_url: str, path: str, *, payload: dict | None = None, timeout: float = 5) -> object:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base_url.rstrip("/") + path, data=body, headers=headers,
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def chat_once(base_url: str, conversation_id: str, message: str, timeout: float) -> dict:
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat/stream",
        data=json.dumps({"message": message, "provider": "fake", "conversation_id": conversation_id}).encode("utf-8"),
        headers={"Accept": "application/x-ndjson", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        final = None
        for line in response:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("type") == "fatal":
                raise RuntimeError("server returned fatal event")
            if event.get("type") == "final":
                final = event
    if not final:
        raise RuntimeError("stream ended without final event")
    return final


def main(base_url: str, *, write_test: bool, timeout: float) -> int:
    try:
        health = request(base_url, "/api/health", timeout=timeout)
        if not isinstance(health, dict) or health.get("status") != "ok":
            print("HEALTH=FAIL")
            return 1
        config = request(base_url, "/api/config", timeout=timeout)
        if not isinstance(config, dict) or config.get("chat_strategy") != "adaptive-auto":
            print("CONFIG=FAIL")
            return 1
        providers = config.get("available") or {}
        models = config.get("models") or {}
        print(f"HEALTH=PASS | service={health.get('service')} | version={health.get('version')}")
        print("CONFIG=PASS | providers=" + ",".join(sorted(k for k, v in providers.items() if v)))
        print("MODELS=" + ",".join(f"{key}:{models[key]}" for key in sorted(models)))
        if not write_test:
            return 0

        conversation_id = "chat_diag_" + uuid.uuid4().hex[:12]
        first = chat_once(base_url, conversation_id, "runtime diagnostic one", timeout)
        second = chat_once(base_url, conversation_id, "runtime diagnostic two", timeout)
        stored = request(base_url, "/api/conversations/" + conversation_id, timeout=timeout)
        messages = stored.get("messages", []) if isinstance(stored, dict) else []
        runs = stored.get("run_ids", []) if isinstance(stored, dict) else []
        ok = (first.get("conversation_id") == conversation_id and
              second.get("conversation_id") == conversation_id and
              len(messages) == 4 and len(runs) == 2)
        print(f"PERSISTENCE={'PASS' if ok else 'FAIL'} | messages={len(messages)} | runs={len(runs)}")
        return 0 if ok else 1
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        # Keep diagnostics actionable while avoiding exception bodies that may
        # contain upstream request details.
        print(f"RUNTIME=FAIL | {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--write-test", action="store_true",
                        help="Run two fake turns and verify one persisted conversation.")
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    raise SystemExit(main(args.url, write_test=args.write_test, timeout=max(1, args.timeout)))
