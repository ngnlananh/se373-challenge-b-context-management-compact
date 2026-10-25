"""Skill catalog: metadata, initial prompt chỉ có catalog, YAML lỗi, thiếu metadata, trùng name."""

import paths
from agent import system_prompt
from skill_catalog import render_catalog, scan_skills


def write_skill(workspace, folder, text):
    path = workspace / "skills" / folder / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_fixture_catalog_metadata():
    catalog = scan_skills(paths.FIXTURES_DIR)
    assert [(s.name, s.location) for s in catalog.skills] == [("weekly-report", "skills/weekly-report/SKILL.md")]
    assert "báo cáo tuần" in catalog.skills[0].description
    assert catalog.diagnostics == []


def test_initial_prompt_has_catalog_but_no_body_or_reference(lab_dirs):
    prompt = system_prompt()
    skill_text = (paths.WORKSPACE_DIR / "skills/weekly-report/SKILL.md").read_text(encoding="utf-8")
    body = skill_text.split("---", 2)[2].strip()
    template = (paths.WORKSPACE_DIR / "skills/weekly-report/references/report-template.md").read_text(encoding="utf-8")
    assert "<location>skills/weekly-report/SKILL.md</location>" in prompt
    assert "<name>weekly-report</name>" in prompt
    assert body.splitlines()[0] not in prompt
    assert "Phân loại từng ghi chú" not in prompt
    assert template.splitlines()[0] not in prompt
    assert "report-template.md" not in prompt


def test_invalid_yaml_and_missing_metadata_are_skipped_with_diagnostics(tmp_path):
    write_skill(tmp_path, "good", "---\nname: good\ndescription: Một skill tốt\n---\nbody\n")
    write_skill(tmp_path, "bad-yaml", "---\nname: [bad\ndescription: x\n---\n")
    write_skill(tmp_path, "no-desc", "---\nname: no-desc\n---\nbody\n")
    write_skill(tmp_path, "no-frontmatter", "# chỉ có body\n")
    catalog = scan_skills(tmp_path)
    assert [s.name for s in catalog.skills] == ["good"]
    joined = "\n".join(catalog.diagnostics)
    assert "skills/bad-yaml/SKILL.md" in joined and "YAML" in joined
    assert "skills/no-desc/SKILL.md: thiếu description" in joined
    assert "skills/no-frontmatter/SKILL.md" in joined


def test_duplicate_name_reports_error_and_keeps_first(tmp_path):
    write_skill(tmp_path, "a-report", "---\nname: report\ndescription: Bản A\n---\n")
    write_skill(tmp_path, "b-report", "---\nname: report\ndescription: Bản B\n---\n")
    catalog = scan_skills(tmp_path)
    assert [(s.name, s.description) for s in catalog.skills] == [("report", "Bản A")]
    assert any("trùng skill name 'report'" in d and "skills/b-report/SKILL.md" in d for d in catalog.diagnostics)


def test_no_skills_means_no_catalog_block(tmp_path):
    assert render_catalog(scan_skills(tmp_path)) == ""
