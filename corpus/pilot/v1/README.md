# Adaptive Agent Lab v0.6

Prototype local bám sát đề tài **Adaptive Multi-Agent LLM Orchestration**.

## Chạy nhanh trên Windows

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\START_WINDOWS.ps1
```

Mở `http://127.0.0.1:8000`.

> Đừng mở `preview-*.html` để test API. App thật phải chạy qua FastAPI.

## Provider

App hỗ trợ:

- `fake` — offline, không cần key
- `gemini` — mặc định `gemini-3.7-flash`
- `groq` — mặc định `openai/gpt-oss-120b`
- `openrouter` — mặc định `openrouter/free` (dev/demo only)
- `openai` — mặc định `gpt-5.6-luna`

Copy `.env.example` thành `.env`, sau đó chỉ điền key của provider muốn dùng. API key luôn nằm server-side và `.gitignore` chặn `.env`.

Nút kiểm tra provider và lệnh `scripts\provider_probe.py <provider>` trả về
diagnostic an toàn theo category (`SUCCESS`, `NOT_CONFIGURED`, network/DNS,
timeout, auth, permission, model, rate/quota/credit hoặc provider error). Provider
đã cấu hình nhưng chưa có bằng chứng live vẫn hiển thị `unknown`.

## Flow chat chính

```text
Task + source context
  -> Simple RAG / Frozen Context Snapshot
  -> Structural Analyzer
  -> Rule-based AUTO routing
       DIRECT | PARALLEL | PLANNED
  -> Agent selection
  -> execute / DAG scheduler
  -> Runtime Verifier
       PASS -> STOP_SUFFICIENT
       NEEDS_WORK -> targeted escalation (nếu còn budget)
  -> final answer + evidence
```

User **không chọn Single/Fixed/Static** trong chat chính. Các strategy đó chỉ nằm trong nút **So sánh** để tạo baseline.

## Conversation persistence

Mỗi cuộc trò chuyện được lưu ở `runs/conversations/`. Mỗi lượt hiển thị thành một khung gồm:

- câu hỏi
- câu trả lời
- selected mode
- provider/model
- calls/tokens/latency
- link tới Run Evidence

Sidebar có rename/delete conversation.

## Kiểm tra

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\runtime_check.py --write-test
.\.venv\Scripts\python.exe scripts\provider_probe.py fake
.\.venv\Scripts\python.exe scripts\provider_probe.py gemini
.\.venv\Scripts\python.exe scripts\provider_probe.py openai
```

## File quan trọng

- `app/core/orchestrator.py` — Adaptive logic
- `app/core/graph.py` — DAG validation / ready-set
- `app/core/rag.py` — Simple RAG + Frozen Context Snapshot
- `app/providers/` — provider adapters
- `app/main.py` — FastAPI, persistence, compare
- `app/static/` — chat UI
- `AUDIT_FIXES.md` — audit lỗi và các thay đổi v0.6
