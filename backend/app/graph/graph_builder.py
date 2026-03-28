"""图谱构建编排器：文档 → 实体抽取 → 社区检测"""
from typing import Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.db_models import Chunk, Document
from app.graph.entity_extractor import EntityRelationExtractor
from app.graph.community_detector import CommunityDetector
from app.config.settings import settings


class GraphBuilder:
    """全流程图谱构建编排器"""

    def __init__(self):
        self.extractor = EntityRelationExtractor()
        self.community_detector = CommunityDetector()

    # ──────────────────────────────────────────────
    # 主入口
    # ──────────────────────────────────────────────

    async def build_from_documents(
        self,
        db: AsyncSession,
        document_ids: Optional[List[int]] = None,
    ) -> Dict:
        """
        完整图谱构建流程：
        1. 从 PostgreSQL 加载文本块（可按 document_ids 过滤）
        2. 对每个文本块抽取实体和关系
        3. 运行社区检测并生成摘要
        返回统计字典。
        """
        # 1. 加载文本块
        stmt = select(Chunk)
        if document_ids:
            stmt = stmt.where(Chunk.document_id.in_(document_ids))
        result = await db.execute(stmt)
        chunks = result.scalars().all()

        if not chunks:
            return {
                "status": "no_chunks",
                "chunks_processed": 0,
                "communities_created": 0,
            }

        print(f"[GraphBuilder] 开始处理 {len(chunks)} 个文本块...")

        # 2. 转换为字典格式
        chunk_dicts = [
            {
                "id": chunk.id,
                "content": chunk.content,
                "document_id": chunk.document_id,
                "chapter": chunk.chapter or "",
                "section": chunk.section or "",
            }
            for chunk in chunks
        ]

        # 3. 分批抽取实体/关系
        batch_size = settings.performance.batch_size
        total_batches = (len(chunk_dicts) + batch_size - 1) // batch_size
        for batch_idx in range(total_batches):
            start = batch_idx * batch_size
            end = start + batch_size
            batch = chunk_dicts[start:end]
            print(f"[GraphBuilder] 实体抽取批次 {batch_idx + 1}/{total_batches}（{len(batch)} 块）")
            try:
                await self.extractor.process_chunks_async(batch, db)
                await db.commit()
            except Exception as e:
                print(f"[GraphBuilder] 批次 {batch_idx + 1} 抽取失败: {e}")
                await db.rollback()

        # 4. 社区检测
        print("[GraphBuilder] 开始社区检测...")
        communities_created = await self.community_detector.run_detection_and_summarize(db)

        return {
            "status": "completed",
            "chunks_processed": len(chunks),
            "communities_created": communities_created,
        }

    async def rebuild_communities(self, db: AsyncSession) -> int:
        """仅重新运行社区检测（不重新抽取实体）"""
        print("[GraphBuilder] 重新运行社区检测...")
        count = await self.community_detector.run_detection_and_summarize(db)
        print(f"[GraphBuilder] 社区重建完成，共 {count} 个社区")
        return count
