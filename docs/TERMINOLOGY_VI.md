# Làm rõ thuật ngữ: Multi-Agent và Multi-Model

## Phạm vi nghiên cứu

Adaptive Agent Lab nghiên cứu **điều phối thích ứng trong một hệ thống
Multi-Agent LLM đồng nhất (homogeneous)**.

Ở đây:

- **Multi-Agent** = có nhiều Agent/vai trò hoặc nhiều lần thực thi Agent.
- **Multi-Agent không đồng nghĩa với Multi-Model**.
- Nhiều Agent có thể cùng dùng **một Model nền duy nhất**.

Trong thí nghiệm chính, Single, Fixed, Static và Adaptive dùng chung Provider,
Model và model settings. Các Agent LLM-backed trong cùng phép so sánh cũng dùng
chung các định danh này. Mục tiêu là cô lập ảnh hưởng của **điều phối**.

## Bốn thuật ngữ chính

### Agent

**Agent** là một thực thể/vai trò xử lý có phạm vi và hợp đồng riêng. Một Agent
được nhận diện bởi:

- mục tiêu riêng;
- prompt/instructions riêng;
- input riêng;
- output contract riêng;
- dependency riêng (nếu có);
- execution evidence riêng.

Agent không phải là tên của Model. Một Model có thể được gọi bởi nhiều Agent
khác nhau; ngược lại, một Agent có thể phát sinh nhiều lần gọi hoặc retry theo
quy tắc runtime.

Trong runtime, **Agent Execution** là một lần kích hoạt có giới hạn của một vai
trò Agent. Vì vậy, số Agent Execution là số lần thực thi vai trò, không phải số
Model khác nhau.

### Model

**Model** là mô hình LLM nền cung cấp khả năng suy luận và sinh nội dung cho
Agent. Model là năng lực được Agent sử dụng, không phải bản thân Agent.

### Provider

**Provider** là dịch vụ cung cấp API/model. Ví dụ: `Groq`. Provider và Model là
hai khái niệm khác nhau: một Provider có thể cung cấp quyền truy cập tới một
hoặc nhiều Model.

### Orchestrator

**Orchestrator** là bộ điều phối/chính sách của hệ thống. Nó quyết định:

- gọi Agent nào;
- gọi bao nhiêu Agent;
- thứ tự thực thi;
- phần nào chạy song song và phần nào phải chờ dependency;
- khi nào dừng;
- khi nào bổ sung xử lý có giới hạn.

Orchestrator không phải là một Model thứ hai và cũng không tự động được tính
là một LLM Agent bổ sung.

## Ví dụ cụ thể

Giả sử cấu hình là:

```text
Provider = Groq
Model = openai/gpt-oss-120b
```

Runtime có thể gồm các vai trò Agent:

```text
Analyzer
Planner
Worker S1
Worker S2
Worker S3
Synthesizer
Verifier
```

Trong thí nghiệm chính, tất cả các vai trò LLM-backed trên **đều dùng chính
Model `openai/gpt-oss-120b`**, với cùng Provider và model settings đã đóng băng.

Do đó:

```text
7 Agent Executions
≠
7 different Models
```

Bảy lần thực thi chỉ nói rằng bảy lần kích hoạt vai trò đã được ghi nhận. Nó
không nói hệ thống đã dùng bảy Model khác nhau.

## Vì sao phải giữ cùng Provider/Model/settings?

Thí nghiệm muốn đo tác động của cách điều phối: chọn Agent, tạo dependency,
chạy song song, retry, verify, dừng hoặc bổ sung xử lý. Nếu Planner dùng
Gemini, Worker dùng DeepSeek, còn Verifier dùng Groq, kết quả có thể khác vì
năng lực Model chứ không phải vì orchestration.

Đó là **confounding factor — yếu tố gây nhiễu**: không biết kết quả khác do
điều phối hay do Model. Giữ Provider, Model và model settings cố định giúp
giảm yếu tố gây nhiễu này.

## Ngoài phạm vi hiện tại

Routing dị thể Multi-Agent/Multi-Model, chẳng hạn:

```text
Gemini Agent
DeepSeek Agent
Grok Agent
```

**không thuộc phạm vi của thí nghiệm chính**. Đây có thể là:

- công việc tương lai;
- một robustness experiment tùy chọn sau Main;
- hoặc một câu hỏi nghiên cứu riêng.

Không thêm routing dị thể vào Pilot hiện tại và không dùng nó để thay đổi RQ1,
RQ2, task taxonomy, Adaptive policy, Fixed topology, Static presets, Pilot
benchmark, Pilot rubric hay Main/Pilot protocol.

## Cách đọc các số liệu runtime

Các số liệu sau là những khái niệm khác nhau:

- **Agent Execution**: một lần thực thi bounded của một vai trò Agent;
- **Logical Model Call**: một lời gọi ở cấp orchestration cho vai trò đó; retry
  vẫn thuộc cùng logical call;
- **Physical Provider Request**: từng request thực tế gửi tới Provider; retry
  làm tăng số request.

Không được suy ra số Model từ một trong các số đếm Agent/Call/Request này.

## Kết luận ngắn

> Multi-Agent mô tả **cấu trúc và số vai trò/thực thi**.
>
> Model mô tả **LLM nền** mà các vai trò đó sử dụng.
>
> Primary research của dự án là **homogeneous Multi-Agent: Có** và
> **primary Multi-Model routing: Không**.

Đây là làm rõ thuật ngữ và phạm vi; không thay đổi research semantics hay
runtime behavior.
