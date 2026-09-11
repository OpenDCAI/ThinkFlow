from __future__ import annotations

from pathlib import Path

from fastapi_app.services.research_repository import ResearchRepository


def test_research_space_conversation_and_messages(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")

    space = repository.create_space("Agent Papers", "local research")
    conversation = repository.create_conversation(space["id"], "Read paper")
    repository.add_message(conversation["id"], "user", "Summarize the paper")
    repository.add_message(conversation["id"], "assistant", "Summary", turn_id="turn-1")

    assert repository.list_spaces()[0]["title"] == "Agent Papers"
    assert repository.list_conversations(space["id"])[0]["title"] == "Read paper"
    assert [message["role"] for message in repository.list_messages(conversation["id"])] == [
        "user",
        "assistant",
    ]
    assert repository.thread_dir(space["id"], conversation["id"]).joinpath("README.md").exists()


def test_message_regeneration_snapshot_can_restore_a_removed_branch(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Replay")
    conversation = repository.create_conversation(space["id"])
    first_user = repository.add_message(conversation["id"], "user", "First question")
    first_answer = repository.add_message(conversation["id"], "assistant", "First answer")
    second_user = repository.add_message(conversation["id"], "user", "Second question")
    second_answer = repository.add_message(conversation["id"], "assistant", "Broken answer")
    repository.set_conversation_runtime(conversation["id"], codex_thread_id="thread-before")

    snapshot = repository.prepare_message_regeneration(conversation["id"], second_answer["id"])

    assert snapshot["prompt"] == "Second question"
    assert [row["id"] for row in snapshot["history"]] == [first_user["id"], first_answer["id"]]
    assert [row["id"] for row in repository.list_messages(conversation["id"])] == [
        first_user["id"], first_answer["id"],
    ]
    assert repository.get_conversation(conversation["id"])["codex_thread_id"] is None

    repository.add_message(conversation["id"], "user", "Temporary retry")
    repository.restore_message_regeneration(snapshot)

    assert [row["id"] for row in repository.list_messages(conversation["id"])] == [
        first_user["id"], first_answer["id"], second_user["id"], second_answer["id"],
    ]
    assert repository.get_conversation(conversation["id"])["codex_thread_id"] == "thread-before"


def test_wiki_and_idea_keep_markdown_as_artifact(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Knowledge")

    page = repository.save_wiki(
        space["id"],
        title="Evidence Map",
        content="Links the main findings.",
        tags=["evidence", "paper"],
    )
    updated = repository.save_wiki(
        space["id"],
        page_id=page["id"],
        title="Evidence Map",
        content="Updated findings.",
        tags=["evidence"],
    )
    idea = repository.save_idea(
        space["id"],
        {"title": "Adaptive retrieval", "problem": "Static retrieval is noisy", "tags": ["rag"]},
    )

    assert updated["revision"] == 2
    assert repository.list_wiki(space["id"], "Updated")[0]["id"] == page["id"]
    assert (repository.space_dir(space["id"]) / "wiki" / "Evidence-Map.md").read_text(encoding="utf-8").endswith("Updated findings.\n")
    idea_markdown = repository.space_dir(space["id"]) / "ideas" / f"{idea['id']}.md"
    assert "Static retrieval is noisy" in idea_markdown.read_text(encoding="utf-8")


def test_translation_job_waits_for_a_provider(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Translation")
    paper = repository.add_paper(space["id"], title="Paper", stored_path="/tmp/paper.pdf")

    job = repository.create_job(
        space["id"],
        kind="paper_translation",
        provider="unconfigured",
        input_data={"paper_id": paper["id"], "target_language": "zh-CN"},
    )

    assert job["status"] == "waiting_provider"
    assert job["input"]["paper_id"] == paper["id"]
    assert repository.list_jobs(space["id"])[0]["provider"] == "unconfigured"


def test_conversation_can_bind_a_paper(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Paper chat")
    conversation = repository.create_conversation(space["id"])
    paper = repository.add_paper(space["id"], title="Paper")

    updated = repository.bind_conversation_paper(conversation["id"], paper["id"])

    assert updated is not None
    assert updated["active_paper_id"] == paper["id"]


def test_idea_scope_survives_conversation_listing(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Scopes")
    paper = repository.add_paper(space["id"], title="Paper")
    paper_chat = repository.create_conversation(space["id"], paper_ids=[paper["id"]])
    idea_chat = repository.create_conversation(space["id"], "Idea 讨论", scope="idea")

    assert paper_chat["scope"] == "space"
    listed = repository.list_conversations(space["id"])
    assert {row["id"] for row in listed} == {paper_chat["id"], idea_chat["id"]}


def test_repository_recovers_running_conversations_after_restart(tmp_path: Path) -> None:
    root = tmp_path / "research"
    repository = ResearchRepository(root)
    space = repository.create_space("Recovery")
    conversation = repository.create_conversation(space["id"])
    repository.set_conversation_runtime(conversation["id"], status="running")

    restarted = ResearchRepository(root)

    assert restarted.get_conversation(conversation["id"])["status"] == "idle"


def test_resource_conversations_and_delete_remove_thread(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Resources")
    resource = repository.add_paper(space["id"], title="A blog", resource_type="blog")
    first = repository.create_conversation(space["id"], "First")
    second = repository.create_conversation(space["id"], "Second")
    repository.bind_conversation_paper(first["id"], resource["id"])
    repository.bind_conversation_paper(second["id"], resource["id"])
    repository.add_message(first["id"], "user", "hello")
    thread = repository.thread_dir(space["id"], first["id"])

    assert len(repository.list_conversations(space["id"], resource["id"])) == 2
    assert repository.delete_conversation(first["id"])
    assert repository.get_conversation(first["id"]) is None
    assert repository.list_messages(first["id"]) == []
    assert not thread.exists()
    assert repository.get_conversation(second["id"]) is not None


def test_global_conversations_are_hidden_from_research_spaces(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Visible space")
    global_chat = repository.create_global_conversation("Cross-space research")

    assert [row["id"] for row in repository.list_spaces()] == [space["id"]]
    assert repository.list_global_conversations()[0]["id"] == global_chat["id"]
    assert global_chat["scope"] == "global"
    assert repository.get_space(global_chat["space_id"])["scope"] == "system"


def test_conversation_resources_keep_order_and_support_resource_history(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Comparative reading")
    first = repository.add_paper(space["id"], title="Paper A")
    second = repository.add_paper(space["id"], title="Paper B")
    conversation = repository.create_conversation(
        space["id"], "Compare", scope="paper", paper_ids=[second["id"], first["id"]]
    )

    assert conversation["paper_ids"] == [second["id"], first["id"]]
    assert conversation["active_paper_id"] == second["id"]
    assert [row["id"] for row in repository.list_conversation_resources(conversation["id"])] == [
        second["id"],
        first["id"],
    ]
    assert repository.list_conversations(space["id"], first["id"])[0]["id"] == conversation["id"]


def test_paper_note_tracks_qa_sources_and_revisions(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Paper memory")
    paper = repository.add_paper(space["id"], title="Memory Paper")
    conversation = repository.create_conversation(space["id"], paper_ids=[paper["id"]])
    message = repository.add_message(conversation["id"], "user", "What is still unclear?")

    first = repository.save_paper_note(
        paper["id"],
        short_summary="Short",
        open_questions="Question",
        source_message_ids=[message["id"]],
    )
    second = repository.save_paper_note(
        paper["id"],
        short_summary="Updated",
        source_message_ids=[message["id"]],
    )

    assert first["revision"] == 1
    assert second["revision"] == 2
    assert second["source_message_ids"] == [message["id"]]
    assert repository.list_paper_messages(paper["id"])[0]["id"] == message["id"]


def test_pending_action_lifecycle_is_persistent_and_cancellable(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    conversation = repository.create_global_conversation()
    first = repository.create_pending_action(
        conversation["id"],
        "create_research_space",
        "新建研究空间《Agents》",
        {"title": "Agents"},
    )
    second = repository.create_pending_action(
        conversation["id"],
        "create_research_space",
        "新建研究空间《Systems》",
        {"title": "Systems"},
    )

    assert repository.claim_pending_action(first["id"])["status"] == "executing"
    assert repository.finish_pending_action(
        first["id"], status="completed", result={"success": True}
    )["result"] == {"success": True}
    assert repository.cancel_pending_action(second["id"])["status"] == "cancelled"
    assert [row["status"] for row in repository.list_pending_actions(conversation["id"])] == [
        "cancelled",
        "completed",
    ]


def test_global_resource_is_reused_and_linked_to_multiple_spaces(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    first_space = repository.create_space("SWE")
    second_space = repository.create_space("Agent evaluation")

    first = repository.add_paper(
        first_space["id"],
        title="Shared paper",
        source_url="https://arxiv.org/abs/1234.5678",
        metadata={"arxiv_id": "1234.5678"},
    )
    second = repository.add_paper(
        second_space["id"],
        title="Shared paper (metadata refresh)",
        source_url="https://arxiv.org/abs/1234.5678/",
        metadata={"arxiv_id": "1234.5678", "authors": ["A"]},
    )

    assert second["id"] == first["id"]
    assert set(second["space_ids"]) == {first_space["id"], second_space["id"]}
    assert [row["id"] for row in repository.list_papers(first_space["id"])] == [first["id"]]
    assert [row["id"] for row in repository.list_papers(second_space["id"])] == [first["id"]]
    assert repository.list_spaces()[0]["resource_count"] == 1
    assert len(repository.list_resources()) == 1


def test_deleting_one_space_keeps_shared_resource_in_other_space(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    first_space = repository.create_space("First")
    second_space = repository.create_space("Second")
    resource = repository.add_paper(
        first_space["id"], title="Shared", source_url="https://example.test/shared"
    )
    repository.link_resource_to_space(resource["id"], second_space["id"])

    assert repository.delete_space(first_space["id"])
    surviving = repository.get_paper(resource["id"])
    assert surviving is not None
    assert surviving["space_ids"] == [second_space["id"]]
    assert [row["id"] for row in repository.list_papers(second_space["id"])] == [resource["id"]]
