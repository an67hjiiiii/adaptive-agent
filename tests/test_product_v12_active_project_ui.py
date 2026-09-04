from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


class ActiveProjectContextUiTests(unittest.TestCase):
    """Browser-free checks for the V1.2 active-project state semantics."""

    @classmethod
    def setUpClass(cls):
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.js = (STATIC / "app.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "styles.css").read_text(encoding="utf-8")

    def _body(self, start: str, end: str) -> str:
        return self.js.split(start, 1)[1].split(end, 1)[0]

    def test_selected_project_is_pending_until_prepare_completes(self):
        process = self._body("async function processContextFile", "function retryContextFile")
        render = self._body("function renderContextAttachments", "async function encodeFileBase64")
        self.assertIn("draftContextActive=true", process)
        self.assertIn('item.status="loading"', process)
        self.assertIn('item.status="processing"', process)
        self.assertIn('state==="loading"||state==="processing"', self.js)
        self.assertIn("context-file-state", render)
        self.assertNotIn("projectWorkspace=", process)

    def test_successful_project_has_explicit_active_context_semantics(self):
        indicator = self._body("function renderProjectWorkspaceIndicator", "function sourceIsExternal")
        self.assertIn("projectWorkspace", indicator)
        self.assertIn('$("#projectWorkspaceIndicator")', indicator)
        self.assertIn("Đang dùng", indicator)
        self.assertIn("project-workspace-status", indicator)
        self.assertIn("Gỡ khỏi ngữ cảnh", indicator)
        self.assertIn('if(!workspace?.project_id)', indicator)

    def test_active_project_survives_send_and_follow_up_turns(self):
        run_chat = self._body("async function runChat", "async function testProvider")
        self.assertIn("clearDraftAttachments()", run_chat)
        self.assertNotIn("projectWorkspace=null", run_chat)
        self.assertIn("context_active:activeContext", run_chat)
        self.assertIn("context_sources:submittedContextSources", run_chat)

    def test_remove_detaches_active_project_and_clears_future_state(self):
        detach = self._body("async function detachProjectWorkspace", "function installResizer")
        self.assertIn("/project-workspace", detach)
        self.assertIn('method:"DELETE"', detach)
        self.assertIn("projectWorkspace=null", detach)
        self.assertIn("renderProjectWorkspaceIndicator()", detach)
        self.assertIn("Đã tách dự án khỏi cuộc trò chuyện", detach)

    def test_new_chat_clears_old_project_indicator(self):
        new_chat = self._body("function newConversation", "function setContextOpen")
        self.assertIn("currentConversationId=null", new_chat)
        self.assertIn("projectWorkspace=null", new_chat)
        self.assertIn("renderProjectWorkspaceIndicator()", new_chat)
        self.assertIn("clearContextFile()", new_chat)

    def test_conversation_switch_clears_then_restores_per_conversation(self):
        load = self._body("async function loadConversation(id)", "async function loadRunInspector")
        cleared = load.index("projectWorkspace=null")
        fetched = load.index("fetch(`/api/conversations/")
        guarded_restore = load.index("if(loadId!==conversationLoadSequence)return")
        restored = load.index("projectWorkspace=conversation.project_workspace||null")
        self.assertLess(cleared, fetched)
        self.assertLess(guarded_restore, restored)
        self.assertIn("renderProjectWorkspaceIndicator()", load)

    def test_prepare_failure_cannot_render_active_project_state(self):
        process = self._body("async function processContextFile", "function retryContextFile")
        self.assertIn("catch(error)", process)
        self.assertIn('item.status=error.code==="UNSUPPORTED_FORMAT"?"unsupported":"error"', process)
        self.assertNotIn("Đang dùng", process)
        indicator = self._body("function renderProjectWorkspaceIndicator", "function sourceIsExternal")
        self.assertIn('if(!workspace?.project_id)', indicator)

    def test_normal_file_attachment_and_general_chat_do_not_use_active_project_state(self):
        handlers = self._body('$("#attachButton").onclick=', '$("#sidebarToggle").onclick=')
        self.assertIn('$("#contextFile").onchange', handlers)
        self.assertIn("processContextFile(file)", handlers)
        run_chat = self._body("async function runChat", "async function testProvider")
        self.assertNotIn("projectWorkspace=null", run_chat)
        self.assertIn("activeContextForRequest()", run_chat)

    def test_active_indicator_keeps_existing_compact_visual_language_and_assets(self):
        self.assertIn(".project-workspace-indicator", self.css)
        self.assertIn(".project-workspace-detach", self.css)
        self.assertIn(":focus-visible", self.css)
        css_versions = re.findall(r"styles\.css\?v=(\d+)", self.html)
        js_versions = re.findall(r"app\.js\?v=(\d+)", self.html)
        self.assertEqual(css_versions, js_versions)
        self.assertEqual(len(css_versions), 1)


if __name__ == "__main__":
    unittest.main()
