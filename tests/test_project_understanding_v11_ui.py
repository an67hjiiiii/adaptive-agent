from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


class ProjectFolderUiContractTests(unittest.TestCase):
    """Static, browser-free contract checks for the V1.1 local-folder UX."""

    @classmethod
    def setUpClass(cls):
        cls.html = (STATIC / "index.html").read_text(encoding="utf-8")
        cls.js = (STATIC / "app.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "styles.css").read_text(encoding="utf-8")

    def test_folder_picker_menu_and_inputs_are_accessibly_wired(self):
        self.assertRegex(
            self.html,
            r'<input id="contextFolder" type="file" webkitdirectory directory multiple\b',
        )
        self.assertIn('id="contextFile" type="file" multiple', self.html)
        self.assertIn('id="attachmentMenu" role="menu"', self.html)
        self.assertIn('id="chooseFiles"', self.html)
        self.assertIn("Chọn tệp", self.html)
        self.assertIn('id="chooseFolder"', self.html)
        self.assertIn("Chọn thư mục dự án", self.html)
        self.assertIn('aria-controls="attachmentMenu"', self.html)
        self.assertIn('aria-expanded="false"', self.html)

        handlers = self.js.split('$("#attachButton").onclick=', 1)[1].split(
            '$("#sidebarToggle").onclick=', 1
        )[0]
        self.assertIn('$("#chooseFiles").onclick', handlers)
        self.assertIn('$("#chooseFolder").onclick', handlers)
        self.assertIn('$("#contextFile").click()', handlers)
        self.assertIn('$("#contextFolder").click()', handlers)
        self.assertIn("closeAttachmentMenu()", handlers)

    def test_discovery_uses_relative_paths_noise_filter_and_server_extensions(self):
        relative = self.js.split("function folderRelativePath", 1)[1].split(
            "function isProjectNoise", 1
        )[0]
        self.assertIn('replace(/\\\\/g,"/")', relative)
        self.assertIn("parts.slice(1).join(\"/\")", relative)

        noise = self.js.split("function isProjectNoise", 1)[1].split(
            "function supportedProjectFiles", 1
        )[0]
        self.assertIn("PROJECT_NOISE_DIRECTORIES", noise)
        self.assertIn('path.split("/")', noise)

        supported = self.js.split("function supportedProjectFiles", 1)[1].split(
            "async function importProjectFolder", 1
        )[0]
        self.assertIn("cfg?.context_file_extensions", supported)
        self.assertIn("folderRelativePath(file)", supported)
        self.assertIn("!isProjectNoise(item.path)", supported)
        self.assertIn("item.path.split(\".\").at(-1)", supported)
        self.assertIn("supported.has", supported)

        for directory in (".git", "node_modules", "dist", "build", "__pycache__", ".venv"):
            self.assertIn(f'"{directory}"', self.js)

    def test_project_import_is_bounded_sorted_and_uses_existing_api(self):
        body = self.js.split("async function importProjectFolder", 1)[1].split(
            "async function detachProjectWorkspace", 1
        )[0]
        self.assertIn("const accepted=supportedProjectFiles(files)", body)
        self.assertIn("const MAX_PROJECT_FILES = 20", self.js)
        self.assertIn("accepted.length>MAX_PROJECT_FILES", body)
        self.assertIn("Hỗ trợ tối đa 20 tệp mã nguồn trong một dự án.", body)
        self.assertIn('accepted.sort((a,b)=>a.path.localeCompare(b.path))', body)
        self.assertIn("processContextFile(item.file,null,item.path)", body)
        self.assertIn('fetch("/api/conversations/project-workspace"', body)
        self.assertIn("conversation_id:currentConversationId", body)
        self.assertIn("relative_path:item.source.relative_path", body)
        self.assertIn("content:item.text", body)
        self.assertIn("projectWorkspace=data.project_workspace||null", body)

    def test_project_envelope_attachment_states_and_removal_are_preserved(self):
        envelope = self.js.split("function rebuildContextFromAttachments", 1)[1].split(
            "function contextAttachmentStateText", 1
        )[0]
        self.assertIn("[PROJECT STRUCTURE]", envelope)
        self.assertIn("[RETRIEVED CONTEXT]", envelope)
        self.assertIn("projectStructure(labels)", envelope)
        self.assertIn("SOURCE: ${safeContextFilename", envelope)

        states = self.js.split("function contextAttachmentStateText", 1)[1].split(
            "function renderContextAttachments", 1
        )[0]
        self.assertIn('state==="loading"||state==="processing"', states)
        self.assertIn('state==="error"||state==="unsupported"', states)

        render = self.js.split("function renderContextAttachments", 1)[1].split(
            "async function encodeFileBase64", 1
        )[0]
        self.assertIn('item.status==="error"||item.status==="unsupported"', render)
        self.assertIn("retryContextFile(id)", render)
        self.assertIn("removeContextAttachment(id)", render)
        self.assertIn("clearDraftAttachments()", self.js)
        self.assertIn("clearContextFile()", self.js)

        self.assertIn(".composer-attachments", self.css)
        self.assertIn(".project-workspace-indicator", self.css)
        self.assertIn(".attachment-menu", self.css)
        self.assertIn(".attachment-menu.open", self.css)
        self.assertIn(":focus-visible", self.css)

    def test_normal_attachment_and_chat_payload_remain_on_existing_path(self):
        process = self.js.split("async function processContextFile", 1)[1].split(
            "function retryContextFile", 1
        )[0]
        self.assertIn('fetch("/api/context/prepare"', process)
        self.assertIn("relative_path:item.relativePath||undefined", process)
        self.assertIn("content_base64:await encodeFileBase64(file)", process)

        self.assertIn("function activeContextForRequest", self.js)
        self.assertIn("function contextSourcesForRequest", self.js)
        run_chat = self.js.split("async function runChat", 1)[1].split(
            "async function testProvider", 1
        )[0]
        self.assertIn("activeContextForRequest()", run_chat)
        self.assertIn("contextSourcesForRequest()", run_chat)
        self.assertIn("context_active:activeContext", run_chat)
        self.assertIn("context_sources:submittedContextSources", run_chat)

        handlers = self.js.split('$("#attachButton").onclick=', 1)[1].split(
            '$("#sidebarToggle").onclick=', 1
        )[0]
        self.assertIn('$("#contextFile").onchange', handlers)
        self.assertIn("processContextFile(file)", handlers)

    def test_static_asset_query_versions_are_synchronized(self):
        css_versions = re.findall(r"styles\.css\?v=(\d+)", self.html)
        js_versions = re.findall(r"app\.js\?v=(\d+)", self.html)
        self.assertEqual(css_versions, js_versions)
        self.assertEqual(len(css_versions), 1)


if __name__ == "__main__":
    unittest.main()
