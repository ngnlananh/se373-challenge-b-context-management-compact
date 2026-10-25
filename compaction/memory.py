"""Working memory - structured context that must survive compaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
        lines = []
        lines.append("=== WORKING MEMORY (PRESERVED) ===")
        lines.append(f"GOAL: {self.goal or '(not set)'}")
        lines.append(f"ISSUE: {self.current_issue or '(not set)'}")
        if self.error_details:
            lines.append(f"ERROR: {self.error_details}")
        lines.append("")
        lines.append("APPROACHES TRIED:")
        if self.approaches_tried:
            for i, a in enumerate(self.approaches_tried, 1):
                lines.append(f"  {i}. [{a.status.upper()}] {a.approach} -> {a.result or '(pending)'}")
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append("NEXT STEPS:")
        if self.next_steps:
            for i, s in enumerate(self.next_steps, 1):
                lines.append(f"  {i}. {s}")
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
            for a in self.artifacts:
                lines.append(f"  - {a.path}" + (f": {a.description}" if a.description else ""))
        if self.open_questions:
            lines.append("")
            lines.append("OPEN QUESTIONS:")
            for q in self.open_questions:
                lines.append(f"  - {q}")
        lines.append("=== END WORKING MEMORY ===")
        return "\n".join(lines)
