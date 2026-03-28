"""Naive chunk retrieval with vector search and keyword fallback."""

import asyncio
import re
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.models.llm_factory import get_embeddings


def _tokenize(query: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", query)
        if token.strip()
    ]


class NaiveSearch:
    """Chunk retrieval used by Naive/Hybrid/Fusion agents."""

    def __init__(self):
        self.embeddings = get_embeddings()
        self.top_k = settings.search.top_k
        self.threshold = settings.search.similarity_threshold

    async def search(
        self,
        query: str,
        db: AsyncSession,
        top_k: Optional[int] = None,
        threshold: Optional[float] = None,
    ) -> List[Dict]:
        k = top_k or self.top_k
        thresh = threshold if threshold is not None else self.threshold

        try:
            query_embedding = await asyncio.to_thread(self.embeddings.embed_query, query)
            return await self._vector_search(query_embedding, db, k, thresh)
        except Exception:
            return await self._keyword_search(query, db, k)

    async def _vector_search(
        self,
        query_embedding: List[float],
        db: AsyncSession,
        top_k: int,
        threshold: float,
    ) -> List[Dict]:
        vec_str = "[" + ",".join(str(value) for value in query_embedding) + "]"
        sql = text(
            """
            SELECT
                c.id,
                c.content,
                c.chapter,
                c.section,
                c.chunk_index,
                1 - (c.embedding <=> CAST(:query_vec AS vector)) AS similarity,
                d.filename AS document_name
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE 1 - (c.embedding <=> CAST(:query_vec AS vector)) >= :threshold
            ORDER BY c.embedding <=> CAST(:query_vec AS vector)
            LIMIT :top_k
            """
        )

        try:
            result = await db.execute(
                sql,
                {
                    "query_vec": vec_str,
                    "threshold": threshold,
                    "top_k": top_k,
                },
            )
            rows = result.fetchall()
        except Exception:
            return []

        return [
            {
                "id": row.id,
                "content": row.content,
                "chapter": row.chapter or "",
                "section": row.section or "",
                "chunk_index": row.chunk_index,
                "similarity": float(row.similarity),
                "document_name": row.document_name,
            }
            for row in rows
        ]

    async def _keyword_search(
        self,
        query: str,
        db: AsyncSession,
        top_k: int,
    ) -> List[Dict]:
        clean_query = query.strip()
        if not clean_query:
            return []

        tokens = _tokenize(clean_query)
        patterns = [clean_query, *tokens]

        where_clauses = []
        params: Dict[str, object] = {"limit": max(top_k * 6, 30)}

        for index, pattern in enumerate(patterns[:10]):
            key = f"pattern_{index}"
            params[key] = f"%{pattern}%"
            where_clauses.extend(
                [
                    f"c.content ILIKE :{key}",
                    f"COALESCE(c.chapter, '') ILIKE :{key}",
                    f"COALESCE(c.section, '') ILIKE :{key}",
                ]
            )

        sql = text(
            f"""
            SELECT
                c.id,
                c.content,
                c.chapter,
                c.section,
                c.chunk_index,
                d.filename AS document_name
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE {' OR '.join(where_clauses)}
            LIMIT :limit
            """
        )
        result = await db.execute(sql, params)
        rows = result.fetchall()

        ranked = sorted(rows, key=lambda row: self._score_chunk(row, clean_query), reverse=True)

        items: List[Dict] = []
        for row in ranked[:top_k]:
            score = self._score_chunk(row, clean_query)
            if score <= 0:
                continue
            items.append(
                {
                    "id": row.id,
                    "content": row.content,
                    "chapter": row.chapter or "",
                    "section": row.section or "",
                    "chunk_index": row.chunk_index,
                    "similarity": None,
                    "document_name": row.document_name,
                    "keyword_score": score,
                }
            )

        return items

    def _score_chunk(self, row, query: str) -> float:
        chapter = row.chapter or ""
        section = row.section or ""
        content = row.content or ""
        blob = f"{chapter} {section} {content}"

        score = 0.0
        if query in blob:
            score += 8

        for token in _tokenize(query):
            score += blob.count(token) * 1.5
            if token in chapter:
                score += 2
            if token in section:
                score += 2

        return score

    def format_context(self, results: List[Dict]) -> str:
        if not results:
            return "未检索到相关临床资料。"

        parts = []
        for index, result in enumerate(results, 1):
            header = f"[{index}]"
            if result.get("chapter"):
                header += f" {result['chapter']}"
            if result.get("section"):
                header += f" > {result['section']}"

            if result.get("similarity") is not None:
                header += (
                    f"（来源：{result['document_name']}，相似度："
                    f"{result['similarity']:.3f}）"
                )
            else:
                header += f"（来源：{result['document_name']}）"

            parts.append(f"{header}\n{result['content']}")

        return "\n\n---\n\n".join(parts)
