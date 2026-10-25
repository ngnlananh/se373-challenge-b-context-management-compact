"""Bash tool: cwd workspace, Python của project, exit 0/1, timeout, không lộ credential."""

import json
import sys
import time
from pathlib import Path

from tools import bash
from tools.bash import _run_bash


def test_cwd_is_workspace(tmp_path):
    result = _run_bash("pwd", tmp_path)
    assert result["ok"] is True and result["exit_code"] == 0
    assert Path(result["stdout"].strip()).resolve() == tmp_path.resolve()


def test_python_is_project_interpreter(tmp_path):
    result = _run_bash('python -c "import sys; print(sys.prefix)"', tmp_path)
    assert result["exit_code"] == 0, result
    assert Path(result["stdout"].strip()).resolve() == Path(sys.prefix).resolve()


def test_exit_1_with_stderr_is_readable_result(tmp_path):
    result = _run_bash("python -c \"import sys; print('Lỗi thử nghiệm', file=sys.stderr); sys.exit(1)\"", tmp_path)
    assert result == {"ok": True, "exit_code": 1, "stdout": "", "stderr": "Lỗi thử nghiệm\n", "timed_out": False, "truncated": False}


def test_timeout_kills_process_and_keeps_partial_output(tmp_path):
    started = time.monotonic()
    result = _run_bash("echo bắt-đầu; sleep 5; echo không-tới", tmp_path, timeout=0.5)
    assert time.monotonic() - started < 3
    assert result["ok"] is False and result["exit_code"] is None and result["timed_out"] is True
    assert result["error"]["code"] == "TIMEOUT"
    assert result["stdout"] == "bắt-đầu\n"


def test_credentials_not_in_subprocess_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://secret.example")
    result = _run_bash("env", tmp_path)
    assert result["exit_code"] == 0
    assert "sk-should-not-leak" not in result["stdout"]
    assert "OPENAI" not in result["stdout"]


def test_tool_runs_in_project_workspace(lab_dirs):
    result = json.loads(bash.invoke({"command": "cat data/weekly_notes.md | head -1"}))
    assert result["exit_code"] == 0
    assert result["stdout"].startswith("# Ghi chú công việc tuần 40")
