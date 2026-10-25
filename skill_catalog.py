"""Skill catalog: quét workspace/skills/*/SKILL.md, chỉ lấy metadata cho system prompt.

Catalog chỉ chứa name, description, location (tương đối workspace). Body và reference không vào
context ban đầu; model tự load SKILL.md bằng read_file khi task khớp description.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

import yaml

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    location: str  # tương đối workspace, ví dụ skills/weekly-report/SKILL.md


@dataclass
class Catalog:
    skills: list[SkillMeta] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def metadata(self) -> list[dict]:
        return [asdict(skill) for skill in self.skills]


def parse_frontmatter(text: str) -> dict:
    """Trả dict frontmatter YAML. Raise ValueError nếu thiếu delimiter hoặc YAML sai."""
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("thiếu frontmatter mở đầu bằng ---")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            try:
                data = yaml.safe_load("\n".join(lines[1:index]))
            except yaml.YAMLError as exc:
                raise ValueError(f"YAML không hợp lệ: {exc}") from exc
            if not isinstance(data, dict):
                raise ValueError("frontmatter phải là YAML mapping")
            return data
    raise ValueError("thiếu dòng --- đóng frontmatter")


def scan_skills(workspace: Path) -> Catalog:
    catalog = Catalog()
    skills_dir = workspace / "skills"
    if not skills_dir.is_dir():
        return catalog
    seen: dict[str, str] = {}
    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        location = skill_file.relative_to(workspace).as_posix()
        try:
            meta = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            catalog.diagnostics.append(f"Bỏ qua {location}: {exc}")
            continue
        name = meta.get("name")
        description = meta.get("description")
        if not isinstance(name, str) or not name.strip():
            catalog.diagnostics.append(f"Bỏ qua {location}: thiếu name")
            continue
        if not isinstance(description, str) or not description.strip():
            catalog.diagnostics.append(f"Bỏ qua {location}: thiếu description")
            continue
        name, description = name.strip(), " ".join(description.split())
        if name in seen:
            catalog.diagnostics.append(f"Lỗi: trùng skill name '{name}' ở {location}; giữ {seen[name]}, bỏ qua bản sau.")
            continue
        if name != skill_file.parent.name:
            catalog.diagnostics.append(f"Cảnh báo {location}: name '{name}' khác tên thư mục '{skill_file.parent.name}'.")
        if len(name) > MAX_NAME_LENGTH:
            catalog.diagnostics.append(f"Cảnh báo {location}: name dài hơn {MAX_NAME_LENGTH} ký tự.")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            catalog.diagnostics.append(f"Cảnh báo {location}: description dài hơn {MAX_DESCRIPTION_LENGTH} ký tự.")
        seen[name] = location
        catalog.skills.append(SkillMeta(name=name, description=description, location=location))
    return catalog


def render_catalog(catalog: Catalog) -> str:
    """Khối <available_skills> cho system prompt. Rỗng nếu không có skill."""
    if not catalog.skills:
        return ""
    items = "\n".join(
        "  <skill>\n"
        f"    <name>{escape(skill.name)}</name>\n"
        f"    <description>{escape(skill.description)}</description>\n"
        f"    <location>{escape(skill.location)}</location>\n"
        "  </skill>"
        for skill in catalog.skills
    )
    return f"<available_skills>\n{items}\n</available_skills>"
