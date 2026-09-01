from __future__ import annotations

import os
import re


def redact_secrets(value: object) -> str:
    """Return a log-safe error string without configured provider credentials."""
    message = str(value)
    for name in ("GEMINI_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
        secret = os.getenv(name, "")
        if secret:
            message = message.replace(secret, "[REDACTED]")
    message = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED]", message)
    message = re.sub(r"sk-[0-9A-Za-z_-]{16,}", "[REDACTED]", message)
    message = re.sub(r"gsk_[0-9A-Za-z_-]{16,}", "[REDACTED]", message)
    message = re.sub(r"sk-or-v1-[0-9A-Za-z_-]{16,}", "[REDACTED]", message)
    message = re.sub(r"AQ\.[0-9A-Za-z_-]{20,}", "[REDACTED]", message)
    return message[:2000]
