"""Fusion RAG agent."""

import asyncio
from typing import Dict, List

from langchain.prompts import ChatPromptTemplate
from langchain.tools import Tool
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser

from app.agents.base import BaseAgent, run_async
from app.config.database import AsyncSessionLocal
from app.config.prompts.clinical_prompts import (
    LOCAL_SEARCH_SYSTEM_PROMPT,
    response_type,
)
from app.search.global_search import GlobalSearch
from app.search.local_search import LocalSearch
from app.search.naive_search import NaiveSearch


_RERANK_PROMPT = """你是一名临床信息筛选专家。请从以下多个来源的检索结果中，选出与临床问题最相关的信息片段。
## 临床问题
{question}

## 检索结果（多个来源）
{all_results}

## 任务
1. 评估每个结果与问题的相关性（高/中/低）
2. 选出最相关的内容（不超过 5 个片段）
3. 按相关性从高到低排序
4. 直接输出筛选后的原始内容，用 "---" 分隔"""

_FUSION_GENERATE_PROMPT = """## 精选检索结果
{context}

## 临床问题
{question}

## 要求
请基于上面的精选结果，提供{response_type}。
- 整合多个来源的信息
- 保持逻辑一致
- 用 [n] 标注参考来源"""


class FusionAgent(BaseAgent):
    """Agent that aggregates, reranks, and synthesizes multiple retrieval sources."""

    def __init__(self):
        self.naive_search = NaiveSearch()
        self.local_search = LocalSearch()
        self.global_search = GlobalSearch()
        super().__init__()

    def _setup_tools(self) -> List:
        async def fusion_search_async(query: str) -> str:
            async with AsyncSessionLocal() as db:
                naive_task = self.naive_search.search(query, db)
                local_task = self.local_search.search(query, db)
                naive_results, local_result = await asyncio.gather(
                    naive_task, local_task, return_exceptions=True
                )

                all_parts = []
                idx = 1

                if isinstance(naive_results, list):
                    for result in naive_results[:5]:
                        all_parts.append(
                            f"[来源{idx} - 向量检索] "
                            f"{result.get('chapter', '')} {result.get('section', '')}\n"
                            f"{result.get('content', '')}"
                        )
                        idx += 1

                if isinstance(local_result, dict):
                    for chunk in local_result.get("chunks", [])[:3]:
                        all_parts.append(
                            f"[来源{idx} - 图谱检索] "
                            f"{chunk.get('chapter', '')} {chunk.get('section', '')}\n"
                            f"{chunk.get('content', '')}"
                        )
                        idx += 1

                    for community in local_result.get("communities", [])[:2]:
                        summary = community.get("summary", "")
                        if summary:
                            all_parts.append(f"[来源{idx} - 社区摘要]\n{summary}")
                            idx += 1

                if len(all_parts) < 3:
                    try:
                        global_result = self.global_search.search(query, level=1)
                        if (
                            global_result
                            and "暂无社区数据" not in global_result
                            and "未找到" not in global_result
                        ):
                            all_parts.append(
                                f"[来源{idx} - 全局检索]\n{global_result[:800]}"
                            )
                    except Exception:
                        pass

                return "\n\n---\n\n".join(all_parts) if all_parts else "未检索到相关临床资料。"

        def fusion_search_fn(query: str) -> str:
            """Aggregate vector, graph, and global search results."""

            return run_async(fusion_search_async(query))

        return [
            Tool.from_function(
                func=fusion_search_fn,
                coroutine=fusion_search_async,
                name="fusion_retriever",
                description=(
                    "Aggregate vector retrieval, graph retrieval, and global search "
                    "for complex questions that need multi-source evidence."
                ),
            )
        ]

    def _add_retrieval_edges(self, workflow) -> None:
        workflow.add_edge("retrieve", "generate")

    def _extract_keywords(self, query: str) -> Dict[str, List[str]]:
        return {"low_level": [], "high_level": []}

    def _build_payload(self, messages) -> Dict[str, str]:
        try:
            question = self._get_latest_user_message(messages) or "Unknown question"
            all_results = (
                self._normalize_retrieval_context(messages[-1].content)
                if len(messages) > 1
                else ""
            )
        except Exception:
            question = "Unknown question"
            all_results = ""
        return {"question": question, "all_results": all_results}

    def _rerank(self, question: str, all_results: str) -> str:
        if not all_results or len(all_results) < 100:
            return all_results

        rerank_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "你是一名临床信息筛选专家，专注于筛选最相关的医学信息。"),
                ("human", _RERANK_PROMPT),
            ]
        )
        chain = rerank_prompt | self.llm | StrOutputParser()
        try:
            return chain.invoke(
                {
                    "question": question,
                    "all_results": all_results[:3000],
                }
            )
        except Exception:
            return all_results

    def _generate_node(self, state) -> Dict:
        payload = self._build_payload(state["messages"])
        reranked_context = self._rerank(payload["question"], payload["all_results"])

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", LOCAL_SEARCH_SYSTEM_PROMPT),
                ("human", _FUSION_GENERATE_PROMPT),
            ]
        )
        chain = prompt | self.llm | StrOutputParser()
        try:
            response = chain.invoke(
                {
                    "context": reranked_context,
                    "question": payload["question"],
                    "response_type": response_type,
                }
            )
            self._log_execution("generate", payload["question"], response[:200])
            return {"messages": [AIMessage(content=response)]}
        except Exception as exc:
            return {"messages": [AIMessage(content=f"Answer generation failed: {exc}")]}

    async def _stream_response(self, state) -> Dict:
        payload = self._build_payload(state["messages"])
        reranked_context = await asyncio.to_thread(
            self._rerank,
            payload["question"],
            payload["all_results"],
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", LOCAL_SEARCH_SYSTEM_PROMPT),
                ("human", _FUSION_GENERATE_PROMPT),
            ]
        )
        async for chunk in self._stream_prompt_response(
            prompt,
            {
                "context": reranked_context,
                "question": payload["question"],
                "response_type": response_type,
            },
            node_name="generate",
            log_input=payload["question"],
        ):
            yield chunk
