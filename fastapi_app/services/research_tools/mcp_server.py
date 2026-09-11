from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from fastapi_app.services.research_repository import ResearchRepository
from fastapi_app.services.research_tools.executor import ResearchToolExecutor
from fastapi_app.services.research_tools.registry import TOOL_SPECS


SERVER_INSTRUCTIONS = (
    "Use read-only ThinkFlow research tools whenever library state is needed. "
    "Write tools execute the user's explicit natural-language request directly; summarize the result and never ask the user to choose a separate import or create mode. "
    "Always pass the current global conversation ID as source_conversation_id. "
    "Search existing spaces and resources before proposing duplicates. Never invent IDs."
)


class ResearchMcpServer:
    def __init__(self) -> None:
        configured_root = os.getenv("THINKFLOW_RESEARCH_ROOT", "").strip()
        repository = ResearchRepository(Path(configured_root) if configured_root else None)
        self.executor = ResearchToolExecutor(repository)

    @staticmethod
    def _response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    async def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = str(request.get("method") or "")
        request_id = request.get("id")
        if request_id is None:
            return None
        if method == "initialize":
            requested = (request.get("params") or {}).get("protocolVersion")
            return self._response(
                request_id,
                {
                    "protocolVersion": requested or "2025-06-18",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "thinkflow-research", "version": "0.1.0"},
                    "instructions": SERVER_INSTRUCTIONS,
                },
            )
        if method == "ping":
            return self._response(request_id, {})
        if method == "tools/list":
            return self._response(
                request_id,
                {"tools": [spec.mcp_definition() for spec in TOOL_SPECS.values()]},
            )
        if method == "tools/call":
            params = request.get("params") or {}
            name = str(params.get("name") or "")
            arguments = params.get("arguments") or {}
            try:
                result = await self.executor.execute_mcp_tool(name, arguments)
                return self._response(
                    request_id,
                    {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, ensure_ascii=False),
                            }
                        ],
                        "structuredContent": result,
                        "isError": False,
                    },
                )
            except Exception as exc:
                error = {"success": False, "error": str(exc)[:2000]}
                return self._response(
                    request_id,
                    {
                        "content": [
                            {"type": "text", "text": json.dumps(error, ensure_ascii=False)}
                        ],
                        "structuredContent": error,
                        "isError": True,
                    },
                )
        if method in {"resources/list", "prompts/list"}:
            key = "resources" if method.startswith("resources") else "prompts"
            return self._response(request_id, {key: []})
        return self._error(request_id, -32601, f"Method not found: {method}")

    async def run(self) -> None:
        while True:
            line = await asyncio.to_thread(sys.stdin.buffer.readline)
            if not line:
                return
            try:
                request = json.loads(line)
                response = await self.handle(request)
            except Exception as exc:
                response = self._error(None, -32700, f"Invalid request: {str(exc)[:1000]}")
            if response is not None:
                payload = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
                sys.stdout.write(payload + "\n")
                sys.stdout.flush()


def main() -> None:
    asyncio.run(ResearchMcpServer().run())


if __name__ == "__main__":
    main()
