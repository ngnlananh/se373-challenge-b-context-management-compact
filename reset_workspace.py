"""Khởi tạo hoặc khôi phục workspace từ fixtures của project này.

- ensure_workspace(): app gọi khi khởi động; chỉ copy fixtures khi workspace chưa có (không ghi đè mỗi lần rerun).
- reset_workspace(): `uv run python reset_workspace.py`; chỉ thao tác workspace có marker của lab, giữ traces.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import paths

MARKER_TEXT = "agent-tools-skills-lab workspace\n"


class WorkspaceError(RuntimeError):
    pass


def _has_marker(workspace: Path) -> bool:
    marker = workspace / paths.WORKSPACE_MARKER
    return marker.is_file() and marker.read_text(encoding="utf-8") == MARKER_TEXT


def _populate(workspace: Path, fixtures: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    for child in sorted(fixtures.iterdir()):
        if child.is_dir():
            shutil.copytree(child, workspace / child.name, symlinks=False)
    (workspace / paths.OUTPUT_SUBDIR).mkdir(exist_ok=True)
    (workspace / paths.WORKSPACE_MARKER).write_text(MARKER_TEXT, encoding="utf-8")


def ensure_workspace(workspace: Path | None = None, fixtures: Path | None = None) -> None:
    workspace = workspace or paths.WORKSPACE_DIR
    fixtures = fixtures or paths.FIXTURES_DIR
    if _has_marker(workspace):
        return
    if workspace.exists() and any(workspace.iterdir()):
        raise WorkspaceError(f"{workspace} đã có dữ liệu nhưng thiếu marker {paths.WORKSPACE_MARKER}; không tự ghi đè.")
    _populate(workspace, fixtures)


def reset_workspace(workspace: Path | None = None, fixtures: Path | None = None) -> None:
    workspace = workspace or paths.WORKSPACE_DIR
    fixtures = fixtures or paths.FIXTURES_DIR
    if workspace.is_symlink():
        raise WorkspaceError(f"{workspace} là symlink; không reset.")
    if workspace.exists():
        if not _has_marker(workspace):
            raise WorkspaceError(f"{workspace} thiếu marker {paths.WORKSPACE_MARKER}; không xóa thư mục không thuộc lab.")
        for child in workspace.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    _populate(workspace, fixtures)


if __name__ == "__main__":
    try:
        reset_workspace()
    except WorkspaceError as exc:
        print(f"Không reset: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Đã khôi phục workspace từ fixtures: {paths.WORKSPACE_DIR}")
