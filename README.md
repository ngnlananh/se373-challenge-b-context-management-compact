# Stage 03: Bash

read_file, write_file, bash + skill catalog (weekly-report).

- Tools: `read_file(path)`, `write_file(path, content)`, `bash(command)`
- Skills: `weekly-report`

## Cài đặt và chạy

Cần Python 3.11+ và [uv](https://docs.astral.sh/uv/). Chạy trong thư mục project này:

```bash
cd stage-03-bash
uv sync --all-packages --locked
cp -n .env.example .env
# Điền OPENAI_API_KEY, MODEL_NAME (và OPENAI_BASE_URL nếu dùng endpoint khác) vào .env
uv run streamlit run app.py
```

Trong lab, cả 5 stage dùng chung `.venv` và `uv.lock` ở thư mục `agent-tools-skills-lab`; `uv sync` và `uv run` tự nhận diện workspace. Không tạo `.venv` riêng tại stage. Nếu copy stage ra ngoài lab để chạy độc lập, dùng `uv sync` thay cho lệnh sync trên.

Mở **Local URL** in ra terminal (mặc định `http://localhost:8501`). `.streamlit/config.toml` của project bật `server.headless`, nên Streamlit không hỏi email ở lần chạy đầu và không tự mở trình duyệt; file này cũng đặt màu theme và tắt gửi thống kê sử dụng. Streamlit chỉ đọc file này khi chạy trong thư mục project.

Đường dẫn được resolve từ vị trí source. Chạy từ thư mục khác: `uv run --project stage-03-bash streamlit run stage-03-bash/app.py`; app vẫn dùng đúng `.env`, workspace và `traces/` của project này.

## Cấu hình model

| Biến | Bắt buộc | Ý nghĩa |
|---|---|---|
| `OPENAI_API_KEY` | Có | API key của provider |
| `MODEL_NAME` | Có | Tên model, cần hỗ trợ native tool calling |
| `OPENAI_BASE_URL` | Không | OpenAI-compatible endpoint. Endpoint phải hỗ trợ tool calling theo chuẩn OpenAI Chat Completions (`tools`, `tool_calls`, message role `tool`). |

Thiếu `OPENAI_API_KEY` hoặc `MODEL_NAME`: UI hiện cảnh báo, ô chat bị khóa và app không gọi model. App không truyền `temperature` hay tham số model khác; key không được ghi vào trace/log.

## Prompt thử

1. `Chạy python --version và cho biết kết quả.`
2. `Chạy một lệnh Python in Lỗi thử nghiệm ra stderr rồi kết thúc với exit code 1. Giải thích kết quả.`

Kỳ vọng: Trace hiển thị command, stdout, stderr, exit_code thực tế. Lệnh exit 1 vẫn là tool result đọc được (`ok: true`, `exit_code: 1`).

## Xem output, trace, state và context

- **Bố cục**: trang không cuộn; chỉ cột chat và cột State & Context cuộn riêng, cao theo cửa sổ trình duyệt (khối CSS nhỏ `PAGE_CSS` trong `app.py`). Nội dung dài (trace, bảng, file output) hiện đầy đủ trong cột, không có khung cuộn lồng nhau.
- **Chat (cột trái)**: mỗi lượt assistant có expander **Các bước thực hiện (N model call, M tool call)**: từng model call, mỗi tool call trong một khung có badge ok/lỗi, thời gian chạy, arguments (lệnh bash hiện dạng code), result; content/stdout/stderr hiện đầy đủ. Final answer nằm ngoài expander. Nút **Cuộc trò chuyện mới** (cạnh tiêu đề) xóa history, counters, snapshots, skill đã load của conversation cũ; không xóa `traces/` hay file output.
- **State & Context (cột phải)**: badge trạng thái và 4 counters cập nhật trong lúc chạy (rê chuột vào biểu tượng ? để xem định nghĩa); **Tools được cấp** (schema); **Skills trong catalog** (metadata, chưa phải đã load); **Skill content đã vào history** (chỉ khi `read_file` SKILL.md thành công, kèm message index và tool_call_id); **Tài nguyên đã đọc**; **Message history hiện tại**; **Event log**.
- **Context gửi model (lớp LangChain)**: snapshot request chụp ngay trước mỗi model call: system prompt thực tế, messages theo thứ tự, tools schema, metadata (conversation_id, run_id, lượt, model call, event sequence, thời điểm, model name, số message, số ký tự, usage nếu provider trả về). Trước model call đầu tiên, panel hiện **Context cấu hình (chưa gửi)**. Sau khi lượt kết thúc có thể chọn lại snapshot cũ (chỉ đọc, không chạy lại agent) và tải snapshot JSON. Snapshot không phải provider wire payload, tokenizer output hay nội dung bên trong model.
- **File đầu ra**: chọn file trong `workspace/output/`, xem Markdown/text và tải xuống. Xem file là thao tác UI, không gửi nội dung vào context của model.
- **Trace trên đĩa**: `traces/<thời gian>_<conversation>_turnNN_<run>.jsonl`, mỗi dòng một event (sequence, type, tool_call_id, tool_name, arguments, result, elapsed_ms; event `model_request` kèm snapshot request). Exception không mong đợi ghi thêm vào `traces/debug.log`.

## Định nghĩa trong State & Context

| Trường | Ý nghĩa |
|---|---|
| Lượt chat | Một lần gửi input; bắt đầu từ 1 trong mỗi conversation. |
| Lần gọi model trong lượt | Tăng ngay trước mỗi model request thực tế (middleware `wrap_model_call`); reset khi gửi lượt mới. Retry nội bộ của OpenAI SDK không quan sát được nên không đếm riêng. |
| Bước sự kiện trong lượt | Số thứ tự observer event (`user_submitted`, `model_request`, `model_response`, `tool_started`, `tool_finished`, `run_completed`, `run_failed`). Không phải LangGraph step. |
| Tool calls trong lượt | Số tool call đã thực thi, mỗi call có ID riêng. Một model response có thể yêu cầu nhiều tool calls. |
| Trạng thái | Sẵn sàng / Đang gọi model / Đang chạy tool / Hoàn tất / Lỗi. |

## Giới hạn thực thi

Mỗi lượt: tối đa 8 lần gọi model (`ModelCallLimitMiddleware`), 20 tool calls (`ToolCallLimitMiddleware`), recursion limit LangGraph 50 (số bước graph, không phải số tool calls). Giá trị nằm trong `config.py`.

Lỗi runtime/provider: UI hiện lỗi, giữ trace đã có, rollback model history về trước lượt lỗi. App không tự chạy lại lượt lỗi.

## Workspace và reset

Agent chỉ làm việc trong `workspace/`: `read_file` đọc file trong workspace, `write_file` chỉ ghi dưới `workspace/output/`. Lần chạy đầu, nếu chưa có workspace, app copy từ `fixtures/`; rerun không ghi đè.

Khôi phục dữ liệu gốc (xóa output, giữ traces):

```bash
uv run python reset_workspace.py
```

Lệnh chỉ chạy khi workspace có marker `.lab-workspace` của lab.

## Skills

`skill_catalog.py` quét `workspace/skills/*/SKILL.md`, chỉ đưa `name`, `description`, `location` vào system prompt. Body và reference không có trong context ban đầu. Model tự đọc SKILL.md bằng `read_file` khi task khớp description; tool result ở lại trong history cho các lượt sau. Skill thiếu metadata hoặc YAML sai bị bỏ qua kèm diagnostic; trùng `name` báo lỗi và giữ bản đầu (xem expander **Skills trong catalog**). Thêm skill mới: tạo `workspace/skills/<name>/SKILL.md` (và bản trong `fixtures/skills/` nếu muốn giữ sau reset).

## Tests

```bash
uv run pytest
```

Tests dùng mock model, không cần API key.

## Giới hạn môi trường

- **Bash không phải sandbox.** `bash` chạy `bash -c` với cwd là `workspace/`, env tối thiểu (PATH trỏ Python trong `.venv` của project, locale UTF-8, không có API key), timeout 10 giây. Path check của `read_file`/`write_file` không áp dụng cho Bash: lệnh vẫn đọc/ghi được ngoài workspace với quyền user chạy app.

- Chỉ chạy trong môi trường lab với dữ liệu giả. Không mount thư mục cá nhân hoặc secrets vào máy/container chạy lab.

- Cần môi trường POSIX có `bash`. Trên Windows dùng WSL2 (cài uv và chạy project bên trong WSL2).

- Chạy local, một người dùng cho mỗi project. Không có xác thực, không chia sẻ workspace đa người dùng.
