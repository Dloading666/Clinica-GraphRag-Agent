"""Knowledge base management router"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.services.ingestion_service import IngestionService
from app.services.knowledge_base_task_service import knowledge_base_task_manager
import shutil
import os
import tempfile

router = APIRouter()
ingestion_service = IngestionService()


@router.get("/documents")
async def list_documents(db: AsyncSession = Depends(get_db)):
    """List all ingested documents"""
    return await ingestion_service.get_documents(db)


@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    build_graph: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Upload and ingest a document"""
    if not file.filename.endswith((".docx", ".pdf")):
        raise HTTPException(400, "Only .docx and .pdf files supported")

    # Save to temp file
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        result = await ingestion_service.ingest_file(tmp_path, db, build_graph=build_graph)
        return {"status": "success", **result}
    except Exception as e:
        raise HTTPException(500, f"Ingestion failed: {str(e)}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post("/ingest-directory")
async def ingest_directory(
    path: str = "/app/knowledge_base",
    build_graph: bool = True,
):
    """Queue ingestion of all documents from the knowledge-base directory."""
    if not os.path.isdir(path):
        raise HTTPException(400, f"Directory not found: {path}")
    return await knowledge_base_task_manager.start_ingestion(
        path=path,
        build_graph=build_graph,
        reason="manual_ingest",
    )


@router.post("/rebuild-graph")
async def rebuild_graph():
    """Queue a graph rebuild, or seed the KB first if the DB is empty."""
    return await knowledge_base_task_manager.start_rebuild(reason="manual_rebuild")


@router.get("/status")
async def knowledge_base_status():
    """Return the current background ingestion/build status plus DB counts."""
    return await knowledge_base_task_manager.get_status()
