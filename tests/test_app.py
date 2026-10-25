"""Streamlit AppTest với mock model: render, thiếu config, history, rerun, snapshot, conversation mới, lỗi."""

import copy

import pytest
from langchain_core.messages import AIMessage
from streamlit.testing.v1 import AppTest

import agent
import paths
from tests.conftest import ScriptedChatModel

APP = str(paths.PROJECT_ROOT / "app.py")
TIMEOUT = 30


def make_app():
    return AppTest.from_file(APP, default_timeout=TIMEOUT)


@pytest.fixture
def mock_model(configured_env, monkeypatch):
    model = ScriptedChatModel(responses=[AIMessage(content="Trả lời 1"), AIMessage(content="Trả lời 2")])
    monkeypatch.setattr(agent, "build_model", lambda settings: model)
    return model


def send(at, text):
    at.chat_input[0].set_value(text).run()
    assert not at.exception, at.exception


def test_missing_config_blocks_model(lab_dirs, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    model = ScriptedChatModel(responses=[AIMessage(content="không được gọi")])
    monkeypatch.setattr(agent, "build_model", lambda settings: model)
    at = make_app().run()
    assert not at.exception
    assert any("OPENAI_API_KEY" in w.value and "MODEL_NAME" in w.value for w in at.warning)
    assert at.chat_input[0].disabled
    assert model.received == []


def test_renders_title_and_state_inspector(configured_env):
    at = make_app().run()
    assert not at.exception
    assert at.title[0].value == "Stage 03: Bash"
    assert "State & Context" in [h.value for h in at.subheader]
    labels = [e.label for e in at.expander]
    assert "Context cấu hình: system prompt" in labels
    assert any(label.startswith("Tools được cấp (3)") for label in labels)
    assert "File đầu ra" in [h.value for h in at.subheader]
    assert any(label.startswith("Skills trong catalog (1)") for label in labels)
    assert any(label.startswith("Skill content đã vào history (0)") for label in labels)
    configured_prompt = [c.value for c in at.code if "<available_skills>" in c.value]
    assert configured_prompt and "Phân loại từng ghi chú" not in configured_prompt[0]


def test_two_turns_history_not_duplicated_and_rerun_does_not_call_model(mock_model):
    at = make_app().run()
    send(at, "Em có thể hỗ trợ gì?")
    observer = at.session_state["observer"]
    assert len(at.session_state["ui_history"]) == 1
    assert len(at.session_state["model_history"]) == 2
    assert (observer.chat_turn, observer.model_calls, observer.tool_calls) == (1, 1, 0)
    assert at.session_state["ui_history"][0]["answer"] == "Trả lời 1"

    events_before = len(observer.events)
    at.run()  # rerun thuần (như khi xem state/tải file)
    assert len(mock_model.received) == 1
    assert len(at.session_state["observer"].events) == events_before

    send(at, "Đọc data/weekly_notes.md và cho biết tuần này đã hoàn thành việc gì.")
    assert len(at.session_state["ui_history"]) == 2
    assert [m.type for m in at.session_state["model_history"]] == ["human", "ai", "human", "ai"]
    assert [m.type for m in mock_model.received[1]] == ["system", "human", "ai", "human"]
    observer = at.session_state["observer"]
    assert (observer.chat_turn, observer.model_calls) == (2, 1)
    assert len(at.chat_message) == 4


def test_select_old_snapshot_is_read_only(mock_model):
    at = make_app().run()
    send(at, "Câu 1")
    send(at, "Câu 2")
    snapshots = copy.deepcopy(at.session_state["observer"].snapshots)
    assert len(snapshots) == 2
    at.selectbox(key="snapshot_choice").set_value(0).run()
    assert not at.exception
    assert at.session_state["observer"].snapshots == snapshots
    assert len(mock_model.received) == 2
    meta = [e for e in at.expander if e.label == "Snapshot: metadata"][0]
    assert meta.json[0].value  # JSON metadata của snapshot đang chọn
    assert '"chat_turn": 1' in meta.json[0].value


def test_new_conversation_resets_state_but_keeps_traces(mock_model):
    at = make_app().run()
    send(at, "Câu 1")
    old_id = at.session_state["conversation_id"]
    traces = sorted(paths.TRACES_DIR.glob("*.jsonl"))
    assert len(traces) == 1
    at.button[0].click().run()
    observer = at.session_state["observer"]
    assert at.session_state["conversation_id"] != old_id
    assert at.session_state["ui_history"] == [] and at.session_state["model_history"] == []
    assert (observer.chat_turn, observer.model_calls, observer.snapshots, observer.messages) == (0, 0, [], [])
    assert sorted(paths.TRACES_DIR.glob("*.jsonl")) == traces


def test_runtime_error_rolls_back_history_and_keeps_trace(configured_env, monkeypatch):
    model = ScriptedChatModel(responses=[])  # gọi model sẽ lỗi
    monkeypatch.setattr(agent, "build_model", lambda settings: model)
    at = make_app().run()
    send(at, "Câu 1")
    observer = at.session_state["observer"]
    assert at.session_state["model_history"] == []
    turn = at.session_state["ui_history"][0]
    assert "hết response" in turn["error"]
    assert [e["type"] for e in turn["events"]] == ["user_submitted", "model_request", "run_failed"]
    assert observer.status == "Lỗi" and observer.model_calls == 1
    assert any("hết response" in e.value for e in at.error)


def test_output_file_preview_does_not_call_agent(configured_env, monkeypatch):
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "output/summary.md", "content": "# Tóm tắt tuần"}, "id": "w1"}]),
            AIMessage(content="Đã ghi."),
        ]
    )
    monkeypatch.setattr(agent, "build_model", lambda settings: model)
    at = make_app().run()
    send(at, "Ghi tóm tắt vào output/summary.md")
    turn = at.session_state["ui_history"][0]
    assert [e["type"] for e in turn["events"] if e["type"].startswith("tool")] == ["tool_started", "tool_finished"]
    assert at.session_state["observer"].tool_calls == 1
    assert at.selectbox(key="output_choice").value == "output/summary.md"
    assert any("Tóm tắt tuần" in m.value for m in at.markdown)

    events_before = len(at.session_state["observer"].events)
    history_before = list(at.session_state["model_history"])
    at.selectbox(key="output_choice").set_value("output/summary.md").run()
    assert len(model.received) == 2
    assert len(at.session_state["observer"].events) == events_before
    assert at.session_state["model_history"] == history_before


def test_skill_load_visible_in_state_and_cleared_by_new_conversation(configured_env, monkeypatch):
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "skills/weekly-report/SKILL.md"}, "id": "s1"}]),
            AIMessage(content="Đã đọc skill."),
        ]
    )
    monkeypatch.setattr(agent, "build_model", lambda settings: model)
    at = make_app().run()
    send(at, "Tạo báo cáo tuần")
    observer = at.session_state["observer"]
    assert [s["skill"] for s in observer.inventory()["skills"]] == ["weekly-report"]
    assert any(e.label.startswith("Skill content đã vào history (1)") for e in at.expander)
    at.button[0].click().run()
    observer = at.session_state["observer"]
    assert observer.inventory()["skills"] == [] and observer.snapshots == []
    assert any(e.label.startswith("Skill content đã vào history (0)") for e in at.expander)
