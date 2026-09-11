from __future__ import annotations

import os
import sqlite3  # Load Conda's SQLite/ICU stack before multimedia libraries load libstdc++.
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote

try:
    from dotenv import load_dotenv
    _root = Path(__file__).resolve().parent.parent
    load_dotenv(_root / "fastapi_app" / ".env")
    load_dotenv(_root / "fastapi_app" / ".env.local", override=True)
except ImportError:
    pass

from workflow_engine.logger import get_logger

log = get_logger(__name__)

# Check Supabase configuration
_supabase_url = os.getenv("SUPABASE_URL")
_supabase_anon = os.getenv("SUPABASE_ANON_KEY")
_supabase_service = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
if _supabase_url and _supabase_anon:
    log.info(f"Supabase configured: URL={_supabase_url[:30]}..., ANON_KEY={'set' if _supabase_anon else 'unset'}, SERVICE_KEY={'set' if _supabase_service else 'unset'}")
else:
    log.info(f"Supabase not configured: URL={'set' if _supabase_url else 'unset'}, ANON_KEY={'set' if _supabase_anon else 'unset'}")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from fastapi_app.routers import auth, data_extract, files, kb, kb_conversation_workspace, kb_documents, kb_embedding, kb_notebooks, kb_outputs_v2, kb_sources, kb_workspace, paper2drawio, paper2ppt, research, tts, search
from fastapi_app.middleware.api_key import APIKeyMiddleware
from fastapi_app.middleware.logging import LoggingMiddleware
from workflow_engine.utils import get_project_root

# Import services (Provider-based)
from fastapi_app.services.embedding_service import EmbeddingService
from fastapi_app.services.research_codex_service import codex_service
from fastapi_app.services.tts_service import TTSService


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Simplified lifespan without subprocess management"""
    log.info("Application startup - Provider-based architecture")

    # Initialize services (no subprocess needed)
    embedding_service = EmbeddingService()
    tts_service = TTSService()


    try:
        yield
    finally:
        await codex_service.close()
        log.info("Application shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="DataFlow Agent FastAPI Backend",
        version="0.1.0",
        description="HTTP API wrapper for dataflow_agent.workflow.* pipelines",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(LoggingMiddleware)
    app.add_middleware(APIKeyMiddleware)

    # Router registration
    app.include_router(kb.router, prefix="/api/v1", tags=["Knowledge Base"])
    app.include_router(kb_conversation_workspace.router, prefix="/api/v1", tags=["ThinkFlow Conversation Workspace"])
    app.include_router(kb_documents.router, prefix="/api/v1", tags=["Knowledge Base"])
    app.include_router(kb_notebooks.router, prefix="/api/v1", tags=["Knowledge Base"])
    app.include_router(kb_outputs_v2.router, prefix="/api/v1", tags=["Knowledge Base"])
    app.include_router(kb_sources.router, prefix="/api/v1", tags=["Knowledge Base"])
    app.include_router(kb_workspace.router, prefix="/api/v1", tags=["ThinkFlow Workspace"])
    app.include_router(kb_embedding.router, prefix="/api/v1", tags=["Knowledge Base Embedding"])
    app.include_router(files.router, prefix="/api/v1", tags=["Files"])
    app.include_router(data_extract.router, prefix="/api/v1", tags=["Data Extract"])
    app.include_router(paper2drawio.router, prefix="/api/v1", tags=["Paper2Drawio"])
    app.include_router(paper2ppt.router, prefix="/api/v1", tags=["Paper2PPT"])
    app.include_router(auth.router, prefix="/api/v1", tags=["Auth"])
    app.include_router(tts.router, prefix="/api/v1", tags=["TTS"])
    app.include_router(search.router, prefix="/api/v1", tags=["Search"])
    app.include_router(research.router, prefix="/api/v1", tags=["Research Workspace"])

    # Static files: /outputs
    project_root = get_project_root()
    outputs_dir = project_root / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/outputs/{path:path}")
    async def serve_outputs(path: str):
        path_decoded = unquote(path)
        outputs_resolved = outputs_dir.resolve()
        for candidate in (path_decoded, path):
            try:
                file_path = (outputs_dir / candidate).resolve()
                if not str(file_path).startswith(str(outputs_resolved)):
                    continue
                if file_path.is_file():
                    resp = FileResponse(path=str(file_path), filename=file_path.name)
                    if file_path.suffix.lower() == ".pdf":
                        resp.headers["Content-Disposition"] = "inline"
                    return resp
            except Exception as e:
                log.debug(f"File path resolution failed: {candidate}, error: {e}")
                continue
        raise HTTPException(status_code=404, detail="Not found")

    log.info(f"Serving /outputs from {outputs_dir}")

    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    log.info("Backend ready")
    return app


app = create_app()
