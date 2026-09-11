from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any, Optional

from pydantic import BaseModel

from fastapi_app.services.research_repository import ResearchRepository
from fastapi_app.services.research_metadata_service import import_paper, resolve_metadata
from fastapi_app.services.research_tools.registry import TOOL_SPECS
from fastapi_app.services.research_tools.schemas import (
    CreateResearchConversationArgs,
    CreateResearchSpaceArgs,
    ImportResearchResourcesArgs,
    SetConversationResourcesArgs,
)


ImportPaper = Callable[..., Awaitable[dict[str, Any]]]
ResolveMetadata = Callable[..., Awaitable[tuple[dict[str, Any], list[dict[str, Any]]]]]


class ResearchToolExecutor:
    """Application-service boundary shared by REST handlers and Codex MCP tools."""

    def __init__(
        self,
        repository: ResearchRepository,
        *,
        import_paper_fn: ImportPaper = import_paper,
        resolve_metadata_fn: ResolveMetadata = resolve_metadata,
    ) -> None:
        self.repository = repository
        self.import_paper = import_paper_fn
        self.resolve_metadata = resolve_metadata_fn

    @staticmethod
    def _unique_strings(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @staticmethod
    def _compact_resource(resource: dict[str, Any]) -> dict[str, Any]:
        metadata = resource.get("metadata") or {}
        return {
            "id": resource.get("id"),
            "space_id": resource.get("space_id"),
            "resource_type": resource.get("resource_type", "paper"),
            "title": resource.get("title"),
            "source_url": resource.get("source_url"),
            "availability": resource.get("availability"),
            "status": resource.get("status"),
            "authors": metadata.get("authors") or [],
            "institutions": metadata.get("institutions") or [],
            "doi": metadata.get("doi"),
            "arxiv_id": metadata.get("arxiv_id"),
            "venue": metadata.get("venue"),
            "publication_status": metadata.get("publication_status"),
            "fulltext_ready": bool(resource.get("stored_path")),
        }

    def _user_space(self, space_id: str) -> dict[str, Any]:
        space = self.repository.get_space(space_id)
        if not space or space.get("scope") == "system":
            raise LookupError("Research space not found")
        return space

    def _global_conversation(self, conversation_id: Optional[str]) -> dict[str, Any]:
        conversation = self.repository.get_conversation(conversation_id or "")
        if not conversation or conversation.get("scope") != "global":
            raise LookupError("A valid global research conversation ID is required")
        return conversation

    def _space_conversation(self, conversation_id: str) -> dict[str, Any]:
        conversation = self.repository.get_conversation(conversation_id)
        if not conversation or conversation.get("scope") in {"global", "system"}:
            raise LookupError("Research conversation not found")
        self._user_space(conversation["space_id"])
        return conversation

    def _validate_resource_ids(self, space_id: str, resource_ids: list[str]) -> list[str]:
        unique_ids = self._unique_strings(resource_ids)
        for resource_id in unique_ids:
            resource = self.repository.get_paper(resource_id)
            if not resource or not self.repository.resource_in_space(resource_id, space_id):
                raise LookupError(f"Resource {resource_id} was not found in the research space")
        return unique_ids

    async def execute_tool(self, name: str, raw_arguments: dict[str, Any]) -> dict[str, Any]:
        spec = TOOL_SPECS.get(name)
        if not spec:
            raise LookupError(f"Unknown research tool: {name}")
        arguments = spec.arguments_model.model_validate(raw_arguments)
        if spec.read_only:
            return await self._execute_read(name, arguments)
        return self.prepare_action(name, arguments)

    async def execute_mcp_tool(self, name: str, raw_arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a Codex MCP request after the model has expressed the action.

        The REST/UI action APIs retain their explicit confirmation workflow. The
        Codex research assistant, however, is itself the natural-language command
        surface, so an explicit write tool call is the user's instruction and can
        execute directly while still being recorded in the audit trail.
        """
        spec = TOOL_SPECS.get(name)
        if not spec:
            raise LookupError(f"Unknown research tool: {name}")
        arguments = spec.arguments_model.model_validate(raw_arguments)
        if spec.read_only:
            return await self._execute_read(name, arguments)
        data = arguments.model_dump()
        source = self._global_conversation(data.get("source_conversation_id"))
        self._validate_write(name, data)
        result = await self.execute_confirmed(name, data)
        request_digest = hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:24]
        self.repository.record_audit(
            conversation_id=source["id"],
            action=name,
            request=data,
            result=result,
            status="completed",
            space_id=(result.get("space") or {}).get("id"),
            idempotency_key=f"mcp:{source['id']}:{name}:{request_digest}",
        )
        return {"success": True, "executed": True, "requires_confirmation": False, **result}

    async def _execute_read(self, name: str, arguments: BaseModel) -> dict[str, Any]:
        data = arguments.model_dump()
        if name == "list_research_spaces":
            spaces = self.repository.list_spaces()[: data["limit"]]
            return {"success": True, "spaces": spaces, "count": len(spaces)}
        if name == "search_research_spaces":
            query = data["query"].strip().casefold()
            spaces = [
                space
                for space in self.repository.list_spaces()
                if query in f"{space.get('title', '')} {space.get('description', '')}".casefold()
            ][: data["limit"]]
            return {"success": True, "spaces": spaces, "count": len(spaces)}
        if name == "list_space_resources":
            self._user_space(data["space_id"])
            query = data["query"].strip().casefold()
            rows = self.repository.list_papers(data["space_id"])
            if data["resource_type"]:
                rows = [row for row in rows if row.get("resource_type") == data["resource_type"]]
            if query:
                rows = [
                    row
                    for row in rows
                    if query
                    in json.dumps(
                        {
                            "title": row.get("title"),
                            "url": row.get("source_url"),
                            "metadata": row.get("metadata"),
                        },
                        ensure_ascii=False,
                    ).casefold()
                ]
            resources = [self._compact_resource(row) for row in rows[: data["limit"]]]
            return {"success": True, "resources": resources, "count": len(resources)}
        if name == "resolve_research_resources":
            queries = self._unique_strings(data["queries"])
            semaphore = asyncio.Semaphore(4)

            async def resolve_one(query: str) -> dict[str, Any]:
                try:
                    async with semaphore:
                        metadata, candidates = await self.resolve_metadata(query)
                    return {
                        "query": query,
                        "status": "resolved",
                        "metadata": metadata,
                        "candidate_count": len(candidates),
                        "candidates": candidates[:5],
                    }
                except Exception as exc:
                    return {"query": query, "status": "error", "error": str(exc)[:1000]}

            results = await asyncio.gather(*(resolve_one(query) for query in queries))
            return {
                "success": any(row["status"] == "resolved" for row in results),
                "results": results,
                "resolved_count": sum(row["status"] == "resolved" for row in results),
                "failed_count": sum(row["status"] == "error" for row in results),
            }
        if name == "list_research_conversations":
            self._user_space(data["space_id"])
            rows = self.repository.list_conversations(
                data["space_id"], data.get("resource_id")
            )[: data["limit"]]
            return {"success": True, "conversations": rows, "count": len(rows)}
        if name == "get_conversation_resources":
            self._space_conversation(data["conversation_id"])
            resources = [
                self._compact_resource(row)
                for row in self.repository.list_conversation_resources(data["conversation_id"])
            ]
            return {"success": True, "resources": resources, "count": len(resources)}
        raise LookupError(f"Read implementation missing for {name}")

    def prepare_action(self, name: str, arguments: BaseModel) -> dict[str, Any]:
        data = arguments.model_dump()
        source = self._global_conversation(data.get("source_conversation_id"))
        self._validate_write(name, data)
        summary = self._action_summary(name, data)
        action = self.repository.create_pending_action(source["id"], name, summary, data)
        self.repository.record_audit(
            conversation_id=source["id"],
            action=f"prepare:{name}",
            request=data,
            result={"action_id": action["id"]},
            status="pending",
            idempotency_key=action["id"],
        )
        return {
            "success": True,
            "requires_confirmation": True,
            "action": action,
            "message": "The action is prepared. Ask the user to review and confirm the action card in ThinkFlow.",
        }

    def _validate_write(self, name: str, data: dict[str, Any]) -> None:
        if name == "create_research_space":
            if not data["title"].strip():
                raise ValueError("Research space title is required")
            return
        if name == "import_research_resources":
            if data.get("space_id"):
                self._user_space(data["space_id"])
            if not self._unique_strings(data["queries"]):
                raise ValueError("At least one paper query is required")
            return
        if name == "create_research_conversation":
            self._user_space(data["space_id"])
            self._validate_resource_ids(data["space_id"], data["resource_ids"])
            return
        if name == "set_conversation_resources":
            conversation = self._space_conversation(data["conversation_id"])
            self._validate_resource_ids(conversation["space_id"], data["resource_ids"])
            return
        raise LookupError(f"Write implementation missing for {name}")

    def _action_summary(self, name: str, data: dict[str, Any]) -> str:
        if name == "create_research_space":
            return f"新建研究空间《{data['title'].strip()}》"
        if name == "import_research_resources":
            target = data.get("new_space_title") or self._user_space(data["space_id"])["title"]
            suffix = f"，并新建对话《{data['new_conversation_title']}》" if data.get("new_conversation_title") else ""
            return f"向《{target}》导入 {len(self._unique_strings(data['queries']))} 项论文资料{suffix}"
        if name == "create_research_conversation":
            space = self._user_space(data["space_id"])
            return f"在《{space['title']}》新建对话《{data['title'] or '新对话'}》，绑定 {len(data['resource_ids'])} 项资料"
        if name == "set_conversation_resources":
            conversation = self._space_conversation(data["conversation_id"])
            return f"将对话《{conversation['title']}》的绑定资料更新为 {len(data['resource_ids'])} 项"
        return name

    async def execute_pending_action(self, action_id: str) -> dict[str, Any]:
        existing = self.repository.get_pending_action(action_id)
        if not existing:
            raise LookupError("Pending action not found")
        if existing["status"] == "completed":
            return existing
        action = self.repository.claim_pending_action(action_id)
        if not action:
            raise RuntimeError(f"Action cannot be confirmed while status is {existing['status']}")
        try:
            result = await self.execute_confirmed(action["tool_name"], action["arguments"])
            finished = self.repository.finish_pending_action(
                action_id, status="completed", result=result
            ) or {}
            self.repository.record_audit(
                conversation_id=action["conversation_id"],
                action=action["tool_name"],
                request=action["arguments"],
                result=result,
                status="completed",
                space_id=(result.get("space") or {}).get("id"),
                idempotency_key=action_id,
            )
            self.repository.add_message(
                action["conversation_id"],
                "assistant",
                self._result_message(action["tool_name"], result),
                event_type="tool_action_result",
                metadata={"action_id": action_id, "tool_name": action["tool_name"]},
            )
            return finished
        except Exception as exc:
            error = str(exc)[:2000]
            self.repository.finish_pending_action(action_id, status="failed", error=error)
            self.repository.record_audit(
                conversation_id=action["conversation_id"],
                action=action["tool_name"],
                request=action["arguments"],
                result={"error": error},
                status="failed",
                idempotency_key=action_id,
            )
            raise

    async def execute_confirmed(self, name: str, raw_arguments: dict[str, Any]) -> dict[str, Any]:
        spec = TOOL_SPECS.get(name)
        if not spec or spec.read_only:
            raise LookupError(f"Unknown write tool: {name}")
        arguments = spec.arguments_model.model_validate(raw_arguments)
        data = arguments.model_dump()
        self._validate_write(name, data)
        if name == "create_research_space":
            space = self.repository.create_space(data["title"], data["description"])
            return {"success": True, "space": space}
        if name == "import_research_resources":
            return await self._import_resources(ImportResearchResourcesArgs.model_validate(data))
        if name == "create_research_conversation":
            payload = CreateResearchConversationArgs.model_validate(data)
            resources = self._validate_resource_ids(payload.space_id, payload.resource_ids)
            conversation = self.repository.create_conversation(
                payload.space_id,
                payload.title,
                scope="paper" if resources else "space",
                paper_ids=resources,
            )
            return {"success": True, "conversation": conversation}
        if name == "set_conversation_resources":
            payload = SetConversationResourcesArgs.model_validate(data)
            conversation = self._space_conversation(payload.conversation_id)
            resources = self._validate_resource_ids(conversation["space_id"], payload.resource_ids)
            updated = self.repository.set_conversation_resources(payload.conversation_id, resources)
            return {
                "success": True,
                "conversation": updated,
                "resources": self.repository.list_conversation_resources(payload.conversation_id),
            }
        raise LookupError(f"Write implementation missing for {name}")

    async def _import_resources(self, arguments: ImportResearchResourcesArgs) -> dict[str, Any]:
        if arguments.space_id:
            space = self._user_space(arguments.space_id)
        else:
            space = self.repository.create_space(
                arguments.new_space_title.strip(), arguments.new_space_description.strip()
            )
        queries = self._unique_strings(arguments.queries)
        semaphore = asyncio.Semaphore(4)

        async def import_one(query: str) -> tuple[dict[str, Any], Optional[str]]:
            try:
                async with semaphore:
                    imported = await self.import_paper(
                        self.repository,
                        space["id"],
                        query,
                        download_pdf=arguments.download_fulltext,
                        download_source=arguments.download_fulltext,
                    )
                paper = imported["paper"]
                return (
                    {
                        "query": query,
                        "status": "success",
                        "paper": paper,
                        "warnings": imported.get("warnings", []),
                        "deduplicated": bool(imported.get("deduplicated")),
                    },
                    paper["id"],
                )
            except Exception as exc:
                return ({"query": query, "status": "error", "error": str(exc)[:1000]}, None)

        imported_results = await asyncio.gather(*(import_one(query) for query in queries))
        results = [row for row, _paper_id in imported_results]
        imported_ids = [paper_id for _row, paper_id in imported_results if paper_id]
        conversation = None
        if arguments.new_conversation_title.strip() and imported_ids:
            conversation = self.repository.create_conversation(
                space["id"],
                arguments.new_conversation_title.strip(),
                scope="paper",
                paper_ids=self._unique_strings(imported_ids)[:200],
            )
        imported_count = sum(row["status"] == "success" for row in results)
        return {
            "success": imported_count > 0,
            "space": self.repository.get_space(space["id"]),
            "conversation": conversation,
            "results": results,
            "imported_count": imported_count,
            "failed_count": len(results) - imported_count,
        }

    @staticmethod
    def _result_message(name: str, result: dict[str, Any]) -> str:
        if name == "create_research_space":
            return f"已新建研究空间《{result['space']['title']}》。"
        if name == "import_research_resources":
            space = result.get("space") or {}
            message = (
                f"已向研究空间《{space.get('title', '')}》处理资料："
                f"成功 {result.get('imported_count', 0)} 项，失败 {result.get('failed_count', 0)} 项。"
            )
            if result.get("conversation"):
                message += f"\n\n已新建并绑定对话《{result['conversation']['title']}》。"
            return message
        if name == "create_research_conversation":
            return f"已新建研究对话《{result['conversation']['title']}》。"
        if name == "set_conversation_resources":
            return f"已更新对话资料绑定，共 {len(result.get('resources') or [])} 项。"
        return "研究库操作已完成。"
