"""Background knowledge-base ingestion and graph-build task manager."""

from __future__ import annotations

import asyncio
import copy
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy import func, select

from app.config.database import AsyncSessionLocal
from app.models.db_models import Chunk, Community, Document, Entity, Relationship
from app.services.ingestion_service import IngestionService


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeBaseTaskManager:
    """Runs ingestion and graph-build work in background asyncio tasks."""

    def __init__(self):
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._default_path = "/app/knowledge_base"
        self._ingestion_service = IngestionService()
        self._state: Dict[str, Any] = self._build_idle_state()

    def _build_idle_state(self) -> Dict[str, Any]:
        return {
            "job_id": None,
            "status": "idle",
            "stage": "idle",
            "message": "知识库空闲。",
            "reason": None,
            "path": self._default_path,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "result": None,
        }

    def _set_state(self, **updates: Any) -> None:
        with self._lock:
            self._state.update(updates)

    def _snapshot(self) -> Dict[str, Any]:
        with self._lock:
            data = copy.deepcopy(self._state)
            data["active"] = bool(self._thread and self._thread.is_alive())
        return data

    def _count_source_files(self, path: str) -> int:
        root = Path(path)
        if not root.exists():
            return 0

        patterns = ("**/*.docx", "**/*.pdf")
        return sum(len(list(root.glob(pattern))) for pattern in patterns)

    async def _read_counts(self) -> Dict[str, int]:
        async with AsyncSessionLocal() as db:
            return {
                "documents": await db.scalar(select(func.count(Document.id))) or 0,
                "chunks": await db.scalar(select(func.count(Chunk.id))) or 0,
                "entities": await db.scalar(select(func.count(Entity.id))) or 0,
                "relationships": await db.scalar(select(func.count(Relationship.id))) or 0,
                "communities": await db.scalar(select(func.count(Community.id))) or 0,
            }

    async def get_status(self) -> Dict[str, Any]:
        snapshot = self._snapshot()
        snapshot["source_files"] = self._count_source_files(
            snapshot.get("path") or self._default_path
        )
        snapshot["counts"] = await self._read_counts()
        return snapshot

    async def ensure_seeded(self) -> Dict[str, Any]:
        """Auto-bootstrap the knowledge base when the service starts with an empty DB."""
        counts = await self._read_counts()
        source_files = self._count_source_files(self._default_path)

        if source_files == 0:
            return await self.get_status()

        if counts["documents"] == 0 or counts["chunks"] == 0:
            return await self.start_ingestion(
                path=self._default_path,
                build_graph=True,
                reason="startup_seed",
            )

        if counts["chunks"] > 0 and counts["entities"] == 0:
            return await self.start_rebuild(reason="startup_rebuild")

        return await self.get_status()

    async def start_ingestion(
        self,
        *,
        path: str = "/app/knowledge_base",
        build_graph: bool = True,
        reason: str = "manual_ingest",
    ) -> Dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return await self.get_status()

            self._state = {
                "job_id": str(uuid4()),
                "status": "running",
                "stage": "queued",
                "message": "知识库任务已排队，准备开始导入。",
                "reason": reason,
                "path": path,
                "started_at": _utcnow_iso(),
                "finished_at": None,
                "error": None,
                "result": None,
            }
            self._thread = threading.Thread(
                target=self._run_coroutine_in_thread,
                args=(self._run_ingestion(path=path, build_graph=build_graph, reason=reason),),
                daemon=True,
            )
            self._thread.start()

        return await self.get_status()

    async def start_rebuild(self, *, reason: str = "manual_rebuild") -> Dict[str, Any]:
        counts = await self._read_counts()
        if counts["chunks"] == 0:
            source_files = self._count_source_files(self._default_path)
            if source_files > 0:
                return await self.start_ingestion(
                    path=self._default_path,
                    build_graph=True,
                    reason=f"{reason}_seed",
                )

        with self._lock:
            if self._thread and self._thread.is_alive():
                return await self.get_status()

            self._state = {
                "job_id": str(uuid4()),
                "status": "running",
                "stage": "queued",
                "message": "图谱重建任务已排队。",
                "reason": reason,
                "path": self._default_path,
                "started_at": _utcnow_iso(),
                "finished_at": None,
                "error": None,
                "result": None,
            }
            self._thread = threading.Thread(
                target=self._run_coroutine_in_thread,
                args=(self._run_rebuild(reason=reason),),
                daemon=True,
            )
            self._thread.start()

        return await self.get_status()

    def _run_coroutine_in_thread(self, coroutine) -> None:
        asyncio.run(coroutine)

    async def _run_ingestion(self, *, path: str, build_graph: bool, reason: str) -> None:
        try:
            self._set_state(
                stage="ingesting",
                message="正在导入知识库文档和文本块，请稍候。",
            )

            async with AsyncSessionLocal() as db:
                results = await self._ingestion_service.ingest_directory(
                    path, db, build_graph=False
                )

            processed = sum(1 for item in results if item.get("document_id"))
            failed = sum(1 for item in results if item.get("error"))

            graph_stats = None
            if build_graph:
                self._set_state(
                    stage="building_graph",
                    message="文档已导入，正在抽取实体关系并构建知识图谱。",
                )
                async with AsyncSessionLocal() as db:
                    graph_stats = await self._ingestion_service.rebuild_graph(db)

            counts = await self._read_counts()
            if processed == 0 and failed == 0:
                message = "未在知识库目录中发现可导入的文档。"
            else:
                message = "知识库导入完成。"

            self._set_state(
                status="completed",
                stage="completed",
                message=message,
                finished_at=_utcnow_iso(),
                error=None,
                result={
                    "documents_processed": processed,
                    "documents_failed": failed,
                    "graph": graph_stats,
                    "counts": counts,
                    "reason": reason,
                },
            )
        except Exception as exc:
            self._set_state(
                status="failed",
                stage="failed",
                message="知识库任务执行失败。",
                finished_at=_utcnow_iso(),
                error=str(exc),
                result=None,
            )

    async def _run_rebuild(self, *, reason: str) -> None:
        try:
            self._set_state(
                stage="building_graph",
                message="正在根据现有文本块重建知识图谱。",
            )

            async with AsyncSessionLocal() as db:
                graph_stats = await self._ingestion_service.rebuild_graph(db)

            counts = await self._read_counts()
            self._set_state(
                status="completed",
                stage="completed",
                message="知识图谱重建完成。",
                finished_at=_utcnow_iso(),
                error=None,
                result={
                    "graph": graph_stats,
                    "counts": counts,
                    "reason": reason,
                },
            )
        except Exception as exc:
            self._set_state(
                status="failed",
                stage="failed",
                message="知识图谱重建失败。",
                finished_at=_utcnow_iso(),
                error=str(exc),
                result=None,
            )


knowledge_base_task_manager = KnowledgeBaseTaskManager()
