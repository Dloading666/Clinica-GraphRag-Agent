"""Ingestion service - orchestrates document processing"""
from typing import List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.db_models import Document
from app.pipelines.document_processor import DocumentProcessor
from app.graph.graph_builder import GraphBuilder


class IngestionService:
    def __init__(self):
        self.processor = DocumentProcessor()
        self.builder = GraphBuilder()

    async def ingest_file(
        self,
        file_path: str,
        db: AsyncSession,
        build_graph: bool = True,
    ) -> Dict:
        """
        Ingest a single file:
        1. Process file (chunk + embed + store in PG)
        2. Optionally build graph (extract entities + build KG)
        Returns stats dict.
        """
        doc = await self.processor.process_file(file_path, db)
        result = {
            "document_id": doc.id,
            "filename": doc.filename,
            "chunks": doc.chunk_count,
        }

        if build_graph:
            graph_stats = await self.builder.build_from_documents(db, [doc.id])
            result["graph"] = graph_stats

        return result

    async def ingest_directory(
        self,
        dir_path: str,
        db: AsyncSession,
        build_graph: bool = True,
    ) -> List[Dict]:
        """Ingest all .docx/.pdf files in a directory"""
        from pathlib import Path

        results = []
        patterns = ["**/*.docx", "**/*.pdf"]

        for pattern in patterns:
            for file_path in Path(dir_path).glob(pattern):
                try:
                    result = await self.ingest_file(
                        str(file_path), db, build_graph=False
                    )
                    results.append(result)
                except Exception as e:
                    results.append({"filename": file_path.name, "error": str(e)})

        # Build graph for all at once if requested
        if build_graph and results:
            try:
                graph_stats = await self.builder.build_from_documents(db)
                for r in results:
                    r["graph"] = graph_stats
            except Exception as e:
                for r in results:
                    r["graph_error"] = str(e)

        return results

    async def get_documents(self, db: AsyncSession) -> List[Dict]:
        """Get all ingested documents"""
        result = await db.execute(
            select(Document).order_by(Document.created_at.desc())
        )
        docs = result.scalars().all()
        return [
            {
                "id": d.id,
                "filename": d.filename,
                "file_type": d.file_type,
                "chunk_count": d.chunk_count,
                "created_at": str(d.created_at),
            }
            for d in docs
        ]

    async def rebuild_graph(self, db: AsyncSession) -> Dict:
        """Rebuild graph data from existing chunks."""
        return await self.builder.build_from_documents(db)
