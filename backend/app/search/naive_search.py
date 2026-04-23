"""Naive chunk retrieval with vector search and keyword fallback."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.models.llm_factory import get_embeddings
from app.search.query_expansion import (
    build_query_expansion_plan,
    empty_retrieval_stats,
)


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
        query_plan: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        payload = await self.search_with_metadata(
            query,
            db,
            top_k=top_k,
            threshold=threshold,
            query_plan=query_plan,
        )
        return payload["items"]

    async def search_with_metadata(
        self,
        query: str,
        db: AsyncSession,
        top_k: Optional[int] = None,
        threshold: Optional[float] = None,
        query_plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        k = top_k or self.top_k
        thresh = threshold if threshold is not None else self.threshold
        plan = query_plan or self._build_query_plan(query)

        results: List[Dict] = []
        try:
            query_embedding = await asyncio.to_thread(
                self.embeddings.embed_query,
                plan["combined_query"],
            )
            results = await self._vector_search(query_embedding, db, k, thresh)
        except Exception:
            results = []

        if not results:
            results = await self._keyword_search(
                query,
                db,
                k,
                keyword_terms=plan["keyword_terms"],
            )

        results = self._dedupe_results(results)[:k]
        sources = self._build_sources(results)
        stats = empty_retrieval_stats(
            used_query_expansion=plan["used_query_expansion"]
        )
        stats["chunk_hits"] = len(results)
        stats["evidence_total"] = len(sources)
        stats["knowledge_backed"] = len(sources) > 0

        return {
            "items": results,
            "stats": stats,
            "sources": sources,
            "query_plan": plan,
            "has_evidence": bool(sources),
        }

    def _build_query_plan(self, query: str) -> Dict[str, Any]:
        apply_targets = {
            item.strip().lower()
            for item in settings.search.query_expansion_apply_to.split(",")
            if item.strip()
        }
        enabled = (
            settings.search.query_expansion_enabled
            and settings.search.query_expansion_mode == "synonym"
            and "naive" in apply_targets
        )
        return build_query_expansion_plan(
            query,
            enabled=enabled,
            max_terms=settings.search.query_expansion_max_terms,
        )

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
        *,
        keyword_terms: Optional[List[str]] = None,
    ) -> List[Dict]:
        clean_query = query.strip()
        if not clean_query:
            return []

        terms = keyword_terms or [clean_query, *_tokenize(clean_query)]
        where_clauses = []
        params: Dict[str, object] = {"limit": max(top_k * 6, 30)}

        for index, pattern in enumerate(terms[:10]):
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

        ranked = sorted(
            rows,
            key=lambda row: self._score_chunk(row, clean_query, terms),
            reverse=True,
        )

        items: List[Dict] = []
        for row in ranked[:top_k]:
            score = self._score_chunk(row, clean_query, terms)
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

    def _score_chunk(self, row, query: str, keyword_terms: Optional[List[str]] = None) -> float:
        chapter = row.chapter or ""
        section = row.section or ""
        content = row.content or ""
        blob = f"{chapter} {section} {content}"

        score = 0.0
        if query and query in blob:
            score += 10

        for token in _tokenize(query):
            score += blob.count(token) * 1.5
            if token in chapter:
                score += 2
            if token in section:
                score += 2

        for term in keyword_terms or []:
            if term == query:
                continue
            score += blob.count(term) * 0.7
            if term in chapter:
                score += 1
            if term in section:
                score += 1

        return score

    def _dedupe_results(self, results: List[Dict]) -> List[Dict]:
        seen_ids: set[str] = set()
        deduped: List[Dict] = []
        for result in results:
            result_id = str(result.get("id"))
            if result_id in seen_ids:
                continue
            seen_ids.add(result_id)
            deduped.append(result)
        return deduped

    def _build_sources(self, results: List[Dict]) -> List[Dict[str, Any]]:
        sources: List[Dict[str, Any]] = []
        for result in results:
            title_parts = []
            if result.get("chapter"):
                title_parts.append(result["chapter"])
            if result.get("section"):
                title_parts.append(result["section"])
            title = " > ".join(title_parts) or result.get("document_name", "文献片段")
            sources.append(
                {
                    "id": f"chunk:{result.get('id')}",
                    "source_type": "chunk",
                    "label": "文献片段",
                    "title": title,
                    "content": result.get("content", ""),
                    "document_name": result.get("document_name", ""),
                }
            )
        return sources

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
