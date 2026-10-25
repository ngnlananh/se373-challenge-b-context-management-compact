"""File tools: read_file và write_file trong workspace của project.

Path luôn tương đối workspace. Path được resolve (kể cả symlink) rồi kiểm tra vẫn nằm trong
workspace (đọc) hoặc workspace/output (ghi). Lỗi dự kiến trả về JSON {"ok": false, "error": {...}}
để quay lại model như tool result.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool

import paths

MAX_READ_BYTES = 200_000


def _error(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def _resolve(workspace: Path, path: str) -> tuple[Path | None, dict | None]:
    raw = (path or "").strip()
    if not raw:
        return None, _error("INVALID_PATH", "Path rỗng. Dùng đường dẫn tương đối workspace, ví dụ data/weekly_notes.md.")
    if Path(raw).is_absolute() or raw.startswith("~"):
        return None, _error("PATH_OUTSIDE_WORKSPACE", f"Không chấp nhận đường dẫn tuyệt đối: {raw}. Dùng đường dẫn tương đối workspace.")
    root = workspace.resolve()
    target = (root / raw).resolve()
    if not target.is_relative_to(root):
        return None, _error("PATH_OUTSIDE_WORKSPACE", f"Đường dẫn thoát ra ngoài workspace: {raw}")
    return target, None


def _read(workspace: Path, path: str) -> dict:
    target, error = _resolve(workspace, path)
    if error:
        return error
    rel = target.relative_to(workspace.resolve()).as_posix()
    if not target.exists():
        return _error("FILE_NOT_FOUND", f"Không tìm thấy file: {rel}")
    if target.is_dir():
        return _error("IS_A_DIRECTORY", f"Đây là thư mục, không phải file: {rel}")
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        return _error("FILE_TOO_LARGE", f"File {rel} có {size} bytes, vượt giới hạn {MAX_READ_BYTES} bytes. Không đọc một phần.")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _error("NOT_UTF8_TEXT", f"File {rel} không phải văn bản UTF-8.")
    return {"ok": True, "path": rel, "content": content}


def _write(workspace: Path, path: str, content: str) -> dict:
    target, error = _resolve(workspace, path)
    if error:
        return error
    output_root = (workspace / paths.OUTPUT_SUBDIR).resolve()
    if not target.is_relative_to(output_root) or target == output_root:
        return _error("PATH_OUTSIDE_OUTPUT", f"Chỉ được ghi file dưới {paths.OUTPUT_SUBDIR}/ (ví dụ output/summary.md). Path nhận được: {path}")
    rel = target.relative_to(workspace.resolve()).as_posix()
    if target.is_dir():
        return _error("IS_A_DIRECTORY", f"Đây là thư mục, không ghi đè được: {rel}")
    status = "updated" if target.exists() else "created"
    target.parent.mkdir(parents=True, exist_ok=True)
    # mkdir có thể đi qua symlink tạo sau lần resolve đầu; kiểm tra lại trước khi ghi
    if not target.parent.resolve().is_relative_to(output_root):
        return _error("PATH_OUTSIDE_OUTPUT", f"Thư mục đích thoát khỏi {paths.OUTPUT_SUBDIR}/: {path}")
    data = content.encode("utf-8")
    target.write_bytes(data)
    return {"ok": True, "path": rel, "bytes": len(data), "status": status}


@tool
def read_file(path: str) -> str:
    """Đọc một file văn bản UTF-8 trong workspace và trả về JSON.

    path là đường dẫn tương đối workspace, ví dụ: data/weekly_notes.md, output/summary.md.
    Dùng để đọc dữ liệu đầu vào, file SKILL.md của một skill và các file reference trong thư mục skill.
    Thành công: {"ok": true, "path": ..., "content": ...}. Lỗi: {"ok": false, "error": {"code": ..., "message": ...}}.
    """
    return json.dumps(_read(paths.WORKSPACE_DIR, path), ensure_ascii=False)


@tool
def write_file(path: str, content: str) -> str:
    """Ghi nội dung văn bản UTF-8 vào một file dưới output/ của workspace và trả về JSON.

    path là đường dẫn tương đối workspace và phải bắt đầu bằng output/, ví dụ output/summary.md.
    Tự tạo thư mục con. Ghi đè nếu file đã tồn tại.
    Thành công: {"ok": true, "path": ..., "bytes": ..., "status": "created" | "updated"}. Lỗi: {"ok": false, "error": {...}}.
    """
    return json.dumps(_write(paths.WORKSPACE_DIR, path, content), ensure_ascii=False)
