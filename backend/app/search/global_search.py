"""Global search based on community summaries."""

from __future__ import annotations

from typing import Any, Dict, List

from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.config.prompts.clinical_prompts import (
    GLOBAL_SEARCH_MAP_PROMPT,
    GLOBAL_SEARCH_REDUCE_PROMPT,
    MAP_SYSTEM_PROMPT,
    REDUCE_SYSTEM_PROMPT,
    response_type,
)
from app.graph.neo4j_manager import clinical_graph_manager
from app.models.llm_factory import get_llm
from app.search.query_expansion import dedupe_source_items, empty_retrieval_stats


class GlobalSearch:
    """Community-level map-reduce retrieval."""

    def __init__(self):
        self.llm = get_llm()

        map_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", MAP_SYSTEM_PROMPT),
                ("human", GLOBAL_SEARCH_MAP_PROMPT),
            ]
        )
        self._map_chain = map_prompt | self.llm | StrOutputParser()

        reduce_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", REDUCE_SYSTEM_PROMPT),
                ("human", GLOBAL_SEARCH_REDUCE_PROMPT),
            ]
        )
        self._reduce_chain = reduce_prompt | self.llm | StrOutputParser()

    def search(self, query: str, level: int = 1) -> str:
        payload = self.search_with_metadata(query, level=level)
        return payload["context"]

    def search_with_metadata(self, query: str, level: int = 1) -> Dict[str, Any]:
        communities = self._get_communities(level)
        if not communities:
            communities = self._get_communities(0)
        if not communities:
            stats = empty_retrieval_stats()
            return {
                "context": "知识图谱中暂无社区数据，请先运行文档处理和图谱构建流程。",
                "stats": stats,
                "sources": [],
                "matched_communities": [],
                "has_evidence": False,
            }

        mapped_results = self._map_phase(query, communities)
        matched_items = [
            item
            for item in mapped_results
            if item.get("result")
            and "无相关信息" not in item["result"]
            and len(item["result"].strip()) > 10
        ]

        if not matched_items:
            stats = empty_retrieval_stats()
            return {
                "context": "在知识图谱的社区摘要中未找到与该问题相关的信息。",
                "stats": stats,
                "sources": [],
                "matched_communities": [],
                "has_evidence": False,
            }

        reduced = self._reduce_phase(
            query,
            [item["result"] for item in matched_items],
        )
        sources = dedupe_source_items(
            [
                {
                    "id": f"community:{item['community'].get('community_id', index)}",
                    "source_type": "community",
                    "label": "社区摘要",
                    "title": f"社区摘要 {item['community'].get('community_id', index)}".strip(),
                    "content": item["community"].get("summary", ""),
                }
                for index, item in enumerate(matched_items[:6], start=1)
                if item["community"].get("summary")
            ]
        )
        stats = empty_retrieval_stats()
        stats["community_hits"] = len(matched_items)
        stats["evidence_total"] = len(sources)
        stats["knowledge_backed"] = len(sources) > 0

        return {
            "context": reduced,
            "stats": stats,
            "sources": sources,
            "matched_communities": [item["community"] for item in matched_items],
            "has_evidence": bool(sources),
        }

    def _get_communities(self, level: int) -> List[Dict]:
        try:
            return clinical_graph_manager.get_communities_by_level(level)
        except Exception as exc:
            print(f"[GlobalSearch] 获取社区失败: {exc}")
            return []

    def _map_phase(self, query: str, communities: List[Dict]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for community in communities:
            summary = community.get("summary", "")
            if not summary:
                continue
            try:
                result = self._map_chain.invoke(
                    {
                        "question": query,
                        "context_data": summary,
                    }
                )
                results.append({"community": community, "result": result})
            except Exception as exc:
                print(
                    f"[GlobalSearch] Map 阶段失败（社区 {community.get('community_id')}）: {exc}"
                )
        return results

    def _reduce_phase(self, query: str, intermediate_results: List[str]) -> str:
        report_data = "\n\n---\n\n".join(
            f"[信息来源 {index + 1}]\n{result}"
            for index, result in enumerate(intermediate_results)
        )
        try:
            return self._reduce_chain.invoke(
                {
                    "question": query,
                    "report_data": report_data,
                    "response_type": response_type,
                }
            )
        except Exception as exc:
            print(f"[GlobalSearch] Reduce 阶段失败: {exc}")
            return f"综合分析失败，原始信息摘录：\n\n{report_data[:2000]}"
