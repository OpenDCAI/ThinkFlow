from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional
from urllib.request import Request, urlopen

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from fastapi_app.services.research_codex_service import codex_service, repository
from fastapi_app.services.research_metadata_service import import_paper, refresh_paper_metadata
from fastapi_app.services.research_paper_service import (
    extract_pdf_to_markdown,
    render_paper_visual_assets,
)
from fastapi_app.services.research_tools import ResearchToolExecutor, TOOL_SPECS


router = APIRouter(prefix="/research", tags=["Research Workspace"])


class SpaceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", max_length=120)
    paper_ids: list[str] = Field(default_factory=list, max_length=20)
    scope: Optional[str] = Field(default=None, max_length=30)


class TurnCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=200_000)
    paper_id: Optional[str] = None


class PaperBinding(BaseModel):
    paper_id: Optional[str] = None


class ConversationResourcesUpdate(BaseModel):
    paper_ids: list[str] = Field(default_factory=list, max_length=20)


class ResourceSpacesUpdate(BaseModel):
    space_ids: list[str] = Field(default_factory=list, max_length=50)


class PaperLinkCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    source_url: str = Field(min_length=1, max_length=4000)
    availability: str = "metadata_only"
    metadata: dict[str, Any] = Field(default_factory=dict)


class BlogLinkCreate(BaseModel):
    title: str = Field(default="", max_length=500)
    source_url: str = Field(min_length=1, max_length=4000)
    fetch_content: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaperImportCreate(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    download_pdf: bool = True
    download_source: bool = True
    resolve_metadata: bool = True


class PaperBatchImportCreate(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=200)
    space_id: Optional[str] = None
    new_space_title: str = Field(default="", max_length=120)
    new_space_description: str = Field(default="", max_length=1000)
    download_pdf: bool = True
    download_source: bool = True
    conversation_id: Optional[str] = None
    instruction: str = Field(default="", max_length=200_000)


class PaperNoteSave(BaseModel):
    short_summary: str = ""
    qa_summary: str = ""
    open_questions: str = ""
    key_takeaways: str = ""
    personal_notes: str = ""


class WikiSave(BaseModel):
    id: Optional[str] = None
    title: str = Field(min_length=1, max_length=200)
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    source_conversation_id: Optional[str] = None


class IdeaSave(BaseModel):
    id: Optional[str] = None
    title: str = Field(min_length=1, max_length=200)
    problem: str = ""
    hypothesis: str = ""
    method: str = ""
    evidence: str = ""
    risks: str = ""
    next_steps: str = ""
    status: str = "draft"
    tags: list[str] = Field(default_factory=list)


class TranslationJobCreate(BaseModel):
    paper_id: str
    provider: str = "unconfigured"
    conversation_id: Optional[str] = None
    target_language: str = "zh-CN"
    layout: str = "original-page-plus-translation"


def _require_space(space_id: str) -> dict[str, Any]:
    space = repository.get_space(space_id)
    if not space:
        raise HTTPException(status_code=404, detail="Research space not found")
    return space


def _require_resource_in_space(resource_id: str, space_id: str) -> dict[str, Any]:
    resource = repository.get_paper(resource_id)
    if not resource or not repository.resource_in_space(resource_id, space_id):
        raise HTTPException(status_code=404, detail="Resource not found in this research space")
    return resource


def _safe_filename(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", Path(name).name)
    return clean[:180] or "paper.pdf"


class _BlogTextParser(HTMLParser):
    """Small dependency-free article extractor for a bounded local context."""

    _ignored = {"script", "style", "noscript", "svg", "nav", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._ignored_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in self._ignored:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in self._ignored and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text or self._ignored_depth:
            return
        if self._in_title and not self.title:
            self.title = text[:500]
        self.parts.append(text)


def _fetch_blog_content(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "ThinkFlow Research/0.1"})
    with urlopen(request, timeout=8) as response:
        payload = response.read(1_000_000)
        charset = response.headers.get_content_charset() or "utf-8"
    parser = _BlogTextParser()
    parser.feed(payload.decode(charset, errors="replace"))
    text = "\n".join(parser.parts)
    return {
        "page_title": parser.title,
        "content": text[:120_000],
        "content_chars": min(len(text), 120_000),
        "content_status": "ready" if text else "empty",
    }


@router.get("/status")
async def research_status() -> dict[str, Any]:
    codex = await codex_service.status()
    return {
        "success": True,
        "codex": codex,
        "storage": str(repository.root),
        "translation_providers": [
            {
                "id": "unconfigured",
                "name": "待接入翻译 Provider",
                "available": False,
                "accepts": ["skill", "command", "http"],
                "outputs": ["bilingual_pdf", "markdown"],
            }
        ],
        "external_tools": [
            {"id": "lark-calendar", "available": True, "mode": "skill"},
            {"id": "lark-task", "available": True, "mode": "skill"},
        ],
        "research_functions": [
            {
                "name": spec.name,
                "title": spec.title,
                "read_only": spec.read_only,
            }
            for spec in TOOL_SPECS.values()
        ],
    }


@router.get("/spaces")
async def list_spaces() -> dict[str, Any]:
    return {"success": True, "spaces": repository.list_spaces()}


@router.post("/spaces")
async def create_space(request: SpaceCreate) -> dict[str, Any]:
    return {"success": True, "space": repository.create_space(request.title, request.description)}


@router.delete("/spaces/{space_id}")
async def delete_space(space_id: str) -> dict[str, Any]:
    if not repository.delete_space(space_id):
        raise HTTPException(status_code=404, detail="Research space not found")
    return {"success": True}


@router.get("/spaces/{space_id}/conversations")
async def list_conversations(space_id: str, resource_id: Optional[str] = None) -> dict[str, Any]:
    _require_space(space_id)
    return {"success": True, "conversations": repository.list_conversations(space_id, resource_id)}


@router.post("/spaces/{space_id}/conversations")
async def create_conversation(space_id: str, request: ConversationCreate) -> dict[str, Any]:
    _require_space(space_id)
    papers = []
    for paper_id in dict.fromkeys(request.paper_ids):
        _require_resource_in_space(paper_id, space_id)
        papers.append(paper_id)
    scope = request.scope or ("paper" if papers else "space")
    if scope not in {"space", "paper", "idea"}:
        scope = "paper" if papers else "space"
    return {
        "success": True,
        "conversation": repository.create_conversation(
            space_id,
            request.title,
            scope=scope,
            paper_ids=papers,
        ),
    }


@router.get("/global/conversations")
async def list_global_conversations() -> dict[str, Any]:
    return {"success": True, "conversations": repository.list_global_conversations()}


@router.post("/global/conversations")
async def create_global_conversation(request: ConversationCreate) -> dict[str, Any]:
    if request.paper_ids:
        raise HTTPException(status_code=400, detail="Global conversations do not attach papers")
    return {
        "success": True,
        "conversation": repository.create_global_conversation(
            request.title or "全局研究对话"
        ),
    }


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(conversation_id: str) -> dict[str, Any]:
    if not repository.get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"success": True, "messages": repository.list_messages(conversation_id)}


@router.post("/conversations/{conversation_id}/messages/{message_id}/rollback")
async def rollback_message_turn(conversation_id: str, message_id: str) -> dict[str, Any]:
    try:
        snapshot = repository.prepare_message_regeneration(conversation_id, message_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "success": True,
        "removed_count": len(snapshot["removed"]),
        "messages": repository.list_messages(conversation_id),
        "conversation": repository.get_conversation(conversation_id),
    }


@router.post("/conversations/{conversation_id}/messages/{message_id}/regenerate")
async def regenerate_message_turn(
    conversation_id: str, message_id: str
) -> StreamingResponse:
    try:
        snapshot = repository.prepare_message_regeneration(conversation_id, message_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def stream():
        finished = False
        completed_normally = False
        try:
            async for event in codex_service.stream_turn(
                conversation_id,
                snapshot["prompt"],
                history_messages=snapshot["history"],
            ):
                if event["type"] == "turn.harness" and event["data"].get("phase") == "completed":
                    completed_normally = True
                if event["type"] == "turn/completed":
                    turn = event["data"].get("turn") or {}
                    status = turn.get("status") or event["data"].get("status")
                    completed_normally = completed_normally or status == "completed"
                yield f"event: {event['type']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
            tail = repository.list_messages(conversation_id)[len(snapshot["history"]):]
            finished = bool(
                completed_normally and tail and tail[-1].get("role") == "assistant"
            )
        finally:
            if not finished:
                repository.restore_message_regeneration(snapshot)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations/{conversation_id}/actions")
async def list_conversation_actions(
    conversation_id: str, status: Optional[str] = None
) -> dict[str, Any]:
    conversation = repository.get_conversation(conversation_id)
    if not conversation or conversation.get("scope") != "global":
        raise HTTPException(status_code=404, detail="Global conversation not found")
    if status and status not in {"pending", "executing", "completed", "failed", "cancelled"}:
        raise HTTPException(status_code=422, detail="Unsupported action status")
    return {
        "success": True,
        "actions": repository.list_pending_actions(conversation_id, status=status),
    }


@router.post("/actions/{action_id}/confirm")
async def confirm_research_action(action_id: str) -> dict[str, Any]:
    action = repository.get_pending_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Pending action not found")
    conversation = repository.get_conversation(action["conversation_id"])
    if not conversation or conversation.get("scope") != "global":
        raise HTTPException(status_code=404, detail="Global conversation not found")
    executor = ResearchToolExecutor(repository, import_paper_fn=import_paper)
    try:
        executed = await executor.execute_pending_action(action_id)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"success": True, "action": executed}


@router.post("/actions/{action_id}/cancel")
async def cancel_research_action(action_id: str) -> dict[str, Any]:
    action = repository.get_pending_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Pending action not found")
    conversation = repository.get_conversation(action["conversation_id"])
    if not conversation or conversation.get("scope") != "global":
        raise HTTPException(status_code=404, detail="Global conversation not found")
    cancelled = repository.cancel_pending_action(action_id)
    if not cancelled:
        raise HTTPException(status_code=409, detail=f"Action cannot be cancelled while status is {action['status']}")
    repository.record_audit(
        conversation_id=action["conversation_id"],
        action=f"cancel:{action['tool_name']}",
        request=action["arguments"],
        result={"action_id": action_id},
        status="cancelled",
        idempotency_key=action_id,
    )
    return {"success": True, "action": cancelled}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict[str, Any]:
    conversation = repository.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation.get("status") == "running":
        await codex_service.cancel(conversation_id)
    if not repository.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"success": True}


@router.put("/conversations/{conversation_id}/paper")
async def bind_conversation_paper(
    conversation_id: str, request: PaperBinding
) -> dict[str, Any]:
    conversation = repository.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if request.paper_id:
        _require_resource_in_space(request.paper_id, conversation["space_id"])
    updated = repository.bind_conversation_paper(conversation_id, request.paper_id)
    return {"success": True, "conversation": updated}


@router.get("/conversations/{conversation_id}/papers")
async def list_conversation_papers(conversation_id: str) -> dict[str, Any]:
    if not repository.get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "success": True,
        "papers": repository.list_conversation_resources(conversation_id),
    }


@router.put("/conversations/{conversation_id}/papers")
async def set_conversation_papers(
    conversation_id: str, request: ConversationResourcesUpdate
) -> dict[str, Any]:
    conversation = repository.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    paper_ids = list(dict.fromkeys(request.paper_ids))
    for paper_id in paper_ids:
        _require_resource_in_space(paper_id, conversation["space_id"])
    updated = repository.set_conversation_resources(conversation_id, paper_ids)
    return {
        "success": True,
        "conversation": updated,
        "papers": repository.list_conversation_resources(conversation_id),
    }


@router.post("/conversations/{conversation_id}/turns")
async def create_turn(conversation_id: str, request: TurnCreate) -> StreamingResponse:
    conversation = repository.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if request.paper_id:
        _require_resource_in_space(request.paper_id, conversation["space_id"])

    async def stream():
        async for event in codex_service.stream_turn(
            conversation_id, request.prompt.strip(), request.paper_id
        ):
            yield f"event: {event['type']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/conversations/{conversation_id}/cancel")
async def cancel_turn(conversation_id: str) -> dict[str, Any]:
    return {"success": True, "cancelled": await codex_service.cancel(conversation_id)}


@router.get("/spaces/{space_id}/papers")
async def list_papers(space_id: str) -> dict[str, Any]:
    _require_space(space_id)
    return {"success": True, "papers": repository.list_papers(space_id)}


@router.get("/resources")
async def list_resources(resource_type: Optional[str] = None) -> dict[str, Any]:
    """List the global, de-duplicated research resource library."""
    return {
        "success": True,
        "resources": repository.list_resources(resource_type=resource_type),
    }


@router.get("/resources/{resource_id}")
async def get_resource(resource_id: str) -> dict[str, Any]:
    resource = repository.get_paper(resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Research resource not found")
    return {
        "success": True,
        "resource": resource,
        "spaces": repository.list_resource_spaces(resource_id),
    }


@router.get("/resources/{resource_id}/spaces")
async def list_resource_spaces(resource_id: str) -> dict[str, Any]:
    if not repository.get_paper(resource_id):
        raise HTTPException(status_code=404, detail="Research resource not found")
    return {"success": True, "spaces": repository.list_resource_spaces(resource_id)}


@router.put("/resources/{resource_id}/spaces")
async def set_resource_spaces(resource_id: str, request: ResourceSpacesUpdate) -> dict[str, Any]:
    if not repository.get_paper(resource_id):
        raise HTTPException(status_code=404, detail="Research resource not found")
    target_ids = list(dict.fromkeys(request.space_ids))
    for space_id in target_ids:
        _require_space(space_id)
    current_ids = [space["id"] for space in repository.list_resource_spaces(resource_id)]
    for space_id in target_ids:
        repository.link_resource_to_space(resource_id, space_id)
    for space_id in current_ids:
        if space_id not in target_ids:
            repository.unlink_resource_from_space(resource_id, space_id)
    return {
        "success": True,
        "resource": repository.get_paper(resource_id),
        "spaces": repository.list_resource_spaces(resource_id),
    }


@router.post("/spaces/{space_id}/papers/upload")
async def upload_paper(
    space_id: str,
    file: UploadFile = File(...),
    title: str = Form(""),
) -> dict[str, Any]:
    _require_space(space_id)
    if Path(file.filename or "").suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF papers are supported")
    signature = await file.read(5)
    await file.seek(0)
    if signature != b"%PDF-":
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid PDF")
    filename = _safe_filename(file.filename or "paper.pdf")
    destination = repository.space_dir(space_id) / "papers" / filename
    if destination.exists():
        destination = destination.with_name(
            f"{destination.stem}_{uuid.uuid4().hex[:8]}{destination.suffix}"
        )
    with destination.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    relative = destination.relative_to(repository.root.parent).as_posix()
    metadata: dict[str, Any] = {
        "size": destination.stat().st_size,
        "outputs_url": f"/outputs/{relative}",
    }
    text_path = destination.with_name(f"{destination.stem}.extracted.md")
    try:
        extraction = await asyncio.to_thread(
            extract_pdf_to_markdown,
            destination,
            text_path,
            title.strip() or destination.stem,
        )
        metadata.update(extraction)
        # Render a bounded set of figure/table pages at ingest time. Codex can
        # attach these images later when the question actually needs vision.
        try:
            metadata.update(await asyncio.to_thread(render_paper_visual_assets, destination))
        except Exception as exc:
            metadata.update(
                {
                    "visual_ingestion_status": "error",
                    "visual_ingestion_error": str(exc)[:500],
                }
            )
    except Exception as exc:
        metadata.update({"extraction_status": "error", "extraction_error": str(exc)[:500]})
    paper = repository.add_paper(
        space_id,
        title=title.strip() or destination.stem,
        original_name=file.filename,
        stored_path=str(destination),
        status="ready" if metadata.get("extraction_status") == "ready" else "extract_error",
        metadata=metadata,
    )
    return {"success": True, "paper": paper}


@router.post("/spaces/{space_id}/papers/link")
async def add_paper_link(space_id: str, request: PaperLinkCreate) -> dict[str, Any]:
    _require_space(space_id)
    paper = repository.add_paper(
        space_id,
        title=request.title,
        source_url=request.source_url,
        availability=request.availability,
        status="metadata_only",
        metadata=request.metadata,
    )
    return {"success": True, "paper": paper}


@router.post("/spaces/{space_id}/resources/blog")
async def add_blog_link(space_id: str, request: BlogLinkCreate) -> dict[str, Any]:
    _require_space(space_id)
    metadata = dict(request.metadata)
    metadata["resource_type"] = "blog"
    metadata["source_url"] = request.source_url
    if request.fetch_content:
        try:
            fetched = await asyncio.to_thread(_fetch_blog_content, request.source_url)
            metadata.update(fetched)
        except Exception as exc:
            metadata.update({"content_status": "error", "content_error": str(exc)[:500]})
    title = request.title.strip() or str(metadata.get("page_title") or request.source_url)
    resource = repository.add_paper(
        space_id,
        title=title,
        source_url=request.source_url,
        resource_type="blog",
        availability="remote_url",
        status="ready" if metadata.get("content_status") == "ready" else "metadata_only",
        metadata=metadata,
    )
    return {"success": True, "resource": resource, "paper": resource}


# Keep these routes after the legacy `/resources/blog` route.  FastAPI uses
# declaration order for overlapping path parameters, so the generic resource
# link must not capture the literal `blog` endpoint.
@router.post("/spaces/{space_id}/resources/{resource_id}")
async def link_resource_to_space(space_id: str, resource_id: str) -> dict[str, Any]:
    _require_space(space_id)
    if not repository.link_resource_to_space(resource_id, space_id):
        raise HTTPException(status_code=404, detail="Research resource not found")
    return {
        "success": True,
        "resource": repository.get_paper(resource_id),
        "spaces": repository.list_resource_spaces(resource_id),
    }


@router.delete("/spaces/{space_id}/resources/{resource_id}")
async def unlink_resource_from_space(space_id: str, resource_id: str) -> dict[str, Any]:
    _require_space(space_id)
    if not repository.unlink_resource_from_space(resource_id, space_id):
        raise HTTPException(status_code=404, detail="Resource link not found")
    return {
        "success": True,
        "resource": repository.get_paper(resource_id),
        "spaces": repository.list_resource_spaces(resource_id),
    }


@router.post("/spaces/{space_id}/papers/import")
async def import_paper_from_query(space_id: str, request: PaperImportCreate) -> dict[str, Any]:
    _require_space(space_id)
    if not request.resolve_metadata:
        raise HTTPException(status_code=400, detail="论文导入必须启用元数据补全")
    try:
        result = await import_paper(
            repository,
            space_id,
            request.query,
            download_pdf=request.download_pdf,
            download_source=request.download_source,
        )
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"success": True, **result}


@router.post("/papers/batch-import")
async def batch_import_papers(request: PaperBatchImportCreate) -> dict[str, Any]:
    conversation = None
    if request.conversation_id:
        conversation = repository.get_conversation(request.conversation_id)
        if not conversation or conversation.get("scope") != "global":
            raise HTTPException(status_code=404, detail="Global conversation not found")
    if not request.space_id and not request.new_space_title.strip():
        raise HTTPException(
            status_code=422,
            detail="Choose an existing research space or provide a new space title",
        )
    queries = list(dict.fromkeys(query.strip() for query in request.queries if query.strip()))
    if not queries:
        raise HTTPException(status_code=422, detail="No paper queries were provided")
    executor = ResearchToolExecutor(repository, import_paper_fn=import_paper)
    try:
        result = await executor.execute_confirmed(
            "import_research_resources",
            {
                "source_conversation_id": request.conversation_id,
                "queries": queries,
                "space_id": request.space_id,
                "new_space_title": request.new_space_title.strip(),
                "new_space_description": request.new_space_description.strip(),
                "download_fulltext": request.download_pdf,
            },
        )
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if conversation:
        instruction = request.instruction.strip() or "\n".join(queries)
        repository.add_message(
            conversation["id"],
            "user",
            instruction,
            event_type="library_action_request",
        )
        success_titles = [
            item["paper"]["title"] for item in result["results"] if item["status"] == "success"
        ]
        failed_queries = [
            item["query"] for item in result["results"] if item["status"] == "error"
        ]
        summary = (
            f"已处理 {len(result['results'])} 项资料，成功导入 {result['imported_count']} 篇到研究空间“{result['space']['title']}”"
            f"，失败 {len(failed_queries)} 篇。"
        )
        if success_titles:
            summary += "\n\n**已导入**\n" + "\n".join(f"- {title}" for title in success_titles)
        if failed_queries:
            summary += "\n\n**未导入**\n" + "\n".join(f"- {query}" for query in failed_queries)
        repository.add_message(
            conversation["id"],
            "assistant",
            summary,
            event_type="library_action_result",
            metadata={
                "space_id": result["space"]["id"],
                "imported_count": result["imported_count"],
                "failed_count": result["failed_count"],
            },
        )
    return result


@router.post("/papers/{paper_id}/metadata/refresh")
async def refresh_paper(paper_id: str) -> dict[str, Any]:
    try:
        paper = await refresh_paper_metadata(repository, paper_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True, "paper": paper}


@router.get("/papers/{paper_id}/note")
async def get_paper_note(paper_id: str) -> dict[str, Any]:
    if not repository.get_paper(paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    return {"success": True, "note": repository.get_paper_note(paper_id)}


@router.put("/papers/{paper_id}/note")
async def save_paper_note(paper_id: str, request: PaperNoteSave) -> dict[str, Any]:
    if not repository.get_paper(paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    existing = repository.get_paper_note(paper_id) or {}
    note = repository.save_paper_note(
        paper_id,
        short_summary=request.short_summary,
        qa_summary=request.qa_summary,
        open_questions=request.open_questions,
        key_takeaways=request.key_takeaways,
        personal_notes=request.personal_notes,
        source_message_ids=existing.get("source_message_ids") or [],
    )
    return {"success": True, "note": note}


@router.post("/papers/{paper_id}/note/refresh")
async def refresh_paper_note(paper_id: str) -> dict[str, Any]:
    if not repository.get_paper(paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    try:
        note = await codex_service.generate_paper_note(paper_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"success": True, "note": note}


@router.get("/papers/{paper_id}/file")
async def paper_file(paper_id: str) -> FileResponse:
    paper = repository.get_paper(paper_id)
    if not paper or not paper.get("stored_path"):
        raise HTTPException(status_code=404, detail="Paper file not found")
    path = Path(paper["stored_path"]).resolve()
    expected = repository.root.resolve()
    if expected not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Paper file not found")
    return FileResponse(path, media_type="application/pdf", filename=paper.get("original_name") or path.name)


@router.get("/spaces/{space_id}/wiki")
async def list_wiki(space_id: str, q: str = "") -> dict[str, Any]:
    _require_space(space_id)
    return {"success": True, "pages": repository.list_wiki(space_id, q)}


@router.post("/spaces/{space_id}/wiki")
async def save_wiki(space_id: str, request: WikiSave) -> dict[str, Any]:
    _require_space(space_id)
    page = repository.save_wiki(
        space_id,
        page_id=request.id,
        title=request.title,
        content=request.content,
        tags=request.tags,
        source_conversation_id=request.source_conversation_id,
    )
    return {"success": True, "page": page}


@router.delete("/wiki/{page_id}")
async def delete_wiki(page_id: str) -> dict[str, Any]:
    if not repository.delete_wiki(page_id):
        raise HTTPException(status_code=404, detail="Wiki page not found")
    return {"success": True}


@router.get("/spaces/{space_id}/ideas")
async def list_ideas(space_id: str) -> dict[str, Any]:
    _require_space(space_id)
    return {"success": True, "ideas": repository.list_ideas(space_id)}


@router.post("/spaces/{space_id}/ideas")
async def save_idea(space_id: str, request: IdeaSave) -> dict[str, Any]:
    _require_space(space_id)
    return {
        "success": True,
        "idea": repository.save_idea(space_id, request.model_dump(), request.id),
    }


@router.get("/spaces/{space_id}/jobs")
async def list_jobs(space_id: str) -> dict[str, Any]:
    _require_space(space_id)
    return {"success": True, "jobs": repository.list_jobs(space_id)}


@router.post("/spaces/{space_id}/translations")
async def create_translation(space_id: str, request: TranslationJobCreate) -> dict[str, Any]:
    _require_space(space_id)
    paper = repository.get_paper(request.paper_id)
    if not paper or not repository.resource_in_space(request.paper_id, space_id):
        raise HTTPException(status_code=404, detail="Paper not found in this research space")
    if request.conversation_id:
        conversation = repository.get_conversation(request.conversation_id)
        if not conversation or conversation["space_id"] != space_id:
            raise HTTPException(status_code=404, detail="Conversation not found in this research space")
    job = repository.create_job(
        space_id,
        kind="paper_translation",
        provider=request.provider,
        conversation_id=request.conversation_id,
        input_data=request.model_dump(),
        status="waiting_provider",
    )
    return {
        "success": True,
        "job": job,
        "message": "Translation job created; install and register a translation provider to run it.",
    }


@router.get("/skills")
async def list_skills() -> dict[str, Any]:
    roots = [Path.home() / ".agents" / "skills", Path.cwd() / ".agents" / "skills"]
    skills: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for skill_file in sorted(root.glob("*/SKILL.md")):
            name = skill_file.parent.name
            key = str(skill_file.resolve())
            if key in seen:
                continue
            seen.add(key)
            first_lines = skill_file.read_text(encoding="utf-8", errors="replace")[:3000]
            description_match = re.search(r"^description:\s*[\"']?(.*?)[\"']?\s*$", first_lines, re.MULTILINE)
            skills.append({
                "name": name,
                "path": key,
                "description": description_match.group(1) if description_match else "",
                "source": "filesystem",
            })
    runtime = await codex_service.skills()
    runtime_rows = runtime.get("skills") or []
    by_path = {str(row.get("path")): row for row in runtime_rows if row.get("path")}
    merged: list[dict[str, Any]] = []
    for skill in skills:
        runtime_row = by_path.get(skill["path"])
        merged.append({
            **skill,
            **({
                "enabled": runtime_row.get("enabled"),
                "scope": runtime_row.get("scope"),
                "interface": runtime_row.get("interface"),
                "source": "codex-runtime",
                "runtime_cwd": runtime_row.get("cwd"),
            } if runtime_row else {}),
        })
    for runtime_row in runtime_rows:
        path = str(runtime_row.get("path") or "")
        if path and path not in {skill["path"] for skill in merged}:
            merged.append({
                "name": runtime_row.get("name", ""),
                "path": path,
                "description": runtime_row.get("description", ""),
                "enabled": runtime_row.get("enabled"),
                "scope": runtime_row.get("scope"),
                "interface": runtime_row.get("interface"),
                "source": "codex-runtime",
                "runtime_cwd": runtime_row.get("cwd"),
            })
    return {
        "success": True,
        "skills": merged,
        "runtime": {
            "available": bool(runtime_rows) or not runtime.get("error"),
            "error": runtime.get("error"),
            "root": runtime.get("root"),
        },
    }
