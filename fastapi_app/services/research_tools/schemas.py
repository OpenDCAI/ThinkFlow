from __future__ import annotations

from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


QueryText = Annotated[str, Field(min_length=1, max_length=4000)]
ResourceId = Annotated[str, Field(min_length=1, max_length=100)]


class ListResearchSpacesArgs(ToolArguments):
    limit: int = Field(default=50, ge=1, le=100)


class SearchResearchSpacesArgs(ToolArguments):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=20, ge=1, le=100)


class CreateResearchSpaceArgs(ToolArguments):
    source_conversation_id: Optional[str] = Field(
        default=None,
        description="The current ThinkFlow global conversation ID.",
    )
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class ListSpaceResourcesArgs(ToolArguments):
    space_id: str = Field(min_length=1, max_length=100)
    query: str = Field(default="", max_length=500)
    resource_type: Optional[str] = Field(default=None, pattern="^(paper|blog)$")
    limit: int = Field(default=100, ge=1, le=200)


class ResolveResearchResourcesArgs(ToolArguments):
    queries: list[QueryText] = Field(min_length=1, max_length=200)


class ImportResearchResourcesArgs(ToolArguments):
    source_conversation_id: Optional[str] = Field(
        default=None,
        description="The current ThinkFlow global conversation ID.",
    )
    queries: list[QueryText] = Field(min_length=1, max_length=200)
    space_id: Optional[str] = Field(default=None, max_length=100)
    new_space_title: str = Field(default="", max_length=120)
    new_space_description: str = Field(default="", max_length=1000)
    download_fulltext: bool = True
    new_conversation_title: str = Field(
        default="",
        max_length=120,
        description="Optionally create a conversation and attach all successfully imported resources.",
    )

    @model_validator(mode="after")
    def target_is_unambiguous(self) -> "ImportResearchResourcesArgs":
        if bool(self.space_id) == bool(self.new_space_title.strip()):
            raise ValueError("Provide exactly one of space_id or new_space_title")
        return self


class ListResearchConversationsArgs(ToolArguments):
    space_id: str = Field(min_length=1, max_length=100)
    resource_id: Optional[str] = Field(default=None, max_length=100)
    limit: int = Field(default=50, ge=1, le=100)


class CreateResearchConversationArgs(ToolArguments):
    source_conversation_id: Optional[str] = Field(
        default=None,
        description="The current ThinkFlow global conversation ID.",
    )
    space_id: str = Field(min_length=1, max_length=100)
    title: str = Field(default="新对话", max_length=120)
    resource_ids: list[ResourceId] = Field(default_factory=list, max_length=200)


class GetConversationResourcesArgs(ToolArguments):
    conversation_id: str = Field(min_length=1, max_length=100)


class SetConversationResourcesArgs(ToolArguments):
    source_conversation_id: Optional[str] = Field(
        default=None,
        description="The current ThinkFlow global conversation ID.",
    )
    conversation_id: str = Field(min_length=1, max_length=100)
    resource_ids: list[ResourceId] = Field(default_factory=list, max_length=200)
