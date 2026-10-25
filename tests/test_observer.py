"""Observer: counters, snapshots, reset và skill/resource inventory từ fixture events."""

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from observer import STATUS_DONE, STATUS_ERROR, STATUS_MODEL, STATUS_TOOL, Observer, serialize_message

SYSTEM = "SYSTEM PROMPT"
TOOLS = [{"name": "read_file", "description": "Đọc file", "parameters": {"type": "object"}}]


def request(messages):
    return {
        "captured_at": "2026-10-04T00:00:00.000+00:00",
        "model_name": "mock",
        "system_prompt": SYSTEM,
        "messages": [serialize_message(m) for m in messages],
        "tools": [dict(t) for t in TOOLS],
    }


def read_result(call_id, path, ok=True, content="# body"):
    payload = {"ok": True, "path": path, "content": content} if ok else {"ok": False, "error": {"code": "FILE_NOT_FOUND", "message": "x"}}
    return ToolMessage(content=json.dumps(payload), tool_call_id=call_id, name="read_file")


def run_fixture_turn(observer):
    """Một lượt: model call 1 yêu cầu 2 tool calls, rồi model call 2 trả lời."""
    user = HumanMessage(content="Tạo báo cáo tuần")
    ai1 = AIMessage(
        content="",
        tool_calls=[
            {"name": "read_file", "args": {"path": "skills/weekly-report/SKILL.md"}, "id": "c1"},
            {"name": "read_file", "args": {"path": "data/weekly_notes.md"}, "id": "c2"},
        ],
    )
    t1 = read_result("c1", "skills/weekly-report/SKILL.md", content="# Weekly report skill body")
    t2 = read_result("c2", "data/weekly_notes.md")
    final = AIMessage(content="Xong")

    observer.start_turn("run-1")
    observer.record("user_submitted", {"text": user.content})
    history = [user]
    observer.sync_messages(history)
    observer.record("model_request", request(history))
    assert observer.status == STATUS_MODEL
    observer.record("model_response", {"tool_calls_requested": [{"id": "c1"}, {"id": "c2"}], "usage": None})
    history.append(ai1)
    observer.sync_messages(history)
    observer.record("tool_started", {"tool_call_id": "c1", "tool_name": "read_file", "arguments": {}})
    observer.record("tool_started", {"tool_call_id": "c2", "tool_name": "read_file", "arguments": {}})
    assert observer.status == STATUS_TOOL
    assert set(observer.running_tools) == {"c1", "c2"}
    observer.record("tool_finished", {"tool_call_id": "c1", "tool_name": "read_file", "status": "success"})
    observer.record("tool_finished", {"tool_call_id": "c2", "tool_name": "read_file", "status": "success"})
    history.extend([t1, t2])
    observer.sync_messages(history)
    observer.record("model_request", request(history))
    observer.record("model_response", {"tool_calls_requested": [], "usage": {"input_tokens": 10, "output_tokens": 2}})
    history.append(final)
    observer.sync_messages(history)
    observer.record("run_completed", {})
    return history


def test_counters_two_model_calls_many_tool_calls():
    observer = Observer(conversation_id="conv")
    run_fixture_turn(observer)
    assert observer.chat_turn == 1
    assert observer.model_calls == 2
    assert observer.tool_calls == 2
    assert observer.event_seq == 10
    assert observer.status == STATUS_DONE
    assert observer.running_tools == {}
    assert [e["sequence"] for e in observer.events] == list(range(1, 11))
    assert observer.snapshots[1]["usage"] == {"input_tokens": 10, "output_tokens": 2}
    assert observer.snapshots[0]["usage"] is None


def test_new_turn_resets_turn_counters_but_keeps_snapshots():
    observer = Observer(conversation_id="conv")
    history = run_fixture_turn(observer)
    observer.start_turn("run-2")
    assert (observer.chat_turn, observer.model_calls, observer.event_seq, observer.tool_calls) == (2, 0, 0, 0)
    observer.record("user_submitted", {"text": "tiếp"})
    observer.record("model_request", request(history + [HumanMessage(content="tiếp")]))
    assert observer.model_calls == 1
    assert observer.snapshots[-1]["chat_turn"] == 2
    assert len(observer.snapshots) == 3


def test_snapshot_before_and_after_tool_result():
    observer = Observer(conversation_id="conv")
    run_fixture_turn(observer)
    first, second = observer.snapshots
    assert [m["role"] for m in first["messages"]] == ["user"]
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "tool", "tool"]
    assert second["messages"][2]["tool_call_id"] == "c1"
    assert "Weekly report skill body" in second["messages"][2]["content"]
    # System prompt và tools schema nằm ngoài graph messages
    assert second["system_prompt"] == SYSTEM
    assert second["tools"] == TOOLS
    assert all(m["role"] != "system" for m in second["messages"])


def test_snapshot_is_deep_copy():
    observer = Observer(conversation_id="conv")
    data = request([HumanMessage(content="xin chào")])
    observer.start_turn("run-1")
    observer.record("model_request", data)
    data["messages"].append({"role": "user", "content": "mutated"})
    data["messages"][0]["content"] = "mutated"
    data["tools"].clear()
    snap = observer.snapshots[0]
    assert snap["messages"] == [serialize_message(HumanMessage(content="xin chào"))]
    assert snap["tools"] == TOOLS
    assert observer.events[0]["snapshot"]["messages"][0]["content"] == "xin chào"


def test_failed_run_keeps_last_state():
    observer = Observer(conversation_id="conv")
    observer.start_turn("run-1")
    observer.record("model_request", request([HumanMessage(content="x")]))
    observer.record("run_failed", {"error": "APIConnectionError: boom"})
    assert observer.status == STATUS_ERROR and observer.turn_failed
    assert observer.model_calls == 1 and len(observer.snapshots) == 1


def test_skill_inventory_only_from_successful_skill_read():
    observer = Observer(conversation_id="conv")
    assert observer.inventory() == {"skills": [], "resources": []}
    run_fixture_turn(observer)
    inventory = observer.inventory()
    assert [(s["skill"], s["message_index"], s["tool_call_id"]) for s in inventory["skills"]] == [("weekly-report", 2, "c1")]
    assert inventory["skills"][0]["first_request"] == "Lượt 1, model call #2"
    assert [r["path"] for r in inventory["resources"]] == ["data/weekly_notes.md"]


def test_failed_read_and_bash_script_do_not_mark_loaded():
    observer = Observer(conversation_id="conv")
    ai = AIMessage(
        content="",
        tool_calls=[
            {"name": "read_file", "args": {"path": "skills/missing/SKILL.md"}, "id": "e1"},
            {"name": "bash", "args": {"command": "python skills/csv-quality/scripts/check_csv.py --input data/tasks.csv"}, "id": "b1"},
        ],
    )
    failed = read_result("e1", "skills/missing/SKILL.md", ok=False)
    bash = ToolMessage(
        content=json.dumps({"ok": True, "exit_code": 0, "stdout": "{}", "stderr": "", "timed_out": False}),
        tool_call_id="b1",
        name="bash",
    )
    observer.sync_messages([HumanMessage(content="x"), ai, failed, bash])
    assert observer.inventory() == {"skills": [], "resources": []}
