"""Bash tool: chạy `bash -c` đồng bộ trong workspace, timeout ngắn, env tối thiểu.

Giới hạn: cwd và env tối thiểu KHÔNG phải sandbox. Lệnh bash vẫn có thể đọc/ghi ngoài workspace
với quyền của user đang chạy app. Chỉ dùng trong môi trường lab với dữ liệu giả.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

import paths

DEFAULT_TIMEOUT_SECONDS = 10
MAX_OUTPUT_CHARS = 20_000
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"


def _windows_path_to_msys(path: str) -> str:
    """Convert a drive-qualified Windows path to the form MSYS Bash expects."""
    normalized = path.replace("\\", "/")
    if len(normalized) >= 2 and normalized[1] == ":":
        return f"/{normalized[0].lower()}{normalized[2:]}"
    return normalized


def _bash_runtime() -> tuple[str, Path | None]:
    """Return a usable Bash executable and, on Windows, its MSYS root."""
    discovered = shutil.which("bash")
    if os.name != "nt":
        return discovered or "bash", None

    # Windows' System32\bash.exe is the WSL launcher. In this project it may
    # be present even when WSL has no accessible distro, so prefer an installed
    # MSYS2 runtime when one is available.
    candidates: list[Path] = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        entry_path = Path(entry)
        if entry_path.name.lower() == "bin" and entry_path.parent.name.lower() == "ucrt64":
            candidates.append(entry_path.parent.parent / "usr" / "bin" / "bash.exe")
    candidates.extend(
        Path(root) / "usr" / "bin" / "bash.exe"
        for root in (r"C:\msys64", r"E:\msys64", r"C:\tools\msys64")
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate), candidate.parent.parent

    if discovered:
        return discovered, None
    raise FileNotFoundError("Không tìm thấy Bash. Trên Windows cần MSYS2 Bash hoặc WSL có distro hoạt động.")


def minimal_env(workspace: Path, msys_root: Path | None = None) -> dict[str, str]:
    """PATH trỏ venv của project trước, locale UTF-8. Không truyền API key hay biến môi trường khác."""
    venv_bin = str(Path(sys.executable).parent)
    locale = os.environ.get("LANG", "")
    if msys_root is not None:
        venv_bin = _windows_path_to_msys(venv_bin)
        home = _windows_path_to_msys(str(workspace))
    else:
        home = str(workspace)
    return {
        "PATH": f"{venv_bin}:{SYSTEM_PATH}",
        "HOME": home,
        "LANG": locale if "UTF-8" in locale.upper() else "C.UTF-8",
        "LC_ALL": locale if "UTF-8" in locale.upper() else "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _clip(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return text[:MAX_OUTPUT_CHARS] + f"\n…[đã cắt, tổng {len(text)} ký tự]", True


def _run_bash(command: str, workspace: Path, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict:
    if not command.strip():
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": "", "timed_out": False,
                "error": {"code": "EMPTY_COMMAND", "message": "Command rỗng."}}
    bash_executable, msys_root = _bash_runtime()
    popen_options = {}
    if os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_options["start_new_session"] = True
    process = subprocess.Popen(
        [bash_executable, "-c", command],  # không login shell, không đọc profile
        cwd=workspace,
        env=minimal_env(workspace, msys_root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **popen_options,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        stdout, out_clipped = _clip(stdout or "")
        stderr, err_clipped = _clip(stderr or "")
        return {
            "ok": False,
            "exit_code": None,
            "stdout": stdout,
            "stderr": stderr,
            "timed_out": True,
            "truncated": out_clipped or err_clipped,
            "error": {"code": "TIMEOUT", "message": f"Command chạy quá {timeout} giây, đã dừng. stdout/stderr là output một phần."},
        }
    stdout, out_clipped = _clip(stdout)
    stderr, err_clipped = _clip(stderr)
    return {
        "ok": True,
        "exit_code": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": False,
        "truncated": out_clipped or err_clipped,
    }


@tool
def bash(command: str) -> str:
    """Chạy một lệnh bash ngắn (bash -c) trong thư mục workspace và trả về JSON.

    cwd là workspace, nên dùng đường dẫn tương đối như data/tasks.csv. `python` là Python của project.
    Timeout 10 giây; không chạy tiến trình nền hay lệnh tương tác.
    Kết quả: {"ok": true, "exit_code": 0, "stdout": "...", "stderr": "", "timed_out": false}.
    ok=true nghĩa là lệnh đã chạy xong và có kết quả; exit_code khác 0 nghĩa là chương trình báo lỗi.
    Timeout: {"ok": false, "exit_code": null, "timed_out": true, ...} kèm output một phần nếu có.
    """
    return json.dumps(_run_bash(command, paths.WORKSPACE_DIR), ensure_ascii=False)
