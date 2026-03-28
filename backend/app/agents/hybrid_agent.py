"""Hybrid RAG Agent - 融合向量检索 + 知识图谱检索"""
from typing import Dict, List

from langchain.prompts import ChatPromptTemplate
from langchain.tools import Tool
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser

from app.agents.base import BaseAgent, run_async
from app.config.database import AsyncSessionLocal
from app.config.prompts.clinical_prompts import (
    LOCAL_SEARCH_CONTEXT_PROMPT,
    LOCAL_SEARCH_SYSTEM_PROMPT,
    response_type,
)
from app.search.local_search import LocalSearch
from app.search.naive_search import NaiveSearch


class HybridAgent(BaseAgent):
    """混合检索 Agent：同时使用向量检索和知识图谱检索，融合两者结果"""

    def __init__(self):
        self.naive_search = NaiveSearch()
        self.local_search = LocalSearch()
        super().__init__()

    # ──────────────────────────────────────────────
    # Tool 配置
    # ──────────────────────────────────────────────

    def _setup_tools(self) -> List:
        def hybrid_search_fn(query: str) -> str:
            """Hybrid search: combines vector similarity and knowledge graph retrieval"""
            async def _async():
                async with AsyncSessionLocal() as db:
                    # 并发执行两种检索
                    import asyncio
                    naive_task = self.naive_search.search(query, db)
                    local_task = self.local_search.search(query, db)
                    naive_results, local_result = await asyncio.gather(
                        naive_task, local_task, return_exceptions=True
                    )

                    parts = []

                    # 向量检索结果
                    if isinstance(naive_results, list) and naive_results:
                        parts.append("## 向量检索结果")
                        parts.append(self.naive_search.format_context(naive_results))

                    # 图谱检索结果
                    if isinstance(local_result, dict):
                        graph_ctx = self.local_search.format_context(local_result)
                        if graph_ctx and "未检索到" not in graph_ctx:
                            parts.append("## 知识图谱检索结果")
                            parts.append(graph_ctx)

                    if parts:
                        return "\n\n".join(parts)
                    return "未检索到相关临床资料。"

            return run_async(_async())

        return [
            Tool(
                name="hybrid_retriever",
                func=hybrid_search_fn,
                description=(
                    "混合检索：同时使用向量相似度和知识图谱搜索临床知识库。"
                    "适合需要精确文献匹配和实体关系分析的综合临床问题。"
                    "输入：临床问题或关键词。"
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
    # Generate 节点
    # ──────────────────────────────────────────────

    def _generate_node(self, state) -> Dict:
        messages = state["messages"]
        try:
            question = messages[0].content if messages else "未知问题"
            docs = messages[-1].content if len(messages) > 1 else ""
        except Exception:
            question, docs = "未知问题", ""

        prompt = ChatPromptTemplate.from_messages([
            ("system", LOCAL_SEARCH_SYSTEM_PROMPT),
            ("human", LOCAL_SEARCH_CONTEXT_PROMPT),
        ])
        chain = prompt | self.llm | StrOutputParser()
        try:
            response = chain.invoke({
                "context": docs,
                "input": question,
                "response_type": response_type,
            })
            self._log_execution("generate", question, response[:200])
            return {"messages": [AIMessage(content=response)]}
        except Exception as e:
            return {"messages": [AIMessage(content=f"生成回答时出错：{str(e)}")]}
