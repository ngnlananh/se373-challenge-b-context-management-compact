"""Ghi trace JSONL cho từng lượt chat và debug log cho exception không mong đợi.

Mỗi dòng là một observer event (đã có sequence). Event model_request kèm snapshot request.
Không ghi API key, headers, environment hay settings.
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


class TraceWriter:
    def __init__(self, traces_dir: Path, project_name: str, conversation_id: str, run_id: str, chat_turn: int):
        traces_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = traces_dir / f"{stamp}_{conversation_id[:8]}_turn{chat_turn:02d}_{run_id[:8]}.jsonl"
        self.project_name = project_name

    def write(self, event: dict[str, Any]) -> None:
        line = {"project_name": self.project_name, **event}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")


def log_exception(traces_dir: Path, exc: BaseException) -> None:
    """Ghi stack trace vào traces/debug.log để debug; UI vẫn hiển thị lỗi."""
    traces_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("lab.debug")
    log_path = str(traces_dir / "debug.log")
    if not any(getattr(h, "baseFilename", None) == log_path for h in logger.handlers):
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    logger.error("".join(traceback.format_exception(exc)))
