"""Knowledge base management router"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.config.database import get_db
from app.services.ingestion_service import IngestionService
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
    db: AsyncSession = Depends(get_db),
):
    """Ingest all documents from knowledge base directory"""
    if not os.path.isdir(path):
        raise HTTPException(400, f"Directory not found: {path}")
    results = await ingestion_service.ingest_directory(path, db, build_graph=build_graph)
    return {"status": "success", "results": results}


@router.post("/rebuild-graph")
async def rebuild_graph(db: AsyncSession = Depends(get_db)):
    """Rebuild knowledge graph data from already ingested chunks."""
    try:
        graph_stats = await ingestion_service.rebuild_graph(db)
        return {"status": "success", "graph": graph_stats}
    except Exception as e:
        raise HTTPException(500, f"Graph rebuild failed: {str(e)}")
