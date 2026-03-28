"""Fusion RAG Agent - 多源检索 + LLM 重排序"""
from typing import Dict, List

from langchain.prompts import ChatPromptTemplate
from langchain.tools import Tool
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser

from app.agents.base import BaseAgent, run_async
from app.config.database import AsyncSessionLocal
from app.config.prompts.clinical_prompts import (
    LOCAL_SEARCH_SYSTEM_PROMPT,
    REDUCE_SYSTEM_PROMPT,
    response_type,
)
from app.search.global_search import GlobalSearch
from app.search.local_search import LocalSearch
from app.search.naive_search import NaiveSearch


# 重排序提示
_RERANK_PROMPT = """你是一名临床信息筛选专家。请从以下多个来源的检索结果中，选出与临床问题最相关的信息片段。

## 临床问题
{question}

## 检索结果（多个来源）
{all_results}

## 任务
1. 评估每个结果与问题的相关性（高/中/低）
2. 选出最相关的内容（不超过 5 个片段）
3. 按相关性从高到低排列
4. 输出格式：直接输出筛选后的内容，保持原文，用"---"分隔

请输出筛选和排序后的内容："""

_FUSION_GENERATE_PROMPT = """## 精选检索结果
{context}

## 临床问题
{question}

## 要求
请基于上述经过筛选和排序的最相关信息，提供{response_type}。
回答时注意整合多个来源的信息，保持一致性，并标注参考来源编号 [n]。"""


class FusionAgent(BaseAgent):
    """融合检索 Agent：多源检索 + LLM 重排序 + 综合生成"""

    def __init__(self):
        self.naive_search = NaiveSearch()
        self.local_search = LocalSearch()
        self.global_search = GlobalSearch()
        super().__init__()

    # ──────────────────────────────────────────────
    # Tool 配置
    # ──────────────────────────────────────────────

    def _setup_tools(self) -> List:
        def fusion_search_fn(query: str) -> str:
            """Fusion search: aggregates results from vector, graph, and global search"""
            async def _async():
                import asyncio
                async with AsyncSessionLocal() as db:
                    # 并发执行三种检索
                    naive_task = self.naive_search.search(query, db)
                    local_task = self.local_search.search(query, db)
                    naive_results, local_result = await asyncio.gather(
                        naive_task, local_task, return_exceptions=True
                    )

                    all_parts = []
                    idx = 1

                    # 向量检索结果
                    if isinstance(naive_results, list):
                        for r in naive_results[:5]:  # 最多取前 5
                            all_parts.append(
                                f"[来源{idx} - 向量检索] {r.get('chapter', '')} {r.get('section', '')}\n"
                                f"{r.get('content', '')}"
                            )
                            idx += 1

                    # 图谱检索结果（文本块部分）
                    if isinstance(local_result, dict):
                        for chunk in local_result.get("chunks", [])[:3]:
                            all_parts.append(
                                f"[来源{idx} - 图谱检索] {chunk.get('chapter', '')} {chunk.get('section', '')}\n"
                                f"{chunk.get('content', '')}"
                            )
                            idx += 1
                        # 社区摘要
                        for comm in local_result.get("communities", [])[:2]:
                            summary = comm.get("summary", "")
                            if summary:
                                all_parts.append(f"[来源{idx} - 社区摘要]\n{summary}")
                                idx += 1

                    # 全局检索（仅在其他检索结果不足时使用）
                    if len(all_parts) < 3:
                        try:
                            global_result = self.global_search.search(query, level=1)
                            if global_result and "暂无社区数据" not in global_result:
                                all_parts.append(f"[来源{idx} - 全局检索]\n{global_result[:800]}")
                        except Exception:
                            pass

                    if not all_parts:
                        return "未检索到相关临床资料。"

                    return "\n\n---\n\n".join(all_parts)

            return run_async(_async())

        return [
            Tool(
                name="fusion_retriever",
                func=fusion_search_fn,
                description=(
                    "融合检索：汇聚向量检索、知识图谱和全局社区检索的结果。"
                    "适合复杂临床问题，需要多维度信息支撑的场景。"
                    "输入：临床问题。"
                ),
            )
        ]

    # ──────────────────────────────────────────────
    # 图谱边
    # ──────────────────────────────────────────────

    def _add_retrieval_edges(self, workflow) -> None:
        workflow.add_edge("retrieve", "generate")

    # ──────────────────────────────────────────────
    # 关键词提取
    # ──────────────────────────────────────────────

    def _extract_keywords(self, query: str) -> Dict[str, List[str]]:
        return {"low_level": [], "high_level": []}

    # ──────────────────────────────────────────────
    # Generate 节点（含重排序）
    # ──────────────────────────────────────────────

    def _generate_node(self, state) -> Dict:
        messages = state["messages"]
        try:
            question = messages[0].content if messages else "未知问题"
            all_results = messages[-1].content if len(messages) > 1 else ""
        except Exception:
            question, all_results = "未知问题", ""

        # 第一步：LLM 重排序
        reranked_context = self._rerank(question, all_results)

        # 第二步：生成最终回答
        prompt = ChatPromptTemplate.from_messages([
            ("system", LOCAL_SEARCH_SYSTEM_PROMPT),
            ("human", _FUSION_GENERATE_PROMPT),
        ])
        chain = prompt | self.llm | StrOutputParser()
        try:
            response = chain.invoke({
                "context": reranked_context,
                "question": question,
                "response_type": response_type,
            })
            self._log_execution("generate", question, response[:200])
            return {"messages": [AIMessage(content=response)]}
        except Exception as e:
            return {"messages": [AIMessage(content=f"生成回答时出错：{str(e)}")]}

    def _rerank(self, question: str, all_results: str) -> str:
        """使用 LLM 对多源检索结果重排序"""
        if not all_results or len(all_results) < 100:
            return all_results

        rerank_prompt = ChatPromptTemplate.from_messages([
            ("system", "你是一名临床信息筛选专家，专注于筛选最相关的医学信息。"),
            ("human", _RERANK_PROMPT),
        ])
        chain = rerank_prompt | self.llm | StrOutputParser()
        try:
            return chain.invoke({
                "question": question,
                "all_results": all_results[:3000],  # 限制输入长度
            })
        except Exception as e:
            print(f"[FusionAgent] 重排序失败，使用原始结果: {e}")
            return all_results
