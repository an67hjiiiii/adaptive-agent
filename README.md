# Adaptive Agent Lab v0.6

Prototype local bám sát đề tài **Adaptive Multi-Agent LLM Orchestration**.

## Chạy nhanh trên Windows

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\START_WINDOWS.ps1
```

Mở `http://127.0.0.1:8000`.

> Đừng mở `preview-*.html` để test API. App thật phải chạy qua FastAPI.

## Deploy trên Render

1. Push repository lên GitHub và tạo Render Blueprint/Web Service từ repository.
2. Render sẽ dùng `render.yaml`; thêm key provider cần dùng trong Environment.
3. Deploy rồi mở URL `*.onrender.com` được cấp.

Provider key chỉ nằm ở Environment Variables server-side. Dữ liệu conversation/file-backed
trong `runs/` có thể tạm thời và bị mất sau restart/redeploy trên Render.

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

## Pilot readiness

`scripts\pilot_harness.py` prepares a versioned, no-secret Pilot manifest from
the separate benchmark manifest and controls only the experiment infrastructure.
It does not launch the 96-run Pilot by default.

```powershell
.\.venv\Scripts\python.exe scripts\pilot_harness.py prepare `
  --task-manifest benchmarks\pilot\pilot_benchmark_v1.json `
  --output runs\pilot\pilot_manifest.json

.\.venv\Scripts\python.exe scripts\pilot_harness.py dry-run

# Validate a frozen manifest and run only one Fake/preflight condition.
.\.venv\Scripts\python.exe scripts\pilot_harness.py validate `
  runs\pilot\pilot_manifest.json `
  --task-manifest benchmarks\pilot\pilot_benchmark_v1.json
.\.venv\Scripts\python.exe scripts\pilot_harness.py run `
  runs\pilot\pilot-ledger `
  --manifest runs\pilot\pilot_manifest.json `
  --task-manifest benchmarks\pilot\pilot_benchmark_v1.json `
  --phase PREFLIGHT --limit 1
.\.venv\Scripts\python.exe scripts\pilot_harness.py status runs\pilot\pilot-ledger
.\.venv\Scripts\python.exe scripts\pilot_harness.py resume `
  runs\pilot\pilot-ledger `
  --task-manifest benchmarks\pilot\pilot_benchmark_v1.json `
  --phase PREFLIGHT --limit 1
```

The dry-run uses Fake, tags raw evidence `DRY_RUN=true`, and is not research
evidence. `run`/`resume` consume the manifest order, default to one condition,
and require `--allow-live` for non-Fake providers. See
`docs\PILOT_EXECUTION_PROTOCOL.md` for order control, resume safety, pricing,
and export rules.

## File quan trọng

- `app/core/orchestrator.py` — Adaptive logic
- `app/core/graph.py` — DAG validation / ready-set
- `app/core/rag.py` — Simple RAG + Frozen Context Snapshot
- `app/providers/` — provider adapters
- `app/main.py` — FastAPI, persistence, compare
- `app/static/` — chat UI
- `AUDIT_FIXES.md` — audit lỗi và các thay đổi v0.6
