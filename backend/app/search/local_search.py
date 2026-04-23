"""Local graph-aware retrieval with vector search and lexical fallback."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.graph.neo4j_manager import clinical_graph_manager
from app.models.llm_factory import get_embeddings
from app.search.query_expansion import (
    build_query_expansion_plan,
    dedupe_source_items,
    empty_retrieval_stats,
)


def _tokenize(query: str) -> List[str]:
    return [
        token
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", query)
        if token.strip()
    ]


class LocalSearch:
    """Retrieve chunks + entities + graph expansion, with graceful fallback."""

    def __init__(self):
        self.embeddings = get_embeddings()

    async def search(
        self,
        query: str,
        db: AsyncSession,
        query_plan: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        plan = query_plan or self._build_query_plan(query)
        try:
            query_embedding = await asyncio.to_thread(
                self.embeddings.embed_query,
                plan["combined_query"],
            )
            entity_names = await self._find_entities_by_embedding(
                query_embedding, db, top_k=settings.search.local_top_entities
            )
            chunks = await self._search_chunks(query_embedding, db)
        except Exception:
            entity_names = await self._find_entities_by_text(
                query,
                db,
                top_k=settings.search.local_top_entities,
                keyword_terms=plan["keyword_terms"],
            )
            chunks = await self._search_chunks_by_text(
                query,
                db,
                top_k=settings.search.local_top_chunks,
                keyword_terms=plan["keyword_terms"],
            )

        if not entity_names:
            entity_names = await self._find_entities_by_text(
                query,
                db,
                top_k=settings.search.local_top_entities,
                keyword_terms=plan["keyword_terms"],
            )
        if not chunks:
            chunks = await self._search_chunks_by_text(
                query,
                db,
                top_k=settings.search.local_top_chunks,
                keyword_terms=plan["keyword_terms"],
            )

        graph_context = {}
        if entity_names:
            try:
                graph_context = await asyncio.to_thread(
                    clinical_graph_manager.graph_expansion,
                    entity_names,
                    settings.search.local_top_chunks,
                    settings.search.local_top_communities,
                    settings.search.local_top_inside_rels,
                    settings.search.local_top_outside_rels,
                )
            except Exception:
                graph_context = {}

        graph_entities = graph_context.get("entities", [])
        inside_rels = graph_context.get("inside_rels", [])
        outside_rels = graph_context.get("outside_rels", [])
        communities = graph_context.get("communities", [])
        sources = self._build_sources(
            chunks=chunks,
            graph_entities=graph_entities,
            inside_rels=inside_rels,
            outside_rels=outside_rels,
            communities=communities,
        )
        stats = empty_retrieval_stats(
            used_query_expansion=plan["used_query_expansion"]
        )
        stats["chunk_hits"] = len(chunks)
        stats["entity_hits"] = len(graph_entities)
        stats["community_hits"] = len(communities)
        stats["relation_hits"] = len(inside_rels) + len(outside_rels)
        stats["evidence_total"] = len(sources)
        stats["knowledge_backed"] = len(sources) > 0

        return {
            "entities": entity_names,
            "graph_entities": graph_entities,
            "inside_rels": inside_rels,
            "outside_rels": outside_rels,
            "communities": communities,
            "chunks": chunks,
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
            and "hybrid" in apply_targets
        )
        return build_query_expansion_plan(
            query,
            enabled=enabled,
            max_terms=settings.search.query_expansion_max_terms,
        )

    async def _find_entities_by_embedding(
        self,
        query_embedding: List[float],
        db: AsyncSession,
        top_k: int = 10,
    ) -> List[str]:
        vec_str = "[" + ",".join(str(value) for value in query_embedding) + "]"
        sql = text(
            """
            SELECT name
            FROM entities
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
            """
        )
        try:
            result = await db.execute(sql, {"vec": vec_str, "k": top_k})
            rows = result.fetchall()
            return [row.name for row in rows]
        except Exception:
            return []

    async def _find_entities_by_text(
        self,
        query: str,
        db: AsyncSession,
        top_k: int = 10,
        *,
        keyword_terms: Optional[List[str]] = None,
    ) -> List[str]:
        clean_query = query.strip()
        if not clean_query:
            return []

        patterns = keyword_terms or [clean_query, *_tokenize(clean_query)]
        where_clauses = []
        params: Dict[str, object] = {
            "query": clean_query,
            "limit": max(top_k * 6, 40),
        }

        for index, pattern in enumerate(patterns[:10]):
            key = f"pattern_{index}"
            params[key] = f"%{pattern}%"
            where_clauses.extend(
                [
                    f"name ILIKE :{key}",
                    f"COALESCE(description, '') ILIKE :{key}",
                ]
            )

        where_clauses.append(":query ILIKE '%' || name || '%'")

        sql = text(
            f"""
            SELECT id, name, entity_type, description
            FROM entities
            WHERE {' OR '.join(where_clauses)}
            LIMIT :limit
            """
        )
        result = await db.execute(sql, params)
        rows = result.fetchall()

        ranked = sorted(
            rows,
            key=lambda row: self._score_entity(
                row.name,
                row.description,
                clean_query,
                patterns,
            ),
            reverse=True,
        )

        names: List[str] = []
        seen = set()
        for row in ranked:
            score = self._score_entity(
                row.name,
                row.description,
                clean_query,
                patterns,
            )
            if score <= 0 or row.name in seen:
                continue
            seen.add(row.name)
            names.append(row.name)
            if len(names) >= top_k:
                break

        return names

    def _score_entity(
        self,
        name: str,
        description: Optional[str],
        query: str,
        keyword_terms: Optional[List[str]] = None,
    ) -> float:
        description = description or ""
        score = 0.0
        if name and name in query:
            score += 12
        if query in name:
            score += 8
        if query and query in description:
            score += 4
        for token in _tokenize(query):
            if token in name:
                score += 3
            if token in description:
                score += 1
        for term in keyword_terms or []:
            if term == query:
                continue
            if term in name:
                score += 1.2
            if term in description:
                score += 0.4
        return score

    async def _search_chunks(
        self,
        query_embedding: List[float],
        db: AsyncSession,
        top_k: Optional[int] = None,
    ) -> List[Dict]:
        k = top_k or settings.search.local_top_chunks
        vec_str = "[" + ",".join(str(value) for value in query_embedding) + "]"
        sql = text(
            """
            SELECT
                c.id,
                c.content,
                c.chapter,
                c.section,
                d.filename AS document_name,
                1 - (c.embedding <=> CAST(:vec AS vector)) AS similarity
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE c.embedding IS NOT NULL
            ORDER BY c.embedding <=> CAST(:vec AS vector)
            LIMIT :k
            """
        )
        try:
            result = await db.execute(sql, {"vec": vec_str, "k": k})
            rows = result.fetchall()
        except Exception:
            return []

        return [
            {
                "id": row.id,
                "content": row.content,
                "chapter": row.chapter or "",
                "section": row.section or "",
                "document_name": row.document_name,
                "similarity": float(row.similarity),
            }
            for row in rows
        ]

    async def _search_chunks_by_text(
        self,
        query: str,
        db: AsyncSession,
        top_k: Optional[int] = None,
        *,
        keyword_terms: Optional[List[str]] = None,
    ) -> List[Dict]:
        k = top_k or settings.search.local_top_chunks
        clean_query = query.strip()
        if not clean_query:
            return []

        patterns = keyword_terms or [clean_query, *_tokenize(clean_query)]
        where_clauses = []
        params: Dict[str, object] = {"limit": max(k * 6, 30)}

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
            key=lambda row: self._score_chunk(row, clean_query, patterns),
            reverse=True,
        )

        chunks: List[Dict] = []
        for row in ranked[:k]:
            score = self._score_chunk(row, clean_query, patterns)
            if score <= 0:
                continue
            chunks.append(
                {
                    "id": row.id,
                    "content": row.content,
                    "chapter": row.chapter or "",
                    "section": row.section or "",
                    "document_name": row.document_name,
                    "similarity": None,
                }
            )

        return chunks

    def _score_chunk(
        self,
        row,
        query: str,
        keyword_terms: Optional[List[str]] = None,
    ) -> float:
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
        for term in keyword_terms or []:
            if term == query:
                continue
            score += blob.count(term) * 0.7
            if term in chapter:
                score += 1
            if term in section:
                score += 1
        return score

    def _build_sources(
        self,
        *,
        chunks: List[Dict],
        graph_entities: List[Dict],
        inside_rels: List[Dict],
        outside_rels: List[Dict],
        communities: List[Dict],
    ) -> List[Dict[str, Any]]:
        sources: List[Dict[str, Any]] = []

        for chunk in chunks:
            title_parts = []
            if chunk.get("chapter"):
                title_parts.append(chunk["chapter"])
            if chunk.get("section"):
                title_parts.append(chunk["section"])
            title = " > ".join(title_parts) or chunk.get("document_name", "文献片段")
            sources.append(
                {
                    "id": f"chunk:{chunk.get('id')}",
                    "source_type": "chunk",
                    "label": "文献片段",
                    "title": title,
                    "content": chunk.get("content", ""),
                    "document_name": chunk.get("document_name", ""),
                }
            )

        for entity in graph_entities:
            description = entity.get("description") or "未提供实体描述。"
            sources.append(
                {
                    "id": f"entity:{entity.get('name', '')}",
                    "source_type": "entity",
                    "label": "相关实体",
                    "title": entity.get("name", "医学实体"),
                    "content": description,
                    "entity_type": entity.get("entity_type", ""),
                }
            )

        for rel in inside_rels + outside_rels:
            relation_title = (
                f"{rel.get('source', '')} --[{rel.get('rel_type', '')}]--> {rel.get('target', '')}"
            )
            sources.append(
                {
                    "id": (
                        f"relation:{rel.get('source', '')}:{rel.get('rel_type', '')}:"
                        f"{rel.get('target', '')}"
                    ),
                    "source_type": "relation",
                    "label": "实体关系",
                    "title": relation_title,
                    "content": rel.get("description", "") or "未提供关系说明。",
                }
            )

        for community in communities:
            summary = community.get("summary", "")
            if not summary:
                continue
            community_id = community.get("community_id", "")
            sources.append(
                {
                    "id": f"community:{community_id}",
                    "source_type": "community",
                    "label": "社区摘要",
                    "title": f"社区摘要 {community_id}".strip(),
                    "content": summary,
                }
            )

        return dedupe_source_items(sources)

    def format_context(self, search_result: Dict) -> str:
        parts = []
        ref_idx = 1

        chunks = search_result.get("chunks", [])
        if chunks:
            parts.append("## 相关文献片段")
            for chunk in chunks:
                header = f"[{ref_idx}]"
                if chunk.get("chapter"):
                    header += f" {chunk['chapter']}"
                if chunk.get("section"):
                    header += f" > {chunk['section']}"
                header += f"（{chunk.get('document_name', '')}）"
                parts.append(f"{header}\n{chunk['content']}")
                ref_idx += 1

        graph_entities = search_result.get("graph_entities", [])
        if graph_entities:
            parts.append("\n## 相关医学实体")
            for entity in graph_entities:
                description = entity.get("description", "")
                parts.append(
                    f"- **{entity.get('name', '')}**"
                    f"（{entity.get('entity_type', '')}）：{description}"
                )

        all_rels = search_result.get("inside_rels", []) + search_result.get("outside_rels", [])
        if all_rels:
            parts.append("\n## 实体关系")
            for rel in all_rels:
                parts.append(
                    f"- {rel.get('source', '')} "
                    f"--[{rel.get('rel_type', '')}]--> "
                    f"{rel.get('target', '')}：{rel.get('description', '')}"
                )

        communities = search_result.get("communities", [])
        if communities:
            parts.append("\n## 医学知识社区摘要")
            for community in communities:
                summary = community.get("summary", "")
                if summary:
                    parts.append(f"- {summary}")

        if not parts:
            return "未检索到相关临床资料。"

        return "\n\n".join(parts)

    def _empty_result(self) -> Dict:
        return {
            "entities": [],
            "graph_entities": [],
            "inside_rels": [],
            "outside_rels": [],
            "communities": [],
            "chunks": [],
            "stats": empty_retrieval_stats(),
            "sources": [],
            "query_plan": build_query_expansion_plan("", enabled=False),
            "has_evidence": False,
        }
