"""Working memory - structured context that must survive compaction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_ACTIONABLE_STEP_START = re.compile(
    r"^(?:(?:please|need to|should|must|to|hãy|cần|nên|phải|tiếp tục)\s+)*"
    r"(?:check|test|validate|inspect|verify|add|write|implement|fix|run|compare|"
    r"reproduce|confirm|review|update|create|try|determine|investigate|parse|handle|"
    r"decide|document|ensure|remove|capture|use|measure|collect|ask|trace|read|look|"
    r"strip|check|kiểm tra|kiểm thử|xác minh|thêm|bổ sung|viết|triển khai|sửa|chạy|"
    r"so sánh|tái hiện|xác nhận|rà soát|cập nhật|tạo|xác định|điều tra|xử lý|"
    r"quyết định|đọc|đo|ghi|làm rõ|tìm|phân tích|đặt|validate)\b",
    re.IGNORECASE,
)


def is_actionable_step(value: str) -> bool:
    """Reject observations and summaries accidentally placed under NEXT STEPS."""
    text = re.sub(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)", "", str(value or ""))
    text = re.sub(r"\*\*(.*?)\*\*|__(.*?)__|`([^`]*)`", lambda m: next(g for g in m.groups() if g is not None), text)
    text = text.strip(" \t*_#:-–—")
    if not text or re.match(r"^(?:#{1,6}\s|(?:step|bước)\s+\d+\b)", text, re.IGNORECASE):
        return False
    return bool(_ACTIONABLE_STEP_START.match(text))


@dataclass
class Attempt:
    """A problem-solving attempt with its outcome."""
    approach: str
    result: str = ""
    status: str = "tried"  # tried, success, failed, partial


@dataclass
class Artifact:
    """Files or resources involved in debugging."""
    path: str
    description: str = ""


@dataclass
class WorkingMemory:
    """Critical context that must be preserved after compaction."""
    goal: str = ""
    current_issue: str = ""
    error_details: str = ""
    approaches_tried: list[Attempt] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "current_issue": self.current_issue,
            "error_details": self.error_details,
            "approaches_tried": [{"approach": a.approach, "result": a.result, "status": a.status} for a in self.approaches_tried],
            "next_steps": self.next_steps,
            "key_decisions": self.key_decisions,
            "facts": self.facts,
            "artifacts": [{"path": a.path, "description": a.description} for a in self.artifacts],
            "open_questions": self.open_questions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkingMemory":
        memory = cls(
            goal=data.get("goal", ""),
            current_issue=data.get("current_issue", ""),
            error_details=data.get("error_details", ""),
            next_steps=data.get("next_steps", []),
            key_decisions=data.get("key_decisions", []),
            facts=data.get("facts", []),
            open_questions=data.get("open_questions", []),
        )
        for a in data.get("approaches_tried", []):
            memory.approaches_tried.append(Attempt(approach=a["approach"], result=a.get("result", ""), status=a.get("status", "tried")))
        for a in data.get("artifacts", []):
            memory.artifacts.append(Artifact(path=a["path"], description=a.get("description", "")))
        return memory

    def render(self) -> str:
        """Render as compact structured text for inclusion in context."""
        def one_line(value: str, *, strip_label: bool = False) -> str:
            # Memory fields are rendered inside a labeled block. A stale value
            # containing newlines can inject duplicate labels or sections.
            value = next((line.strip() for line in str(value or "").splitlines() if line.strip()), "")
            if strip_label:
                for label in ("current issue:", "issue:", "error:", "exception:", "lỗi:"):
                    if value.casefold().startswith(label):
                        value = value[len(label):].strip()
                        break
            return value

        lines = []
        lines.append("=== WORKING MEMORY (PRESERVED) ===")
        lines.append(f"GOAL: {one_line(self.goal) or '(not set)'}")
        lines.append(f"ISSUE: {one_line(self.current_issue, strip_label=True) or '(not set)'}")
        error_details = one_line(self.error_details, strip_label=True)
        if error_details:
            lines.append(f"ERROR: {error_details}")
        lines.append("")
        lines.append("APPROACHES TRIED:")
        if self.approaches_tried:
            for i, a in enumerate(self.approaches_tried, 1):
                approach = one_line(a.approach)
                result = one_line(a.result)
                lines.append(f"  {i}. [{a.status.upper()}] {approach} -> {result or '(pending)'}")
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append("NEXT STEPS:")
        if self.next_steps:
            rendered_steps: list[str] = []
            seen_steps: set[str] = set()
            for s in self.next_steps:
                step = one_line(s)
                if not is_actionable_step(step):
                    continue
                normalized = re.sub(r"\s+", " ", step).strip(" .,:;!?-–—").casefold()
                if normalized and normalized not in seen_steps:
                    seen_steps.add(normalized)
                    rendered_steps.append(step)
            if rendered_steps:
                for i, step in enumerate(rendered_steps, 1):
                    lines.append(f"  {i}. {step}")
            else:
                lines.append("  (none)")
        else:
            lines.append("  (none)")
        if self.key_decisions:
            lines.append("")
            lines.append("KEY DECISIONS:")
            for d in self.key_decisions:
                lines.append(f"  - {d}")
        if self.facts:
            lines.append("")
            lines.append("FACTS:")
            for f in self.facts:
                lines.append(f"  - {f}")
        if self.artifacts:
            lines.append("")
            lines.append("ARTIFACTS:")
            rendered_artifacts: set[str] = set()
            for a in self.artifacts:
                path = one_line(a.path)
                if not path or path.startswith("//") or path in rendered_artifacts:
                    continue
                rendered_artifacts.add(path)
                description = one_line(a.description)
                lines.append(f"  - {path}" + (f": {description}" if description else ""))
            if not rendered_artifacts:
                lines.pop()  # omit the empty ARTIFACTS heading
        if self.open_questions:
            lines.append("")
            lines.append("OPEN QUESTIONS:")
            for q in self.open_questions:
                lines.append(f"  - {q}")
        lines.append("=== END WORKING MEMORY ===")
        return "\n".join(lines)
