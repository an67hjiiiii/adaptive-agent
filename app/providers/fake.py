from __future__ import annotations
import asyncio, json, re, uuid
from app.providers.base import Provider
from app.core.types import ProviderResult, Usage

class FakeProvider(Provider):
    name = "fake"
    model = "fake-research-v2"

    async def generate(self, *, system: str, user: str) -> ProviderResult:
        await asyncio.sleep(0.22)
        low = (system + "\n" + user).lower()
        task_match = re.search(r"current user task:\s*(.*?)\n\n(?:recent conversation context:.*?\n\n)?frozen reference context:", user, re.S | re.I)
        task_text = (task_match.group(1) if task_match else user).strip()
        task_low = task_text.lower()

        if "structural analyzer" in low:
            aspects = 1
            dep = False
            verify = "low"
            if any(x in task_low for x in ["authentication", "pagination", "error handling"]):
                aspects = 3
            if any(x in task_low for x in ["từ đó", "sau đó", "phụ thuộc", "depends", "based on"]):
                dep = True
            if any(x in task_low for x in ["mâu thuẫn", "conflict", "exception", "ngoại lệ", "tránh nhầm"]):
                verify = "high"
            elif aspects > 1:
                verify = "medium"
            aspect_objs=[{"name":f"aspect_{i+1}","goal":f"Analyze required aspect {i+1}"} for i in range(aspects)]
            obj = {
                "aspects": aspect_objs,
                "dependencies": [{"from":"aspect_1","to":"aspect_2","reason":"later step depends on earlier result"}] if dep and aspects > 1 else [],
                "parallelizable_groups": [[x["name"] for x in aspect_objs]] if aspects > 1 and not dep else [],
                "verification_demand": verify,
                "verification_reasons": ["conditional/exception-sensitive"] if verify=="high" else [],
                "rationale": "Derived from task wording and requested structure."
            }
            text = json.dumps(obj, ensure_ascii=False)

        elif "planner" in low:
            dep = any(x in task_low for x in ["từ đó", "sau đó", "phụ thuộc", "depends"])
            obj = {
                "subtasks": [
                    {"id":"S1","goal":"Extract the first required aspect","depends_on":[]},
                    {"id":"S2","goal":"Analyze the second required aspect","depends_on":["S1"] if dep else []},
                    {"id":"S3","goal":"Check remaining relevant evidence","depends_on":[]},
                ]
            }
            text = json.dumps(obj, ensure_ascii=False)

        elif "runtime verifier" in low:
            needs = any(x in task_low for x in ["public client", "confidential client", "ngoại lệ", "exception", "mâu thuẫn"])
            if needs and "[targeted_fix_done]" not in low:
                text = json.dumps({
                    "status":"NEEDS_WORK",
                    "issues":[{"type":"missing_or_unclear_exception","description":"Clarify the exception/condition before finalizing."}],
                    "rationale":"The candidate needs a clearer conditional distinction."
                }, ensure_ascii=False)
            else:
                text = json.dumps({"status":"PASS","issues":[],"rationale":"Candidate covers the requested points from context."}, ensure_ascii=False)

        elif "direct solver" in low:
            text = self._answer(task_text)

        elif "worker" in low:
            text = self._answer(task_text)

        elif "synthesizer" in low:
            text = "Synthesized answer:\n\n" + self._answer(task_text)

        else:
            text = self._answer(task_text)

        inp = max(80, len(user)//4)
        out = max(30, len(text)//4)
        return ProviderResult(text=text, usage=Usage(inp,out), request_id="fake_"+uuid.uuid4().hex[:8], model=self.model,
                              usage_metadata_available=True)

    def _answer(self, user: str) -> str:
        low=user.lower()
        if "token" in low and ("bao lâu" in low or "expire" in low):
            return "Theo context mẫu, access token hết hạn sau **60 phút**."
        if "pagination" in low and "authentication" in low:
            return ("**Authentication:** Bearer token; access token hết hạn sau 60 phút.\n\n"
                    "**Pagination:** cursor pagination; mặc định 25, tối đa 100.\n\n"
                    "**Error Handling:** 401 là thiếu/hết hạn xác thực; 429 là vượt rate limit.")
        if "public" in low or "confidential" in low or "mâu thuẫn" in low:
            return ("Hai rule phụ thuộc loại client: **confidential client** có thể dùng refresh token; "
                    "**public client** phải re-authenticate khi access token hết hạn.")
        return "Tôi đã phân tích task dựa trên reference context và tạo câu trả lời source-grounded cho demo."
