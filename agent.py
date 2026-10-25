"""LangChain agent của stage 03: read_file, write_file, bash + skill catalog trong system prompt."""

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_openai import ChatOpenAI

import paths
from config import MODEL_CALL_LIMIT, TOOL_CALL_LIMIT, Settings
from observer import ObserverMiddleware
from prompts import build_system_prompt
from skill_catalog import Catalog, render_catalog, scan_skills
from tools import bash, read_file, write_file

TOOLS = [read_file, write_file, bash]


def build_model(settings: Settings) -> ChatOpenAI:
    kwargs = {"model": settings.model_name, "api_key": settings.api_key}
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    return ChatOpenAI(**kwargs)


def load_catalog() -> Catalog:
    return scan_skills(paths.WORKSPACE_DIR)


def system_prompt() -> str:
    return build_system_prompt(render_catalog(load_catalog()))


def capabilities() -> dict:
    catalog = load_catalog()
    return {"tools": [t.name for t in TOOLS], "skills": catalog.metadata(), "skill_diagnostics": catalog.diagnostics}


def build_agent(model):
    return create_agent(
        model=model,
        tools=TOOLS,
        system_prompt=system_prompt(),
        middleware=[
            ModelCallLimitMiddleware(run_limit=MODEL_CALL_LIMIT, exit_behavior="end"),
            ToolCallLimitMiddleware(run_limit=TOOL_CALL_LIMIT),
            ObserverMiddleware(),  # cuối danh sách = sát model/tool invocation nhất
        ],
    )
