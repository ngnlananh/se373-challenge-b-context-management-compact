"""Observer: quan sát model call / tool execution và giữ state cho phần State & Context.

Hai phần:
- ObserverMiddleware chạy trong agent (có thể ở worker thread của LangGraph). Nó chỉ chụp request
  ngay sát model/tool invocation rồi phát event qua stream writer (stream_mode="custom").
  Không sửa request, không gọi lại handler, không gọi model/tool khác.
- Observer sống trong st.session_state, nhận event ở luồng UI, đánh số và giữ counters, snapshots,
  message history. Mọi dữ liệu lưu là bản sao JSON (deep copy), không giữ reference tới list đang chạy.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.config import get_stream_writer

STATUS_READY = "Sẵn sàng"
STATUS_MODEL = "Đang gọi model"
STATUS_TOOL = "Đang chạy tool"
STATUS_DONE = "Hoàn tất"
STATUS_ERROR = "Lỗi"

EVENT_TYPES = (
    "user_submitted",
    "model_request",
    "model_response",
    "tool_started",
    "tool_finished",
    "run_completed",
    "run_failed",
)

ROLE_BY_TYPE = {"human": "user", "ai": "assistant", "tool": "tool", "system": "system"}
SKILL_FILE_RE = re.compile(r"^skills/([^/]+)/SKILL\.md$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def json_copy(value: Any) -> Any:
    """Deep copy dạng JSON để snapshot không bị mutate về sau."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def serialize_message(message: BaseMessage) -> dict[str, Any]:
    data: dict[str, Any] = {
        "role": ROLE_BY_TYPE.get(message.type, message.type),
        "type": message.type,
        "content": json_copy(message.content),
        "id": message.id,
    }
    if isinstance(message, AIMessage):
        data["tool_calls"] = [
            {"id": call.get("id"), "name": call.get("name"), "args": json_copy(call.get("args", {}))}
            for call in message.tool_calls
        ]
        if message.usage_metadata:
            data["usage_metadata"] = json_copy(dict(message.usage_metadata))
    if isinstance(message, ToolMessage):
        data["tool_call_id"] = message.tool_call_id
        data["name"] = message.name
        data["status"] = message.status
    return data


def tool_schema(tool: Any) -> dict[str, Any]:
    """Tên, description và argument schema của tool như được bind cho model."""
    if isinstance(tool, dict):
        return json_copy(tool)
    function = convert_to_openai_tool(tool)["function"]
    return {
        "name": function["name"],
        "description": function.get("description", ""),
        "parameters": function.get("parameters", {}),
    }


def parse_tool_content(content: Any) -> Any:
    """Tool trong lab trả JSON string; parse để hiển thị bằng st.json. Không parse được thì giữ nguyên."""
    if isinstance(content, str):
        try:
            return json.loads(content)
        except ValueError:
            return content
    return content


def content_chars(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        total += len(message_text(message.get("content", "")))
        for call in message.get("tool_calls", []) or []:
            total += len(json.dumps(call.get("args", {}), ensure_ascii=False))
    return total


class ObserverMiddleware(AgentMiddleware):
    """Chụp request ở lớp LangChain ngay trước model/tool invocation và phát event qua stream writer."""

    def wrap_model_call(self, request, handler):
        writer = get_stream_writer()
        system_prompt = request.system_message.text if request.system_message is not None else ""
        writer(
            {
                "observer": True,
                "event": "model_request",
                "data": {
                    "captured_at": now_iso(),
                    "model_name": getattr(request.model, "model_name", None),
                    "system_prompt": system_prompt,
                    "messages": [serialize_message(m) for m in request.messages],
                    "tools": [tool_schema(t) for t in request.tools],
                },
            }
        )
        started = time.perf_counter()
        response = handler(request)  # gọi đúng một lần
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        ai_messages = [m for m in response.result if isinstance(m, AIMessage)]
        last = ai_messages[-1] if ai_messages else None
        writer(
            {
                "observer": True,
                "event": "model_response",
                "data": {
                    "elapsed_ms": elapsed_ms,
                    "tool_calls_requested": [
                        {"id": c.get("id"), "name": c.get("name")} for c in (last.tool_calls if last else [])
                    ],
                    "usage": json_copy(dict(last.usage_metadata)) if last and last.usage_metadata else None,
                },
            }
        )
        return response

    def wrap_tool_call(self, request, handler):
        writer = get_stream_writer()
        call = request.tool_call
        writer(
            {
                "observer": True,
                "event": "tool_started",
                "data": {"tool_call_id": call.get("id"), "tool_name": call.get("name"), "arguments": json_copy(call.get("args", {}))},
            }
        )
        started = time.perf_counter()
        try:
            result = handler(request)
        except Exception as exc:
            writer(
                {
                    "observer": True,
                    "event": "tool_finished",
                    "data": {
                        "tool_call_id": call.get("id"),
                        "tool_name": call.get("name"),
                        "status": "exception",
                        "error": f"{type(exc).__name__}: {exc}",
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                }
            )
            raise
        data: dict[str, Any] = {
            "tool_call_id": call.get("id"),
            "tool_name": call.get("name"),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        if isinstance(result, ToolMessage):
            data["status"] = result.status
            data["result"] = parse_tool_content(json_copy(result.content))
        else:
            data["status"] = "success"
            data["result"] = f"<{type(result).__name__}>"
        writer({"observer": True, "event": "tool_finished", "data": data})
        return result


@dataclass
class Observer:
    """State quan sát của một conversation. Chỉ thay đổi khi nhận event thực tế."""

    conversation_id: str
    chat_turn: int = 0
    run_id: str | None = None
    model_calls: int = 0
    event_seq: int = 0
    tool_calls: int = 0
    status: str = STATUS_READY
    running_tools: dict[str, str] = field(default_factory=dict)
    turn_failed: bool = False
    history_rolled_back: bool = False
    error: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def start_turn(self, run_id: str) -> None:
        self.chat_turn += 1
        self.run_id = run_id
        self.model_calls = 0
        self.event_seq = 0
        self.tool_calls = 0
        self.running_tools = {}
        self.turn_failed = False
        self.history_rolled_back = False
        self.error = None
        self.status = STATUS_READY

    def sync_messages(self, messages: list[BaseMessage]) -> None:
        """Cập nhật message history hiện tại (bản sao) sau mỗi graph update."""
        self.messages = [serialize_message(m) for m in messages]

    def record(self, event_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Ghi một event có thứ tự; trả event đã chuẩn hóa để ghi trace."""
        if event_type not in EVENT_TYPES:
            raise ValueError(f"Unknown observer event: {event_type}")
        data = json_copy(data or {})
        self.event_seq += 1
        event: dict[str, Any] = {
            "conversation_id": self.conversation_id,
            "run_id": self.run_id,
            "chat_turn": self.chat_turn,
            "sequence": self.event_seq,
            "type": event_type,
            "timestamp": now_iso(),
        }

        if event_type == "model_request":
            self.model_calls += 1
            self.status = STATUS_MODEL
            snapshot = {
                "label": "Context gửi model (lớp LangChain)",
                "conversation_id": self.conversation_id,
                "run_id": self.run_id,
                "chat_turn": self.chat_turn,
                "model_call_index": self.model_calls,
                "event_sequence": self.event_seq,
                "captured_at": data.get("captured_at"),
                "model_name": data.get("model_name"),
                "system_prompt": data.get("system_prompt", ""),
                "messages": data.get("messages", []),
                "tools": data.get("tools", []),
                "message_count": len(data.get("messages", [])),
                "system_prompt_chars": len(data.get("system_prompt", "")),
                "message_chars": content_chars(data.get("messages", [])),
                "usage": None,
            }
            self.snapshots.append(snapshot)
            event["model_call_index"] = self.model_calls
            event["snapshot"] = json_copy(snapshot)
        elif event_type == "model_response":
            event["model_call_index"] = self.model_calls
            event.update(data)
            if self.snapshots and self.snapshots[-1]["run_id"] == self.run_id:
                self.snapshots[-1]["usage"] = data.get("usage")
        elif event_type == "tool_started":
            self.tool_calls += 1
            self.running_tools[data["tool_call_id"]] = data["tool_name"]
            self.status = STATUS_TOOL
            event.update(data)
        elif event_type == "tool_finished":
            self.running_tools.pop(data.get("tool_call_id"), None)
            event.update(data)
        elif event_type == "run_completed":
            self.status = STATUS_DONE
            self.running_tools = {}
            event.update(data)
        elif event_type == "run_failed":
            self.status = STATUS_ERROR
            self.turn_failed = True
            self.error = data.get("error")
            self.running_tools = {}
            event.update(data)
        else:  # user_submitted
            event.update(data)

        self.events.append(json_copy(event))
        return event

    def counters(self) -> dict[str, Any]:
        return {
            "Trạng thái": self.status,
            "Lượt chat": self.chat_turn,
            "Lần gọi model trong lượt": self.model_calls,
            "Bước sự kiện trong lượt": self.event_seq,
            "Tool calls trong lượt": self.tool_calls,
        }

    def inventory(self) -> dict[str, list[dict[str, Any]]]:
        """Skill content / tài nguyên đã vào history, suy từ tool result read_file thành công."""
        return context_inventory(self.messages, self.snapshots)

    def export(self) -> dict[str, Any]:
        return json_copy(
            {
                "label": "Context gửi model (lớp LangChain), không phải provider wire payload",
                "conversation_id": self.conversation_id,
                "counters": self.counters(),
                "messages": self.messages,
                "snapshots": self.snapshots,
                "events": self.events,
            }
        )


def context_inventory(messages: list[dict[str, Any]], snapshots: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Chỉ tính read_file có tool result ok=true và content không rỗng. Chạy script bằng bash không tính."""
    skills: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if message.get("role") != "tool" or message.get("name") != "read_file":
            continue
        result = parse_tool_content(message.get("content"))
        if not isinstance(result, dict) or result.get("ok") is not True or not result.get("content"):
            continue
        path = str(result.get("path", ""))
        tool_call_id = message.get("tool_call_id")
        item = {"path": path, "message_index": index, "tool_call_id": tool_call_id}
        match = SKILL_FILE_RE.match(path)
        if match:
            item["skill"] = match.group(1)
            item["chars"] = len(result["content"])
            item["first_request"] = _first_request_with(tool_call_id, snapshots or [])
            skills.append(item)
        else:
            resources.append(item)
    return {"skills": skills, "resources": resources}


def _first_request_with(tool_call_id: str | None, snapshots: list[dict[str, Any]]) -> str | None:
    for snap in snapshots:
        for message in snap.get("messages", []):
            if message.get("role") == "tool" and message.get("tool_call_id") == tool_call_id:
                return f"Lượt {snap['chat_turn']}, model call #{snap['model_call_index']}"
    return None
