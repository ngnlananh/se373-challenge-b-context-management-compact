"""Project độc lập: chỉ import stdlib, dependency đã khai báo hoặc module trong chính project."""

import ast
import sys
import tomllib

import paths

ROOT = paths.PROJECT_ROOT
DEPENDENCY_MODULES = {
    "langchain": "langchain",
    "langchain_core": "langchain",
    "langgraph": "langchain",
    "langchain_openai": "langchain-openai",
    "streamlit": "streamlit",
    "dotenv": "python-dotenv",
    "pydantic": "langchain",
    "pytest": "pytest",
    "yaml": "pyyaml",
}


def source_files():
    skip = {".venv", "workspace", "fixtures", "traces"}
    return [p for p in ROOT.rglob("*.py") if not skip.intersection(p.relative_to(ROOT).parts)]


def declared_packages():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    specs = project["project"]["dependencies"] + project["dependency-groups"]["dev"]
    return {spec.split(">")[0].split("=")[0].split("<")[0].strip().lower() for spec in specs}


def test_imports_are_stdlib_declared_or_local():
    local = {p.stem for p in ROOT.glob("*.py")} | {p.name for p in ROOT.iterdir() if (p / "__init__.py").exists()}
    declared = declared_packages()
    for path in source_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"{path}: relative import"
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top in local or top in sys.stdlib_module_names:
                    continue
                assert top in DEPENDENCY_MODULES and DEPENDENCY_MODULES[top] in declared, f"{path}: import {name}"


def test_project_has_only_its_own_modules():
    assert sorted(p.name for p in ROOT.glob("*.py")) == [
        "agent.py",
        "app.py",
        "config.py",
        "observer.py",
        "paths.py",
        "prompts.py",
        "reset_workspace.py",
        "skill_catalog.py",
        "trace.py",
    ]
    assert sorted(p.name for p in (ROOT / "tools").glob("*.py")) == ["__init__.py", "bash.py", "files.py"]
    assert sorted(p.name for p in (ROOT / "fixtures" / "skills").iterdir()) == ["weekly-report"]
    assert sorted(p.name for p in (ROOT / "workspace" / "skills").iterdir()) == ["weekly-report"]
