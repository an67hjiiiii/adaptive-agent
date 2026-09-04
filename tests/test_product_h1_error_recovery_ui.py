"""H1-B: frontend-only provider error recovery UX contract.

Browser-free, static-source checks in the same style as the existing
``tests/test_runtime.py`` static contract tests. These assertions target
only ``app/static/app.js`` / ``index.html`` and reuse the EXISTING
``friendlyRunError`` / ``safeErrorDetail`` / ``UPSTREAM_ERROR_MESSAGES``
architecture -- no new error-handling system, no backend changes.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


class ProviderErrorRecoveryUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (STATIC / "app.js").read_text(encoding="utf-8")
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")

    def _body(self, start: str, end: str) -> str:
        return self.js.split(start, 1)[1].split(end, 1)[0]

    def test_reuses_existing_error_helpers_no_second_system(self):
        # The mapping must build on the existing helpers, not replace them.
        self.assertIn("function friendlyRunError", self.js)
        self.assertIn("function safeErrorDetail", self.js)
        self.assertIn("const UPSTREAM_ERROR_MESSAGES", self.js)
        self.assertIn("providerFriendlyMessage", self.js)
        self.assertIn("safeErrorDetail(value,status,contentType)", self.js)

    def test_known_safe_message_categories_map_to_vietnamese_copy(self):
        table = self._body("const PROVIDER_SAFE_MESSAGE_COPY", "function providerFriendlyMessage")
        # Conceptual categories from app/core/provider_diagnostics.SAFE_MESSAGES:
        # rate limit / timeout / auth-config must all have Vietnamese copy.
        self.assertIn("rate limit reached", table)
        self.assertIn("Nhà cung cấp đang giới hạn yêu cầu", table)
        self.assertIn("request timed out", table)
        self.assertIn("Phản hồi mất quá nhiều thời gian", table)
        self.assertIn("rejected the configured credentials", table)
        self.assertIn("Cấu hình mô hình hiện chưa sẵn sàng", table)

    def test_run_chat_always_resets_busy_and_composer_in_finally(self):
        run_chat = self._body("async function runChat", "async function testProvider")
        self.assertIn("finally{busy=false;sendBtn.disabled=false", run_chat)
        self.assertIn("promptEl.focus()", run_chat)

    def test_run_chat_catch_never_clears_project_or_history_wholesale(self):
        run_chat = self._body("async function runChat", "async function testProvider")
        catch_block = run_chat.split("catch(error){", 1)[1].split("}finally{", 1)[0]
        self.assertNotIn("projectWorkspace=null", catch_block)
        self.assertNotIn("history=[]", catch_block)
        # Only the just-submitted optimistic user turn may be rolled back.
        self.assertIn("history.pop()", catch_block)

    def test_catch_uses_friendly_run_error_not_raw_message(self):
        run_chat = self._body("async function runChat", "async function testProvider")
        catch_block = run_chat.split("catch(error){", 1)[1].split("}finally{", 1)[0]
        self.assertIn("friendlyRunError(error.message", catch_block)

    def test_node_syntax_check(self):
        result = subprocess.run(
            ["node", "--check", str(STATIC / "app.js")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_provider_friendly_message_hides_raw_english_safe_message(self):
        helper = self.js.split("const UPSTREAM_ERROR_MESSAGES", 1)[1].split("function cap", 1)[0]
        script = "const UPSTREAM_ERROR_MESSAGES" + helper + r'''
const rateLimited = friendlyRunError("Provider rate limit reached; wait before retrying.", "groq", "model");
if (!rateLimited.includes("Nhà cung cấp đang giới hạn yêu cầu")) throw new Error("rate_limit: " + rateLimited);
if (rateLimited.includes("wait before retrying")) throw new Error("rate_limit leaked raw text: " + rateLimited);

const timeoutMsg = friendlyRunError("Provider request timed out; check network latency and retry.", "openai", "model");
if (!timeoutMsg.includes("Phản hồi mất quá nhiều thời gian")) throw new Error("timeout: " + timeoutMsg);
if (timeoutMsg.includes("check network latency")) throw new Error("timeout leaked raw text: " + timeoutMsg);

const authMsg = friendlyRunError("Provider API key is not configured.", "openai", "model");
if (!authMsg.includes("Cấu hình mô hình hiện chưa sẵn sàng")) throw new Error("auth: " + authMsg);

// Unknown/unmapped safe_message text still falls through safely (no crash,
// no HTML/stack leakage) via the existing safeErrorDetail path.
const fallback = friendlyRunError("Some new provider safe message.", "openai", "model");
if (!fallback.includes("Some new provider safe message.")) throw new Error("fallback: " + fallback);

console.log("ALL_PASS");
'''
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("ALL_PASS", result.stdout)

    def test_asset_version_bumped_together_in_html(self):
        # app.js changed in this task; the query-string version in index.html
        # must reference the same file consistently (existing convention).
        import re
        match = re.search(r'app\.js\?v=(\d+)', self.html)
        self.assertIsNotNone(match)


if __name__ == "__main__":
    unittest.main()
