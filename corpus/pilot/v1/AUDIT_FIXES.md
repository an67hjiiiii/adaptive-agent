# Audit & Fixes — Adaptive Agent Lab v0.6

## Mục tiêu bản sửa

Bản này tập trung vào 3 việc: **chạy ổn**, **bám sát Adaptive Orchestration**, và **UI dùng như một chat app thật** thay vì dashboard rời rạc.

## Các lỗi/vấn đề đã phát hiện

### 1. Conversation hiển thị rời rạc
Bản cũ render câu hỏi user và câu trả lời assistant thành hai khối độc lập. Khi hội thoại dài, mắt rất khó biết câu trả lời nào thuộc câu hỏi nào; khi mở lại history cũng không tạo cảm giác một transcript ổn định.

**Fix:** mỗi lượt giờ là một `turn-card` duy nhất: câu hỏi + câu trả lời + mode + provider/model + calls/tokens/latency + nút mở evidence.

### 2. Lịch sử conversation khó đọc
Sidebar cũ gần như chỉ là danh sách title/meta nhỏ, thiếu preview và thao tác quản lý.

**Fix:** mỗi conversation là một card có title, câu hỏi gần nhất, số lượt, provider, thời gian cập nhật; thêm rename/delete. Backend có PATCH/DELETE endpoint thật.

### 3. Provider test thất bại có thể khóa nhầm cả provider
UI cũ chặn luôn Send khi trạng thái provider là `failed`. Một test lỗi vì model/credit/rate-limit không có nghĩa mọi request/model của provider chắc chắn không chạy được.

**Fix:** chỉ chặn khi **không có API key**. Trạng thái failed là cảnh báo, không phải hard lock. Nếu đổi model, trạng thái quay về unknown và có thể test lại.

### 4. Gemini đang dùng API legacy
Provider cũ gọi `generateContent`. Nó vẫn được hỗ trợ, nhưng Interactions API hiện là hướng mới cho ứng dụng/agent workflow.

**Fix:** Gemini adapter chuyển sang `POST /v1beta/interactions`, dùng `system_instruction`, `generation_config`, `response_format` khi yêu cầu JSON, parse `steps[]`, và usage `total_input_tokens / total_output_tokens`.

### 5. Chỉ có OpenAI/Gemini/Fake nên dễ bị kẹt billing/key
Demo Multi-Agent gọi nhiều request; nếu OpenAI hết credit hoặc Gemini key lỗi thì gần như không test được.

**Fix:** thêm Groq và OpenRouter qua OpenAI-compatible adapter. OpenRouter Free được ghi rõ là **dev-only**, không dùng làm Main Experiment vì router có thể đổi model giữa các request.

### 6. Current task và chat history bị trộn thành một chuỗi
Bản cũ nối `RECENT CHAT` trực tiếp vào `task`. Analyzer có thể xem câu hỏi cũ như một phần task hiện tại và route sai.

**Fix:** `RunState` tách `task` và `chat_history`; prompt ghi riêng `CURRENT USER TASK`, `RECENT CONVERSATION CONTEXT`, `FROZEN REFERENCE CONTEXT`.

### 7. Provider/API information chưa đủ rõ
UI trước có badge nhỏ và dễ hiểu nhầm lỗi kết nối thành lỗi orchestration.

**Fix:** Provider + Model + API test tách rõ. Inspector chỉ hiển thị luồng thuật toán; provider_request ẩn khỏi Flow nhưng vẫn có trong Raw evidence.

### 8. Chữ và mật độ giao diện hơi nhỏ
Inspector/meta có nhiều chữ 8–10px, assistant text trông như log.

**Fix:** tăng body answer lên ~15.5px desktop, tăng spacing, giảm noise, tăng contrast. Hai panel vẫn collapse mượt và workspace tự giãn.

## Core research giữ nguyên

- Simple RAG -> Frozen Context Snapshot
- Structural Analyzer
- Rule-based AUTO route: DIRECT / PARALLEL / PLANNED
- Agent Selection
- Planner chỉ khi PLANNED
- DAG validation
- dependency-aware ready-set scheduling
- Worker concurrency với asyncio
- Runtime Verifier
- PASS / NEEDS_WORK / FAIL
- Early Stop
- Targeted Escalation
- retry / timeout / logical-call budget / physical-request budget
- token / latency / calculated cost
- raw evidence
- Single / Fixed / Static / Adaptive comparison trên cùng Frozen Context Snapshot

## Quy tắc nghiên cứu

Chat chính luôn chạy **Adaptive AUTO**. Single/Fixed/Static chỉ xuất hiện trong Compare để tránh người dùng vô tình biến cơ chế adaptive thành lựa chọn thủ công.

OpenRouter `openrouter/free` phù hợp debug/demo nhưng không phù hợp Main Experiment vì backend router có thể chọn model khác nhau. Main Experiment phải freeze provider + model + config.

### 9. Physical request accounting could be undercounted by SDK retries
OpenAI SDK-based providers can retry internally. If that happens below the Orchestrator, one application-level attempt may generate more than one HTTP request while the trace still counts only one.

**Fix:** OpenAI, Groq and OpenRouter adapters set `max_retries=0`. Retry/backoff is owned by `Orchestrator._call`, so Logical Call vs Physical Request accounting stays observable.

### 10. A stale API-test badge could survive a changed key
`provider_status.json` previously remembered only `ready/failed + model`. After replacing an API key, the UI could still display an old green status until tested again.

**Fix:** provider status is bound to a one-way SHA-256 key fingerprint stored only locally. If the key changes, status returns to `unknown`. The fingerprint itself is not returned to the browser.

### 11. Very long chat history/context uploads could hurt routing or fail late
The backend accepts a bounded task/context, but old history was not separately bounded and the browser could load an oversized text file before receiving a backend validation error.

**Fix:** recent conversation context is capped while preserving newest turns; prompt/context `maxlength` now matches backend contracts; oversized uploaded context is truncated to 100,000 characters with a visible warning.
