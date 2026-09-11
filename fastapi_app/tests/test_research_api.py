from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_app.middleware.api_key import APIKeyMiddleware
from fastapi_app.routers import research
from fastapi_app.services.research_repository import ResearchRepository


API_HEADERS = {"X-API-Key": "df-internal-2024-workflow-key"}


class FakeCodexService:
    async def status(self):
        return {"available": True, "signed_in": False, "models": [{"id": "test-model"}]}

    async def stream_turn(
        self,
        conversation_id: str,
        prompt: str,
        paper_id: str | None = None,
        history_messages=None,
    ):
        self.history_messages = history_messages or []
        research.repository.add_message(conversation_id, "user", prompt)
        yield {"type": "turn.started", "data": {"turnId": "turn-test", "threadId": "thread-test"}}
        yield {"type": "item/agentMessage/delta", "data": {"delta": "测试回答"}}
        research.repository.add_message(conversation_id, "assistant", "测试回答", turn_id="turn-test")
        yield {"type": "turn/completed", "data": {"status": "completed"}}

    async def cancel(self, conversation_id: str):
        return bool(research.repository.get_conversation(conversation_id))


def build_client(tmp_path: Path, monkeypatch) -> TestClient:
    repository = ResearchRepository(tmp_path / "research")
    monkeypatch.setattr(research, "repository", repository)
    monkeypatch.setattr(research, "codex_service", FakeCodexService())
    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)
    app.include_router(research.router, prefix="/api/v1")
    return TestClient(app)


def test_research_api_end_to_end(tmp_path: Path, monkeypatch) -> None:
    with build_client(tmp_path, monkeypatch) as client:
        assert client.get("/api/v1/research/spaces").status_code == 401

        status = client.get("/api/v1/research/status", headers=API_HEADERS).json()
        assert status["codex"]["available"] is True
        assert status["translation_providers"][0]["available"] is False

        space = client.post(
            "/api/v1/research/spaces",
            headers=API_HEADERS,
            json={"title": "Agent Papers", "description": "local research"},
        ).json()["space"]
        conversation = client.post(
            f"/api/v1/research/spaces/{space['id']}/conversations",
            headers=API_HEADERS,
            json={"title": "Read paper"},
        ).json()["conversation"]
        assert conversation["scope"] == "space"

        idea_conversation = client.post(
            f"/api/v1/research/spaces/{space['id']}/conversations",
            headers=API_HEADERS,
            json={"title": "Idea 讨论", "scope": "idea"},
        ).json()["conversation"]
        assert idea_conversation["scope"] == "idea"
        listed = client.get(
            f"/api/v1/research/spaces/{space['id']}/conversations", headers=API_HEADERS
        ).json()["conversations"]
        assert idea_conversation["id"] in {item["id"] for item in listed}

        with client.stream(
            "POST",
            f"/api/v1/research/conversations/{conversation['id']}/turns",
            headers=API_HEADERS,
            json={"prompt": "请总结这篇论文"},
        ) as response:
            stream_body = "".join(response.iter_text())
        assert response.status_code == 200
        assert "event: item/agentMessage/delta" in stream_body
        assert "测试回答" in stream_body

        messages = client.get(
            f"/api/v1/research/conversations/{conversation['id']}/messages",
            headers=API_HEADERS,
        ).json()["messages"]
        assert [message["role"] for message in messages] == ["user", "assistant"]

        upload = client.post(
            f"/api/v1/research/spaces/{space['id']}/papers/upload",
            headers=API_HEADERS,
            files={"file": ("sample.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")},
        )
        assert upload.status_code == 200
        paper = upload.json()["paper"]
        assert paper["metadata"]["outputs_url"].startswith("/outputs/")
        assert paper["metadata"]["outputs_url"].endswith("/papers/sample.pdf")
        assert Path(paper["stored_path"]).read_bytes().startswith(b"%PDF-")

        binding = client.put(
            f"/api/v1/research/conversations/{conversation['id']}/paper",
            headers=API_HEADERS,
            json={"paper_id": paper["id"]},
        )
        assert binding.status_code == 200
        assert binding.json()["conversation"]["active_paper_id"] == paper["id"]

        wiki = client.post(
            f"/api/v1/research/spaces/{space['id']}/wiki",
            headers=API_HEADERS,
            json={"title": "Evidence Map", "content": "Finding A", "tags": ["paper"]},
        ).json()["page"]
        idea = client.post(
            f"/api/v1/research/spaces/{space['id']}/ideas",
            headers=API_HEADERS,
            json={"title": "Adaptive reading", "problem": "Too much context", "tags": ["agent"]},
        ).json()["idea"]
        assert wiki["revision"] == 1
        assert idea["status"] == "draft"

        job_response = client.post(
            f"/api/v1/research/spaces/{space['id']}/translations",
            headers=API_HEADERS,
            json={"paper_id": paper["id"], "conversation_id": conversation["id"]},
        )
        assert job_response.status_code == 200
        assert job_response.json()["job"]["status"] == "waiting_provider"

        jobs = client.get(
            f"/api/v1/research/spaces/{space['id']}/jobs", headers=API_HEADERS
        ).json()["jobs"]
        assert jobs[0]["input"]["paper_id"] == paper["id"]


def test_message_rollback_and_regeneration_rebuild_codex_history(
    tmp_path: Path, monkeypatch
) -> None:
    with build_client(tmp_path, monkeypatch) as client:
        space = client.post(
            "/api/v1/research/spaces", headers=API_HEADERS, json={"title": "Replay"}
        ).json()["space"]
        conversation = client.post(
            f"/api/v1/research/spaces/{space['id']}/conversations",
            headers=API_HEADERS,
            json={"title": "Paper chat"},
        ).json()["conversation"]
        first_user = research.repository.add_message(conversation["id"], "user", "Question one")
        first_answer = research.repository.add_message(
            conversation["id"], "assistant", "Answer one", turn_id="turn-1"
        )
        research.repository.add_message(conversation["id"], "user", "Question two")
        second_answer = research.repository.add_message(
            conversation["id"], "assistant", "Broken answer", turn_id="turn-2"
        )
        research.repository.set_conversation_runtime(
            conversation["id"], codex_thread_id="thread-old"
        )

        with client.stream(
            "POST",
            f"/api/v1/research/conversations/{conversation['id']}/messages/{second_answer['id']}/regenerate",
            headers=API_HEADERS,
        ) as response:
            body = "".join(response.iter_text())

        assert response.status_code == 200
        assert "测试回答" in body
        messages = research.repository.list_messages(conversation["id"])
        assert [message["content"] for message in messages] == [
            "Question one", "Answer one", "Question two", "测试回答",
        ]
        assert [message["content"] for message in research.codex_service.history_messages] == [
            "Question one", "Answer one",
        ]

        rolled_back = client.post(
            f"/api/v1/research/conversations/{conversation['id']}/messages/{first_answer['id']}/rollback",
            headers=API_HEADERS,
        )
        assert rolled_back.status_code == 200
        assert rolled_back.json()["removed_count"] == 4
        assert rolled_back.json()["messages"] == []
        assert research.repository.get_conversation(conversation["id"])["codex_thread_id"] is None
        assert first_user["id"] not in {row["id"] for row in research.repository.list_messages(conversation["id"])}


def test_failed_regeneration_restores_original_messages_and_thread(
    tmp_path: Path, monkeypatch
) -> None:
    class FailingCodexService(FakeCodexService):
        async def stream_turn(
            self, conversation_id, prompt, paper_id=None, history_messages=None
        ):
            research.repository.add_message(conversation_id, "user", prompt)
            research.repository.add_message(
                conversation_id, "system", "upstream failed", event_type="error"
            )
            yield {"type": "error", "data": {"message": "upstream failed"}}

    with build_client(tmp_path, monkeypatch) as client:
        monkeypatch.setattr(research, "codex_service", FailingCodexService())
        space = research.repository.create_space("Restore")
        conversation = research.repository.create_conversation(space["id"])
        user = research.repository.add_message(conversation["id"], "user", "Keep me")
        answer = research.repository.add_message(
            conversation["id"], "assistant", "Original answer", turn_id="turn-original"
        )
        research.repository.set_conversation_runtime(
            conversation["id"], codex_thread_id="thread-original"
        )

        with client.stream(
            "POST",
            f"/api/v1/research/conversations/{conversation['id']}/messages/{answer['id']}/regenerate",
            headers=API_HEADERS,
        ) as response:
            assert "upstream failed" in "".join(response.iter_text())

        restored = research.repository.list_messages(conversation["id"])
        assert [row["id"] for row in restored] == [user["id"], answer["id"]]
        assert [row["content"] for row in restored] == ["Keep me", "Original answer"]
        assert research.repository.get_conversation(conversation["id"])["codex_thread_id"] == "thread-original"


def test_research_api_rejects_invalid_pdf_and_cross_space_job(tmp_path: Path, monkeypatch) -> None:
    with build_client(tmp_path, monkeypatch) as client:
        first = client.post(
            "/api/v1/research/spaces", headers=API_HEADERS, json={"title": "First"}
        ).json()["space"]
        second = client.post(
            "/api/v1/research/spaces", headers=API_HEADERS, json={"title": "Second"}
        ).json()["space"]

        invalid = client.post(
            f"/api/v1/research/spaces/{first['id']}/papers/upload",
            headers=API_HEADERS,
            files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
        )
        assert invalid.status_code == 400

        linked_paper = client.post(
            f"/api/v1/research/spaces/{first['id']}/papers/link",
            headers=API_HEADERS,
            json={"title": "Metadata paper", "source_url": "https://example.test/paper"},
        ).json()["paper"]
        assert linked_paper["metadata"] == {}

        cross_space = client.post(
            f"/api/v1/research/spaces/{second['id']}/translations",
            headers=API_HEADERS,
            content=json.dumps({"paper_id": linked_paper["id"]}),
        )
        assert cross_space.status_code == 404


def test_blog_resource_conversations_and_delete(tmp_path: Path, monkeypatch) -> None:
    with build_client(tmp_path, monkeypatch) as client:
        space = client.post(
            "/api/v1/research/spaces", headers=API_HEADERS, json={"title": "Blog research"}
        ).json()["space"]
        blog = client.post(
            f"/api/v1/research/spaces/{space['id']}/resources/blog",
            headers=API_HEADERS,
            json={"source_url": "https://example.com", "fetch_content": False},
        ).json()["resource"]
        assert blog["resource_type"] == "blog"
        first = client.post(
            f"/api/v1/research/spaces/{space['id']}/conversations",
            headers=API_HEADERS,
            json={"title": "Blog chat 1"},
        ).json()["conversation"]
        second = client.post(
            f"/api/v1/research/spaces/{space['id']}/conversations",
            headers=API_HEADERS,
            json={"title": "Blog chat 2"},
        ).json()["conversation"]
        for conversation in (first, second):
            response = client.put(
                f"/api/v1/research/conversations/{conversation['id']}/paper",
                headers=API_HEADERS,
                json={"paper_id": blog["id"]},
            )
            assert response.status_code == 200
        linked = client.get(
            f"/api/v1/research/spaces/{space['id']}/conversations",
            params={"resource_id": blog["id"]},
            headers=API_HEADERS,
        ).json()["conversations"]
        assert {item["id"] for item in linked} == {first["id"], second["id"]}
        assert client.delete(
            f"/api/v1/research/conversations/{first['id']}", headers=API_HEADERS
        ).status_code == 200
        assert client.get(
            f"/api/v1/research/conversations/{first['id']}/messages", headers=API_HEADERS
        ).status_code == 404


def test_global_multi_paper_batch_and_note_apis(tmp_path: Path, monkeypatch) -> None:
    async def fake_import(repository, space_id, query, **_kwargs):
        if query == "missing paper":
            raise LookupError("not found")
        paper = repository.add_paper(
            space_id,
            title=f"Resolved {query}",
            source_url=f"https://example.test/{query}",
            availability="metadata_only",
            status="metadata_only",
        )
        return {"paper": paper, "warnings": [], "metadata": {}, "candidates": []}

    monkeypatch.setattr(research, "import_paper", fake_import)
    with build_client(tmp_path, monkeypatch) as client:
        space = client.post(
            "/api/v1/research/spaces", headers=API_HEADERS, json={"title": "Comparison"}
        ).json()["space"]
        first = research.repository.add_paper(space["id"], title="Paper A")
        second = research.repository.add_paper(space["id"], title="Paper B")
        conversation = client.post(
            f"/api/v1/research/spaces/{space['id']}/conversations",
            headers=API_HEADERS,
            json={"title": "Compare", "paper_ids": [first["id"], second["id"]]},
        ).json()["conversation"]
        assert conversation["paper_ids"] == [first["id"], second["id"]]

        swapped = client.put(
            f"/api/v1/research/conversations/{conversation['id']}/papers",
            headers=API_HEADERS,
            json={"paper_ids": [second["id"], first["id"]]},
        ).json()
        assert swapped["conversation"]["active_paper_id"] == second["id"]
        assert [paper["id"] for paper in swapped["papers"]] == [second["id"], first["id"]]

        global_chat = client.post(
            "/api/v1/research/global/conversations",
            headers=API_HEADERS,
            json={"title": "Library assistant"},
        ).json()["conversation"]
        batch = client.post(
            "/api/v1/research/papers/batch-import",
            headers=API_HEADERS,
            json={
                "queries": ["paper one", "missing paper", "paper two"],
                "space_id": space["id"],
                "conversation_id": global_chat["id"],
                "instruction": "把这三篇加入 Comparison",
                "download_pdf": False,
            },
        ).json()
        assert batch["imported_count"] == 2
        assert batch["failed_count"] == 1
        global_messages = client.get(
            f"/api/v1/research/conversations/{global_chat['id']}/messages",
            headers=API_HEADERS,
        ).json()["messages"]
        assert [message["event_type"] for message in global_messages] == [
            "library_action_request",
            "library_action_result",
        ]

        note = client.put(
            f"/api/v1/research/papers/{first['id']}/note",
            headers=API_HEADERS,
            json={"short_summary": "A short memory", "personal_notes": "Compare with B"},
        ).json()["note"]
        assert note["revision"] == 1
        assert client.get(
            f"/api/v1/research/papers/{first['id']}/note", headers=API_HEADERS
        ).json()["note"]["personal_notes"] == "Compare with B"


def test_batch_import_accepts_200_queries_and_rejects_201(tmp_path: Path, monkeypatch) -> None:
    async def fake_import(repository, space_id, query, **_kwargs):
        paper = repository.add_paper(space_id, title=query)
        return {"paper": paper, "warnings": [], "metadata": {}, "candidates": []}

    monkeypatch.setattr(research, "import_paper", fake_import)
    with build_client(tmp_path, monkeypatch) as client:
        space = client.post(
            "/api/v1/research/spaces", headers=API_HEADERS, json={"title": "Large Batch"}
        ).json()["space"]
        queries = [f"Paper {index:03d}" for index in range(200)]

        accepted = client.post(
            "/api/v1/research/papers/batch-import",
            headers=API_HEADERS,
            json={"queries": queries, "space_id": space["id"], "download_pdf": False},
        )
        rejected = client.post(
            "/api/v1/research/papers/batch-import",
            headers=API_HEADERS,
            json={"queries": [*queries, "Paper 200"], "space_id": space["id"]},
        )

        assert accepted.status_code == 200
        assert accepted.json()["imported_count"] == 200
        assert rejected.status_code == 422


def test_global_action_confirmation_and_cancellation_apis(tmp_path: Path, monkeypatch) -> None:
    with build_client(tmp_path, monkeypatch) as client:
        conversation = client.post(
            "/api/v1/research/global/conversations",
            headers=API_HEADERS,
            json={"title": "Function assistant"},
        ).json()["conversation"]
        create_action = research.repository.create_pending_action(
            conversation["id"],
            "create_research_space",
            "新建研究空间《SWE Evolution》",
            {
                "source_conversation_id": conversation["id"],
                "title": "SWE Evolution",
                "description": "",
            },
        )
        cancel_action = research.repository.create_pending_action(
            conversation["id"],
            "create_research_space",
            "新建研究空间《Cancelled》",
            {
                "source_conversation_id": conversation["id"],
                "title": "Cancelled",
                "description": "",
            },
        )

        listed = client.get(
            f"/api/v1/research/conversations/{conversation['id']}/actions",
            headers=API_HEADERS,
        ).json()["actions"]
        assert {row["id"] for row in listed} == {create_action["id"], cancel_action["id"]}

        confirmed = client.post(
            f"/api/v1/research/actions/{create_action['id']}/confirm", headers=API_HEADERS
        ).json()["action"]
        cancelled = client.post(
            f"/api/v1/research/actions/{cancel_action['id']}/cancel", headers=API_HEADERS
        ).json()["action"]

        assert confirmed["status"] == "completed"
        assert confirmed["result"]["space"]["title"] == "SWE Evolution"
        assert cancelled["status"] == "cancelled"
        messages = client.get(
            f"/api/v1/research/conversations/{conversation['id']}/messages",
            headers=API_HEADERS,
        ).json()["messages"]
        assert messages[-1]["event_type"] == "tool_action_result"


def test_global_resource_library_and_space_links(tmp_path: Path, monkeypatch) -> None:
    with build_client(tmp_path, monkeypatch) as client:
        first = client.post(
            "/api/v1/research/spaces", headers=API_HEADERS, json={"title": "SWE"}
        ).json()["space"]
        second = client.post(
            "/api/v1/research/spaces", headers=API_HEADERS, json={"title": "Agents"}
        ).json()["space"]
        created = client.post(
            f"/api/v1/research/spaces/{first['id']}/papers/link",
            headers=API_HEADERS,
            json={
                "title": "Shared",
                "source_url": "https://arxiv.org/abs/1234.5678",
                "metadata": {"arxiv_id": "1234.5678"},
            },
        ).json()["paper"]
        resource_id = created["id"]

        linked = client.post(
            f"/api/v1/research/spaces/{second['id']}/resources/{resource_id}",
            headers=API_HEADERS,
        )
        assert linked.status_code == 200
        assert {space["id"] for space in linked.json()["spaces"]} == {
            first["id"],
            second["id"],
        }
        resources = client.get("/api/v1/research/resources", headers=API_HEADERS)
        assert resources.status_code == 200
        assert [item["id"] for item in resources.json()["resources"]] == [resource_id]
        listed = client.get(
            f"/api/v1/research/spaces/{second['id']}/papers", headers=API_HEADERS
        ).json()["papers"]
        assert [item["id"] for item in listed] == [resource_id]

        removed = client.delete(
            f"/api/v1/research/spaces/{first['id']}/resources/{resource_id}",
            headers=API_HEADERS,
        )
        assert removed.status_code == 200
        assert removed.json()["resource"]["space_ids"] == [second["id"]]
