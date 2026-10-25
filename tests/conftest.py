"""Fixtures dùng chung cho tests của project này (không cần model thật)."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

import paths
from reset_workspace import ensure_workspace


class ScriptedChatModel(BaseChatModel):
    """Mock model: trả lần lượt các AIMessage đã định sẵn và ghi lại input của mỗi lần gọi."""

    responses: list[AIMessage] = Field(default_factory=list)
    received: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-mock"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.received.append(list(messages))
        if not self.responses:
            raise RuntimeError("ScriptedChatModel: hết response định sẵn")
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


@pytest.fixture
def lab_dirs(tmp_path, monkeypatch):
    """Workspace, trace và .env trỏ vào thư mục tạm để test không đụng dữ liệu thật của project."""
    monkeypatch.setattr(paths, "TRACES_DIR", tmp_path / "traces")
    monkeypatch.setattr(paths, "ENV_PATH", tmp_path / "missing.env")
    monkeypatch.setattr(paths, "WORKSPACE_DIR", tmp_path / "workspace")
    ensure_workspace(paths.WORKSPACE_DIR, paths.FIXTURES_DIR)
    return tmp_path


@pytest.fixture
def configured_env(lab_dirs, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("MODEL_NAME", "mock-model")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    return lab_dirs
