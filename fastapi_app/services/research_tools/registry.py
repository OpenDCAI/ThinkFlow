from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel

from fastapi_app.services.research_tools.schemas import (
    CreateResearchConversationArgs,
    CreateResearchSpaceArgs,
    GetConversationResourcesArgs,
    ImportResearchResourcesArgs,
    ListResearchConversationsArgs,
    ListResearchSpacesArgs,
    ListSpaceResourcesArgs,
    ResolveResearchResourcesArgs,
    SearchResearchSpacesArgs,
    SetConversationResourcesArgs,
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    arguments_model: Type[BaseModel]
    read_only: bool

    def mcp_definition(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.arguments_model.model_json_schema(),
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": False,
                "idempotentHint": self.read_only,
                "openWorldHint": self.name == "resolve_research_resources",
            },
        }


TOOL_SPECS = {
    spec.name: spec
    for spec in (
        ToolSpec(
            "list_research_spaces",
            "列出研究空间",
            "List all visible ThinkFlow research spaces with resource and conversation counts.",
            ListResearchSpacesArgs,
            True,
        ),
        ToolSpec(
            "search_research_spaces",
            "搜索研究空间",
            "Search visible research spaces by title or research description before creating a duplicate.",
            SearchResearchSpacesArgs,
            True,
        ),
        ToolSpec(
            "create_research_space",
            "新建研究空间",
            "Create a ThinkFlow research space when the user explicitly asks for one in the global research conversation.",
            CreateResearchSpaceArgs,
            False,
        ),
        ToolSpec(
            "list_space_resources",
            "获取空间资料",
            "List or search papers and blogs already stored in one research space. Use returned resource IDs for conversation bindings.",
            ListSpaceResourcesArgs,
            True,
        ),
        ToolSpec(
            "resolve_research_resources",
            "查找论文",
            "Resolve paper titles, DOI values, arXiv IDs, or public links into metadata without adding anything to the library.",
            ResolveResearchResourcesArgs,
            True,
        ),
        ToolSpec(
            "import_research_resources",
            "批量导入论文",
            "Import up to 200 paper titles, DOI values, arXiv IDs, or links into an existing or new research space. It can also create one conversation bound to all successful imports.",
            ImportResearchResourcesArgs,
            False,
        ),
        ToolSpec(
            "list_research_conversations",
            "获取研究对话",
            "List conversations in one research space, optionally filtered by a bound paper or blog resource.",
            ListResearchConversationsArgs,
            True,
        ),
        ToolSpec(
            "create_research_conversation",
            "新建研究对话",
            "Create a conversation in a research space, optionally with multiple existing resources attached.",
            CreateResearchConversationArgs,
            False,
        ),
        ToolSpec(
            "get_conversation_resources",
            "获取对话绑定资料",
            "Get the ordered papers and blogs currently attached to a research conversation.",
            GetConversationResourcesArgs,
            True,
        ),
        ToolSpec(
            "set_conversation_resources",
            "设置对话资料",
            "Replace a conversation's ordered multi-resource binding when the user explicitly requests the change.",
            SetConversationResourcesArgs,
            False,
        ),
    )
}
