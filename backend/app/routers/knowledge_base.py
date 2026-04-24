"""Knowledge base management router"""

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.security import require_admin_api_key
from app.services.ingestion_service import IngestionService
from app.services.knowledge_base_task_service import knowledge_base_task_manager

router = APIRouter()
ingestion_service = IngestionService()
_ALLOWED_UPLOAD_SUFFIXES = {".docx"}
_ALLOWED_INGEST_ROOT = Path("/app/knowledge_base")


def _resolve_allowed_ingest_path(raw_path: str) -> Path:
    base_dir = _ALLOWED_INGEST_ROOT.resolve()
    requested = Path(raw_path or str(base_dir)).resolve()
    if requested != base_dir and base_dir not in requested.parents:
        raise HTTPException(400, "Only /app/knowledge_base and its subdirectories are allowed")
    if not requested.is_dir():
        raise HTTPException(400, f"Directory not found: {requested}")
    return requested


@router.get("/documents")
async def list_documents(db: AsyncSession = Depends(get_db)):
    """List all ingested documents."""
    return await ingestion_service.get_documents(db)


@router.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    build_graph: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Upload and ingest a document."""
    require_admin_api_key(request)

    filename = (file.filename or "").strip()
    suffix = os.path.splitext(filename)[1].lower()
    if suffix not in _ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(400, "Only .docx files are supported")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        result = await ingestion_service.ingest_file(tmp_path, db, build_graph=build_graph)
        return {"status": "success", **result}
    except Exception as exc:
        raise HTTPException(500, f"Ingestion failed: {str(exc)}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post("/ingest-directory")
async def ingest_directory(
    request: Request,
    path: str = "/app/knowledge_base",
    build_graph: bool = True,
):
    """Queue ingestion of all documents from the knowledge-base directory."""
    require_admin_api_key(request)
    target_path = _resolve_allowed_ingest_path(path)
    return await knowledge_base_task_manager.start_ingestion(
        path=str(target_path),
        build_graph=build_graph,
        reason="manual_ingest",
    )


@router.post("/rebuild-graph")
async def rebuild_graph(request: Request):
    """Queue a graph rebuild, or seed the KB first if the DB is empty."""
    require_admin_api_key(request)
    return await knowledge_base_task_manager.start_rebuild(reason="manual_rebuild")


@router.get("/status")
async def knowledge_base_status():
    """Return the current background ingestion/build status plus DB counts."""
    return await knowledge_base_task_manager.get_status()
