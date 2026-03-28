"""文档摄入流水线：文件 → 分块 → 向量嵌入 → PostgreSQL"""
import hashlib
import asyncio
from pathlib import Path
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.db_models import Document, Chunk
from app.models.llm_factory import get_embeddings
from app.pipelines.file_reader import read_document, Section
from app.pipelines.text_chunker import MedicalTextChunker
from app.config.settings import settings


class DocumentProcessor:
    """文档处理器：读取文件、分块、嵌入并存储到 PostgreSQL"""

    def __init__(self):
        self.chunker = MedicalTextChunker()
        self.embeddings = get_embeddings()
        self.batch_size = settings.performance.embedding_batch_size

    # ──────────────────────────────────────────────
    # 主入口
    # ──────────────────────────────────────────────

    async def process_file(self, file_path: str, db: AsyncSession) -> Document:
        """
        单文件完整处理流程：
        1. 检查是否已处理（按文件名去重）
        2. 读取文档结构
        3. 分块
        4. 批量嵌入
        5. 存储 Document + Chunk 记录
        """
        path = Path(file_path)
        filename = path.name

        # 1. 去重检查
        existing = await db.execute(
            select(Document).where(Document.filename == filename)
        )
        doc = existing.scalar_one_or_none()
        if doc is not None:
            return doc

        # 2. 读取文档
        sections: List[Section] = read_document(file_path)

        # 3. 分块（带元数据）
        all_chunks: List[dict] = []
        for section in sections:
            chunks = self.chunker.chunk_with_metadata(
                text=section.content,
                chapter=section.chapter,
                section=section.section,
            )
            all_chunks.extend(chunks)

        if not all_chunks:
            # 文档为空，仍创建 Document 记录
            doc = Document(
                filename=filename,
                file_type=path.suffix.lower().lstrip("."),
                file_path=str(path.resolve()),
                chunk_count=0,
            )
            db.add(doc)
            await db.commit()
            await db.refresh(doc)
            return doc

        # 4. 批量嵌入
        texts = [c["content"] for c in all_chunks]
        embeddings = await self.embed_chunks_batch(texts)

        # 5. 存储 Document
        doc = Document(
            filename=filename,
            file_type=path.suffix.lower().lstrip("."),
            file_path=str(path.resolve()),
            chunk_count=len(all_chunks),
        )
        db.add(doc)
        await db.flush()  # 获取自增 id

        # 6. 存储 Chunk
        for i, (chunk_meta, embedding) in enumerate(zip(all_chunks, embeddings)):
            chunk_id = self.generate_chunk_id(doc.id, i)
            chunk = Chunk(
                id=chunk_id,
                document_id=doc.id,
                content=chunk_meta["content"],
                chunk_index=i,
                chapter=chunk_meta.get("chapter", ""),
                section=chunk_meta.get("section", ""),
                embedding=embedding,
            )
            db.add(chunk)

        await db.commit()
        await db.refresh(doc)
        return doc

    # ──────────────────────────────────────────────
    # 嵌入批处理
    # ──────────────────────────────────────────────

    async def embed_chunks_batch(self, texts: List[str]) -> List[List[float]]:
        """
        批量嵌入文本列表。
        使用 asyncio.to_thread 将同步嵌入 API 移到线程池中执行。
        按 embedding_batch_size 分批，避免超出 API 限制。
        """
        all_embeddings: List[List[float]] = []

        for start in range(0, len(texts), self.batch_size):
            batch = texts[start: start + self.batch_size]
            try:
                batch_embeddings = await asyncio.to_thread(
                    self.embeddings.embed_documents, batch
                )
                all_embeddings.extend(batch_embeddings)
            except Exception as e:
                # 批次失败时用零向量占位，避免整体流程中断
                dim = settings.embedding.dimension
                placeholder = [[0.0] * dim for _ in batch]
                all_embeddings.extend(placeholder)
                print(f"[DocumentProcessor] 嵌入批次失败 (start={start}): {e}")

        return all_embeddings

    # ──────────────────────────────────────────────
    # 工具方法
    # ──────────────────────────────────────────────

    def generate_chunk_id(self, document_id: int, chunk_index: int) -> str:
        """生成确定性块 ID（SHA-256 前 32 字符）"""
        raw = f"{document_id}_{chunk_index}".encode()
        return hashlib.sha256(raw).hexdigest()[:32]
