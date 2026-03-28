"""Global Search：基于社区摘要的 Map-Reduce 全局检索"""
from typing import List, Dict

from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.models.llm_factory import get_llm
from app.graph.neo4j_manager import clinical_graph_manager
from app.config.prompts.clinical_prompts import (
    MAP_SYSTEM_PROMPT,
    REDUCE_SYSTEM_PROMPT,
    GLOBAL_SEARCH_MAP_PROMPT,
    GLOBAL_SEARCH_REDUCE_PROMPT,
    response_type,
)


class GlobalSearch:
    """社区级 Map-Reduce 全局检索"""

    def __init__(self):
        self.llm = get_llm()

        # Map 链
        map_prompt = ChatPromptTemplate.from_messages([
            ("system", MAP_SYSTEM_PROMPT),
            ("human", GLOBAL_SEARCH_MAP_PROMPT),
        ])
        self._map_chain = map_prompt | self.llm | StrOutputParser()

        # Reduce 链
        reduce_prompt = ChatPromptTemplate.from_messages([
            ("system", REDUCE_SYSTEM_PROMPT),
            ("human", GLOBAL_SEARCH_REDUCE_PROMPT),
        ])
        self._reduce_chain = reduce_prompt | self.llm | StrOutputParser()

    # ──────────────────────────────────────────────
    # 主检索
    # ──────────────────────────────────────────────

    def search(self, query: str, level: int = 1) -> str:
        """
        全局 Map-Reduce 检索：
        1. 获取指定层级的所有社区摘要
        2. Map：对每个社区提取相关信息
        3. Reduce：综合所有 Map 结果生成最终回答
        """
        communities = self._get_communities(level)
        if not communities:
            # 尝试 level=0
            communities = self._get_communities(0)
        if not communities:
            return "知识图谱中暂无社区数据，请先运行文档处理和图谱构建流程。"

        # Map 阶段
        intermediate_results = self._map_phase(query, communities)

        # 过滤无效结果
        valid_results = [
            r for r in intermediate_results
            if r and "无相关信息" not in r and len(r.strip()) > 10
        ]

        if not valid_results:
            return "在知识图谱的社区摘要中未找到与该问题相关的信息。"

        # Reduce 阶段
        return self._reduce_phase(query, valid_results)

    # ──────────────────────────────────────────────
    # Map & Reduce
    # ──────────────────────────────────────────────

    def _get_communities(self, level: int) -> List[Dict]:
        """从 Neo4j 获取指定层级的社区摘要"""
        try:
            return clinical_graph_manager.get_communities_by_level(level)
        except Exception as e:
            print(f"[GlobalSearch] 获取社区失败: {e}")
            return []

    def _map_phase(self, query: str, communities: List[Dict]) -> List[str]:
        """Map 阶段：并行（实际串行）从每个社区摘要中提取相关信息"""
        results = []
        for community in communities:
            summary = community.get("summary", "")
            if not summary:
                continue
            try:
                result = self._map_chain.invoke({
                    "question": query,
                    "context_data": summary,
                })
                results.append(result)
            except Exception as e:
                print(f"[GlobalSearch] Map 阶段失败（社区 {community.get('community_id')}）: {e}")
        return results

    def _reduce_phase(self, query: str, intermediate_results: List[str]) -> str:
        """Reduce 阶段：综合所有中间结果生成最终回答"""
        # 将所有中间结果合并，每条加编号
        report_data = "\n\n---\n\n".join(
            f"[信息来源 {i+1}]\n{result}"
            for i, result in enumerate(intermediate_results)
        )
        try:
            return self._reduce_chain.invoke({
                "question": query,
                "report_data": report_data,
                "response_type": response_type,
            })
        except Exception as e:
            print(f"[GlobalSearch] Reduce 阶段失败: {e}")
            return f"综合分析失败，原始信息摘录：\n\n{report_data[:2000]}"
