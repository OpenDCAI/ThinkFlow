from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openai_codex import LocalImageInput, SkillInput, TextInput

from fastapi_app.services.research_codex_service import (
    CODEX_CONFIG_OVERRIDES,
    CODEX_MODEL_PROVIDER,
    PROJECT_SKILLS_ROOT,
    RESEARCH_MCP_TOOL_NAMES,
    READ_PAPER_SKILL_PATH,
    RESEARCH_INSTRUCTIONS,
    ResearchCodexService,
    VISION_PAPER_SKILL_PATH,
)
from fastapi_app.services.research_repository import ResearchRepository


def notification(method: str, payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(method=method, payload=payload)


@dataclass
class FakeTurn:
    notifications: list[SimpleNamespace]
    id: str = "turn-test"
    interrupt_count: int = 0

    async def stream(self):
        for item in self.notifications:
            yield item

    async def interrupt(self) -> None:
        self.interrupt_count += 1


@dataclass
class FakeThread:
    turn_handle: FakeTurn
    id: str = "thread-test"
    last_input: Any = None

    async def turn(self, prompt: Any, **kwargs: Any) -> FakeTurn:
        self.last_input = prompt
        return self.turn_handle


class FakeResearchCodexService(ResearchCodexService):
    def __init__(self, repository: ResearchRepository, turn: FakeTurn) -> None:
        super().__init__(repository)
        self.thread = FakeThread(turn)

    async def _thread(self, conversation: dict[str, Any]) -> FakeThread:
        return self.thread


class SequencedResearchCodexService(ResearchCodexService):
    def __init__(self, repository: ResearchRepository, turns: list[FakeTurn]) -> None:
        super().__init__(repository)
        self.turns = iter(turns)

    async def _thread(self, conversation: dict[str, Any]) -> FakeThread:
        return FakeThread(next(self.turns))


def build_service(tmp_path: Path, turn: FakeTurn):
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Codex tests")
    conversation = repository.create_conversation(space["id"])
    return repository, conversation, FakeResearchCodexService(repository, turn)


def test_research_instructions_allow_autonomous_external_checks() -> None:
    instructions = " ".join(RESEARCH_INSTRUCTIONS.split())

    assert "Decide autonomously whether external web search is needed" in instructions
    assert "Use web search only when current paper discovery is requested" not in instructions
    assert "check, verify, compare, challenge, update, or extend" in instructions
    assert "Do not search merely to restate or translate" in instructions
    assert "Do not add inline citations" in instructions
    assert "available project skills include read-paper for structured paper understanding" in instructions
    assert "vision-paper for figures, tables, plots, and diagrams" in instructions
    assert "review-paper for critique" in instructions
    assert "intent-relevant SkillInput as a candidate capability" in instructions


def test_project_paper_skills_are_installed() -> None:
    assert (PROJECT_SKILLS_ROOT / "read-paper" / "SKILL.md").is_file()
    assert (PROJECT_SKILLS_ROOT / "review-paper" / "SKILL.md").is_file()
    assert (PROJECT_SKILLS_ROOT / "vision-paper" / "SKILL.md").is_file()


def test_paper_turn_input_offers_read_and_vision_skills_by_intent(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Visual input")
    image_path = repository.space_dir(space["id"]) / "papers" / "page-002.png"
    image_path.write_bytes(b"image fixture")
    paper = repository.add_paper(
        space["id"],
        title="Visual Paper",
        metadata={"visual_assets": [{"path": str(image_path), "page": 2}]},
    )
    service = ResearchCodexService(repository)

    turn_input = service._paper_turn_input(
        "[THINKFLOW_ATTACHED_PAPER]fixture[/THINKFLOW_ATTACHED_PAPER]",
        "请总结论文方法，并解释 Figure 1 的架构图",
        paper,
    )

    assert isinstance(turn_input, list)
    assert isinstance(turn_input[0], TextInput)
    assert any(
        isinstance(item, SkillInput)
        and item.name == "read-paper"
        and item.path == str(READ_PAPER_SKILL_PATH)
        for item in turn_input
    )
    assert any(isinstance(item, LocalImageInput) and item.path == str(image_path) for item in turn_input)
    assert any(
        isinstance(item, SkillInput)
        and item.name == "vision-paper"
        and item.path == str(VISION_PAPER_SKILL_PATH)
        for item in turn_input
    )


def test_narrow_paper_question_stays_plain_text(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Narrow question")
    paper = repository.add_paper(space["id"], title="Paper")
    service = ResearchCodexService(repository)

    turn_input = service._paper_turn_input("paper context", "用了什么数据集？", paper)

    assert turn_input == "paper context"


@pytest.mark.asyncio
async def test_attached_paper_turn_leaves_skill_choice_to_codex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turn = FakeTurn(
        [
            notification("item/agentMessage/delta", {"delta": "已完成回答"}),
            notification(
                "turn/completed",
                {"turn": {"id": "turn-test", "status": "completed"}},
            ),
        ]
    )
    repository, conversation, service = build_service(tmp_path, turn)
    paper = repository.add_paper(conversation["space_id"], title="Skill Paper")
    monkeypatch.setattr(
        "fastapi_app.services.research_codex_service.build_paper_context",
        lambda repository, paper: "[THINKFLOW_ATTACHED_PAPER]fixture[/THINKFLOW_ATTACHED_PAPER]",
    )

    events = [
        event
        async for event in service.stream_turn(
            conversation["id"],
            "这篇论文用了什么数据集？",
            paper["id"],
        )
    ]

    assert isinstance(service.thread.last_input, str)
    assert "THINKFLOW_ATTACHED_PAPER" in service.thread.last_input
    assert not any(event["type"] == "turn.skill" for event in events)
    starting_turn = next(
        event
        for event in events
        if event["type"] == "turn.harness"
        and event["data"]["phase"] == "starting_turn"
    )
    assert "自主选择" in starting_turn["data"]["detail"]


@pytest.mark.asyncio
async def test_multi_paper_turn_builds_a_bounded_ordered_research_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turn = FakeTurn(
        [
            notification("item/agentMessage/delta", {"delta": "比较完成"}),
            notification("turn/completed", {"turn": {"id": "turn-test", "status": "completed"}}),
        ]
    )
    repository, conversation, service = build_service(tmp_path, turn)
    first = repository.add_paper(conversation["space_id"], title="Paper A")
    second = repository.add_paper(conversation["space_id"], title="Paper B")
    repository.set_conversation_resources(conversation["id"], [second["id"], first["id"]])
    monkeypatch.setattr(
        "fastapi_app.services.research_codex_service.build_paper_context",
        lambda repository, paper: f"[THINKFLOW_ATTACHED_PAPER]{paper['title']}[/THINKFLOW_ATTACHED_PAPER]",
    )

    events = [
        event
        async for event in service.stream_turn(
            conversation["id"], "请比较论文的方法与实验"
        )
    ]

    assert isinstance(service.thread.last_input, list)
    text_input = next(item for item in service.thread.last_input if isinstance(item, TextInput))
    assert text_input.text.index("Paper B") < text_input.text.index("Paper A")
    assert text_input.text.count("[RESOURCE ") == 2
    assert text_input.text.count("[/RESOURCE ") == 2
    assert text_input.text.startswith("[THINKFLOW_ATTACHED_RESEARCH_SET]")
    read_skills = [
        item for item in service.thread.last_input
        if isinstance(item, SkillInput) and item.name == "read-paper"
    ]
    assert len(read_skills) == 1
    context_ready = next(
        event for event in events
        if event["type"] == "turn.harness" and event["data"]["phase"] == "context_ready"
    )
    assert "Paper B" in context_ready["data"]["detail"]
    assert "Paper A" in context_ready["data"]["detail"]


def test_paper_note_parser_keeps_structured_sections() -> None:
    sections = ResearchCodexService._paper_note_sections(
        """## 简短摘要
Summary

## QA 摘要
Questions

## 未决问题
- Open

## 关键结论
- Result

## 个人记录与启发
Idea"""
    )

    assert sections == {
        "short_summary": "Summary",
        "qa_summary": "Questions",
        "open_questions": "- Open",
        "key_takeaways": "- Result",
        "personal_notes": "Idea",
    }


@pytest.mark.asyncio
async def test_runtime_skill_event_is_forwarded_without_application_routing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turn = FakeTurn(
        [
            notification(
                "item/started",
                {"item": {"type": "skill", "name": "read-paper", "path": "/skills/read-paper/SKILL.md"}},
            ),
            notification("item/agentMessage/delta", {"delta": "已使用 Skill"}),
            notification("turn/completed", {"turn": {"id": "turn-test", "status": "completed"}}),
        ]
    )
    repository, conversation, service = build_service(tmp_path, turn)
    paper = repository.add_paper(conversation["space_id"], title="Runtime skill paper")
    monkeypatch.setattr(
        "fastapi_app.services.research_codex_service.build_paper_context",
        lambda repository, paper: "[THINKFLOW_ATTACHED_PAPER]fixture[/THINKFLOW_ATTACHED_PAPER]",
    )

    events = [
        event async for event in service.stream_turn(conversation["id"], "请读懂这篇论文", paper["id"])
    ]

    skill_event = next(event for event in events if event["type"] == "turn.skill")
    assert skill_event["data"]["name"] == "read-paper"
    assert skill_event["data"]["status"] == "loaded"


@pytest.mark.asyncio
async def test_mcp_tool_lifecycle_is_forwarded_to_frontend(tmp_path: Path) -> None:
    started = {
        "type": "mcpToolCall",
        "id": "tool-1",
        "server": "thinkflow_research",
        "tool": "list_research_spaces",
        "arguments": {"limit": 10},
        "status": "inProgress",
    }
    completed = {**started, "status": "completed"}
    turn = FakeTurn(
        [
            notification("item/started", {"item": started}),
            notification("item/completed", {"item": completed}),
            notification("item/agentMessage/delta", {"delta": "找到研究空间"}),
            notification("turn/completed", {"turn": {"id": "turn-test", "status": "completed"}}),
        ]
    )
    repository, conversation, service = build_service(tmp_path, turn)

    events = [event async for event in service.stream_turn(conversation["id"], "列出空间")]
    tool_events = [event for event in events if event["type"] == "turn.tool"]

    assert [event["data"]["status"] for event in tool_events] == ["inProgress", "completed"]
    assert tool_events[0]["data"]["name"] == "list_research_spaces"


@pytest.mark.asyncio
async def test_global_thread_registers_research_mcp_only_for_global_scope(tmp_path: Path) -> None:
    class Thread:
        id = "thread-mcp"

        async def set_name(self, _name: str) -> None:
            return None

    class Runtime:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def thread_start(self, **kwargs: Any) -> Thread:
            self.calls.append(kwargs)
            return Thread()

    repository = ResearchRepository(tmp_path / "research")
    global_chat = repository.create_global_conversation()
    space = repository.create_space("Local")
    local_chat = repository.create_conversation(space["id"])
    runtime = Runtime()
    service = ResearchCodexService(repository)
    service._codex = runtime  # type: ignore[assignment]

    await service._thread(global_chat)
    await service._thread(local_chat)

    global_config = runtime.calls[0]["config"]
    local_config = runtime.calls[1]["config"]
    server = global_config["mcp_servers"]["thinkflow_research"]
    assert server["enabled_tools"] == list(RESEARCH_MCP_TOOL_NAMES)
    assert server["env"]["THINKFLOW_RESEARCH_ROOT"] == str(repository.root)
    assert global_chat["id"] in runtime.calls[0]["developer_instructions"]
    assert "mcp_servers" not in local_config


@pytest.mark.asyncio
async def test_skill_input_echo_is_not_reported_as_runtime_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    turn = FakeTurn(
        [
            notification(
                "item/started",
                {
                    "item": {
                        "type": "userMessage",
                        "content": [
                            {
                                "type": "skill",
                                "name": "read-paper",
                                "path": str(READ_PAPER_SKILL_PATH),
                            }
                        ],
                    }
                },
            ),
            notification("item/agentMessage/delta", {"delta": "回答"}),
            notification("turn/completed", {"turn": {"id": "turn-test", "status": "completed"}}),
        ]
    )
    repository, conversation, service = build_service(tmp_path, turn)
    paper = repository.add_paper(conversation["space_id"], title="Skill echo")
    monkeypatch.setattr(
        "fastapi_app.services.research_codex_service.build_paper_context",
        lambda repository, paper: "[THINKFLOW_ATTACHED_PAPER]fixture[/THINKFLOW_ATTACHED_PAPER]",
    )

    events = [
        event async for event in service.stream_turn(conversation["id"], "请总结这篇论文", paper["id"])
    ]

    provided = next(event for event in events if event["type"] == "turn.skill")
    assert provided["data"]["status"] == "provided"
    assert provided["data"]["name"] == "read-paper"


@pytest.mark.asyncio
async def test_codex_start_registers_project_skill_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[tuple[str, dict[str, Any], Any]] = []

    class FakeRpcClient:
        async def request(self, method: str, params: dict[str, Any], *, response_model: Any):
            requests.append((method, params, response_model))
            if method == "skills/list":
                return response_model.model_validate(
                    {
                        "data": [
                            {
                                "cwd": str(Path.cwd()),
                                "errors": [],
                                "skills": [
                                    {
                                        "name": "read-paper",
                                        "path": str(PROJECT_SKILLS_ROOT / "read-paper" / "SKILL.md"),
                                        "description": "Read papers",
                                        "enabled": True,
                                        "scope": "user",
                                    }
                                ],
                            }
                        ]
                    }
                )
            return response_model()

    class FakeCodex:
        def __init__(self, config: Any) -> None:
            self.config = config
            self._client = FakeRpcClient()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
            return None

    monkeypatch.setattr(
        "fastapi_app.services.research_codex_service.AsyncCodex", FakeCodex
    )
    repository = ResearchRepository(tmp_path / "research")
    service = ResearchCodexService(repository)

    codex = await service.start()

    assert isinstance(codex, FakeCodex)
    assert requests[0][0] == "skills/extraRoots/set"
    assert requests[0][1] == {"extraRoots": [str(PROJECT_SKILLS_ROOT)]}
    assert requests[1][0] == "skills/list"
    assert requests[1][1]["forceReload"] is True
    assert (await service.skills())["skills"][0]["name"] == "read-paper"


def test_codex_runtime_enables_standalone_search_for_its_provider() -> None:
    assert (
        f"model_providers.{CODEX_MODEL_PROVIDER}.supports_standalone_web_search=true"
        in CODEX_CONFIG_OVERRIDES
    )
    assert "features.standalone_web_search=true" in CODEX_CONFIG_OVERRIDES


def test_turn_error_extracts_nested_upstream_message() -> None:
    message = '{"error":{"message":"Upstream request failed","type":"upstream_error"}}'

    assert ResearchCodexService._turn_error({"error": {"message": message}}) == (
        "Upstream request failed"
    )


@pytest.mark.asyncio
async def test_retry_notification_is_nonfatal_and_answer_is_saved(tmp_path: Path) -> None:
    turn = FakeTurn(
        [
            notification(
                "error",
                {
                    "error": {"message": "stream disconnected before completion"},
                    "willRetry": True,
                },
            ),
            notification("item/agentMessage/delta", {"delta": "已恢复"}),
            notification(
                "turn/completed",
                {"turn": {"id": "turn-test", "status": "completed"}},
            ),
        ]
    )
    repository, conversation, service = build_service(tmp_path, turn)

    events = [event async for event in service.stream_turn(conversation["id"], "继续")]

    event_types = [event["type"] for event in events]
    assert event_types[0] == "turn.harness"
    assert events[0]["data"]["phase"] == "queued"
    assert event_types.count("turn.harness") >= 5
    assert event_types.index("turn.started") < event_types.index("item/agentMessage/delta")
    assert any(
        event["type"] == "turn.harness" and event["data"]["phase"] == "streaming"
        for event in events
    )
    assert events[-1]["type"] == "turn/completed"
    assert events[-2]["data"]["phase"] == "completed"
    assert [message["role"] for message in repository.list_messages(conversation["id"])] == [
        "user",
        "assistant",
    ]
    assert repository.get_conversation(conversation["id"])["status"] == "idle"
    assert turn.interrupt_count == 0


@pytest.mark.asyncio
async def test_closing_stream_interrupts_once_and_clears_running_status(tmp_path: Path) -> None:
    turn = FakeTurn([])
    repository, conversation, service = build_service(tmp_path, turn)
    stream = service.stream_turn(conversation["id"], "开始")

    queued = await anext(stream)
    assert queued["type"] == "turn.harness"
    assert queued["data"]["phase"] == "queued"
    assert repository.get_conversation(conversation["id"])["status"] == "running"

    while True:
        event = await anext(stream)
        if event["type"] == "turn.started":
            break

    await stream.aclose()

    assert turn.interrupt_count == 1
    assert repository.get_conversation(conversation["id"])["status"] == "idle"
    assert conversation["id"] not in service._active_turns


@pytest.mark.asyncio
async def test_harness_reports_thread_turn_and_completion_lifecycle(tmp_path: Path) -> None:
    turn = FakeTurn(
        [
            notification("item/agentMessage/delta", {"delta": "已开始回答"}),
            notification(
                "turn/completed",
                {"turn": {"id": "turn-test", "status": "completed"}},
            ),
        ]
    )
    repository, conversation, service = build_service(tmp_path, turn)

    events = [event async for event in service.stream_turn(conversation["id"], "请回答")]
    harnesses = [event["data"] for event in events if event["type"] == "turn.harness"]

    assert [item["phase"] for item in harnesses] == [
        "queued",
        "starting_thread",
        "starting_turn",
        "waiting_for_response",
        "streaming",
        "completed",
    ]
    waiting = next(item for item in harnesses if item["phase"] == "waiting_for_response")
    assert waiting["threadId"] == "thread-test"
    assert waiting["turnId"] == "turn-test"
    assert harnesses[-1]["title"] == "回复已完成"


@pytest.mark.asyncio
async def test_failed_turn_clears_thread_and_records_error(tmp_path: Path) -> None:
    nested_error = '{"error":{"message":"Upstream request failed"}}'
    turn = FakeTurn(
        [
            notification(
                "error",
                {"error": {"message": nested_error}, "willRetry": False},
            ),
            notification(
                "turn/completed",
                {
                    "turn": {
                        "id": "turn-test",
                        "status": "failed",
                        "error": {"message": nested_error},
                    }
                },
            ),
        ]
    )
    repository, conversation, service = build_service(tmp_path, turn)
    repository.set_conversation_runtime(
        conversation["id"], codex_thread_id="thread-stale"
    )

    events = [event async for event in service.stream_turn(conversation["id"], "重试")]

    assert any(
        event["type"] == "error" and event["data"]["message"] == "Upstream request failed"
        for event in events
    )
    updated = repository.get_conversation(conversation["id"])
    assert updated["status"] == "error"
    assert updated["codex_thread_id"] == ""
    messages = repository.list_messages(conversation["id"])
    assert [message["role"] for message in messages] == ["user", "system"]
    assert messages[-1]["content"] == "Upstream request failed"
    assert turn.interrupt_count == 0


@pytest.mark.asyncio
async def test_transient_upstream_failure_retries_with_a_new_turn(tmp_path: Path) -> None:
    nested_error = '{"error":{"message":"Upstream request failed"}}'
    failed = FakeTurn(
        [
            notification(
                "error",
                {"error": {"message": nested_error}, "willRetry": False},
            ),
            notification(
                "turn/completed",
                {
                    "turn": {
                        "id": "turn-test",
                        "status": "failed",
                        "error": {"message": nested_error},
                    }
                },
            ),
        ],
        id="turn-first",
    )
    succeeded = FakeTurn(
        [
            notification("item/agentMessage/delta", {"delta": "重试成功"}),
            notification(
                "turn/completed",
                {"turn": {"id": "turn-second", "status": "completed"}},
            ),
        ],
        id="turn-second",
    )
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Retry")
    conversation = repository.create_conversation(space["id"])
    service = SequencedResearchCodexService(repository, [failed, succeeded])

    events = [event async for event in service.stream_turn(conversation["id"], "继续")]

    assert [event["type"] for event in events].count("turn.started") == 2
    assert any(
        event["type"] == "turn.retrying"
        and event["data"]["attempt"] == 2
        and event["data"]["reset"] is True
        for event in events
    )
    assert not any(event["type"] == "error" for event in events)
    assert events[-1]["type"] == "turn/completed"
    assert events[-2]["type"] == "turn.harness"
    assert events[-2]["data"]["phase"] == "completed"
    messages = repository.list_messages(conversation["id"])
    assert [(message["role"], message["content"]) for message in messages] == [
        ("user", "继续"),
        ("assistant", "重试成功"),
    ]
    assert repository.get_conversation(conversation["id"])["status"] == "idle"
