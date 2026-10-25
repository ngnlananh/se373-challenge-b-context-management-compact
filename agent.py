"""LangChain agent của stage 03: read_file, write_file, bash + skill catalog trong system prompt."""

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

import paths
from compaction import Compactor, CompactionPolicy, WorkingMemory
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

class ContextCompactAgent:
    """Wrapper around the original LangChain agent with selective compaction."""

    def __init__(
        self,
        agent,
        policy: CompactionPolicy | None = None,
        working_memory: WorkingMemory | None = None,
        compaction_count: int = 0,
    ):
        self.agent = agent
        self.policy = policy or CompactionPolicy()
        self.compactor = Compactor(self.policy)
        self.working_memory = working_memory or WorkingMemory()
        self.compaction_count = compaction_count
        self.last_compaction_stats: dict | None = None
        self.last_input_messages: list[BaseMessage] = []

    @staticmethod
    def _to_dict(messages: list[BaseMessage]) -> list[dict]:
        result = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                result.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                result.append({"role": "assistant", "content": msg.content, "tool_calls": msg.tool_calls})
            elif isinstance(msg, ToolMessage):
                result.append({
                    "role": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id,
                    "name": msg.name, "status": msg.status,
                })
            elif isinstance(msg, SystemMessage):
                item = {"role": "system", "content": msg.content}
                if msg.additional_kwargs.get("context_compaction_memory"):
                    item["type"] = "system_memory"
                result.append(item)
            else:
                result.append({"role": getattr(msg, "type", "assistant"), "content": msg.content})
        return result

    @staticmethod
    def _from_dict(messages: list[dict]) -> list[BaseMessage]:
        result = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if msg.get("type") == "system_memory":
                result.append(SystemMessage(
                    content=content,
                    additional_kwargs={"context_compaction_memory": True},
                ))
            elif role == "system":
                result.append(SystemMessage(content=content))
            elif role == "user":
                result.append(HumanMessage(content=content))
            elif role == "tool":
                result.append(ToolMessage(
                    content=content,
                    tool_call_id=msg.get("tool_call_id", "compact"),
                    name=msg.get("name"),
                    status=msg.get("status", "success"),
                ))
            elif role == "assistant":
                result.append(AIMessage(content=content, tool_calls=msg.get("tool_calls", [])))
            else:
                result.append(AIMessage(content=content))
        return result

    def invoke(self, input: dict, config: dict | None = None, **kwargs):
        messages = input.get("messages", []) if isinstance(input, dict) else []
        self.last_compaction_stats = None
        if not isinstance(messages, list) or len(messages) == 0:
            self.last_input_messages = messages
            return self.agent.invoke(input, config=config, **kwargs)
        dict_msgs = self._to_dict(messages)
        total_tokens = sum(self.compactor.estimate_tokens(str(m.get("content", ""))) for m in dict_msgs)
        if self.policy.should_compact(total_tokens, len(dict_msgs)):
            compacted, memory, stats = self.compactor.compact(dict_msgs, self.working_memory)
            self.working_memory = memory
            self.compaction_count += 1
            self.last_compaction_stats = stats
            messages = self._from_dict(compacted)
        self.last_input_messages = messages
        new_input = dict(input)
        new_input["messages"] = messages
        return self.agent.invoke(new_input, config=config, **kwargs)

    def stream(self, input: dict, config: dict | None = None, **kwargs):
        self.last_compaction_stats = None
        messages = input.get("messages", []) if isinstance(input, dict) else []
        if isinstance(messages, list) and len(messages) > 0:
            dict_msgs = self._to_dict(messages)
            total_tokens = sum(self.compactor.estimate_tokens(str(m.get("content", ""))) for m in dict_msgs)
            if self.policy.should_compact(total_tokens, len(dict_msgs)):
                compacted, memory, stats = self.compactor.compact(dict_msgs, self.working_memory)
                self.working_memory = memory
                self.compaction_count += 1
                self.last_compaction_stats = stats
                messages = self._from_dict(compacted)
        self.last_input_messages = messages
        new_input = dict(input)
        new_input["messages"] = messages
        return self.agent.stream(new_input, config=config, **kwargs)
