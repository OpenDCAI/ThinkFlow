from __future__ import annotations

from pathlib import Path

import pytest

from fastapi_app.services.research_repository import ResearchRepository
from fastapi_app.services.research_tools.executor import ResearchToolExecutor
from fastapi_app.services.research_tools.mcp_server import ResearchMcpServer
from fastapi_app.services.research_tools.registry import TOOL_SPECS


@pytest.mark.asyncio
async def test_read_tools_search_spaces_resources_and_conversations(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    swe = repository.create_space("SWE Agent 演进", "软件工程智能体")
    repository.create_space("Multimodal")
    paper = repository.add_paper(
        swe["id"],
        title="SWE-bench",
        metadata={"arxiv_id": "2310.06770", "authors": [{"name": "Jimenez"}]},
    )
    conversation = repository.create_conversation(
        swe["id"], "Benchmark", scope="paper", paper_ids=[paper["id"]]
    )
    executor = ResearchToolExecutor(repository)

    spaces = await executor.execute_tool("search_research_spaces", {"query": "软件工程"})
    resources = await executor.execute_tool(
        "list_space_resources", {"space_id": swe["id"], "query": "2310.06770"}
    )
    conversations = await executor.execute_tool(
        "list_research_conversations", {"space_id": swe["id"], "resource_id": paper["id"]}
    )
    bindings = await executor.execute_tool(
        "get_conversation_resources", {"conversation_id": conversation["id"]}
    )

    assert [row["id"] for row in spaces["spaces"]] == [swe["id"]]
    assert resources["resources"][0]["id"] == paper["id"]
    assert conversations["conversations"][0]["id"] == conversation["id"]
    assert bindings["resources"][0]["title"] == "SWE-bench"


@pytest.mark.asyncio
async def test_write_tool_prepares_then_idempotently_confirms_action(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    global_chat = repository.create_global_conversation()
    executor = ResearchToolExecutor(repository)

    prepared = await executor.execute_tool(
        "create_research_space",
        {
            "source_conversation_id": global_chat["id"],
            "title": "SWE Evolution",
            "description": "Track agent systems",
        },
    )

    assert prepared["requires_confirmation"] is True
    assert repository.list_spaces() == []
    completed = await executor.execute_pending_action(prepared["action"]["id"])
    repeated = await executor.execute_pending_action(prepared["action"]["id"])

    assert completed["status"] == "completed"
    assert repeated["id"] == completed["id"]
    assert repository.list_spaces()[0]["title"] == "SWE Evolution"
    assert repository.list_messages(global_chat["id"])[0]["event_type"] == "tool_action_result"


@pytest.mark.asyncio
async def test_mcp_write_tool_executes_explicit_global_command_directly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("THINKFLOW_RESEARCH_ROOT", str(tmp_path / "research"))
    server = ResearchMcpServer()
    global_chat = server.executor.repository.create_global_conversation()

    response = await server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "create_research_space",
                "arguments": {
                    "source_conversation_id": global_chat["id"],
                    "title": "Direct MCP Space",
                    "description": "Created from natural language",
                },
            },
        }
    )

    result = response["result"]["structuredContent"]
    assert result["executed"] is True
    assert result["requires_confirmation"] is False
    assert server.executor.repository.list_spaces()[0]["title"] == "Direct MCP Space"
    assert server.executor.repository.list_pending_actions(global_chat["id"]) == []


@pytest.mark.asyncio
async def test_confirmed_import_can_create_space_conversation_and_bind_resources(
    tmp_path: Path,
) -> None:
    repository = ResearchRepository(tmp_path / "research")
    global_chat = repository.create_global_conversation()

    async def fake_import(repository, space_id, query, **_kwargs):
        if query == "missing":
            raise LookupError("not found")
        paper = repository.add_paper(space_id, title=f"Resolved {query}")
        return {"paper": paper, "warnings": []}

    executor = ResearchToolExecutor(repository, import_paper_fn=fake_import)
    prepared = await executor.execute_tool(
        "import_research_resources",
        {
            "source_conversation_id": global_chat["id"],
            "queries": ["Paper A", "missing", "Paper B"],
            "new_space_title": "Comparison",
            "download_fulltext": False,
            "new_conversation_title": "Compare A and B",
        },
    )
    completed = await executor.execute_pending_action(prepared["action"]["id"])
    result = completed["result"]

    assert result["imported_count"] == 2
    assert result["failed_count"] == 1
    assert result["conversation"]["resource_count"] == 2
    assert len(repository.list_conversation_resources(result["conversation"]["id"])) == 2


def test_registry_exposes_ten_bounded_research_functions() -> None:
    assert len(TOOL_SPECS) == 10
    assert TOOL_SPECS["list_research_spaces"].read_only is True
    assert TOOL_SPECS["import_research_resources"].read_only is False
    schema = TOOL_SPECS["import_research_resources"].mcp_definition()["inputSchema"]
    assert schema["properties"]["queries"]["maxItems"] == 200
