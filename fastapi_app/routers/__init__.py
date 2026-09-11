from __future__ import annotations

"""
Router package for FastAPI backend (Notebook / frontend-v2).
"""

from . import (
    auth,
    data_extract,
    files,
    kb,
    kb_conversation_workspace,
    kb_documents,
    kb_embedding,
    kb_notebooks,
    kb_outputs_v2,
    kb_sources,
    kb_workspace,
    paper2drawio,
    paper2ppt,
    research,
)

__all__ = [
    "auth",
    "data_extract",
    "kb",
    "kb_conversation_workspace",
    "kb_documents",
    "kb_embedding",
    "kb_notebooks",
    "kb_outputs_v2",
    "kb_sources",
    "kb_workspace",
    "files",
    "paper2drawio",
    "paper2ppt",
    "research",
]
