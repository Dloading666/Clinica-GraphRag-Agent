"""Naive RAG Agent - 纯向量相似度检索"""
from typing import Dict, List

from langchain.prompts import ChatPromptTemplate
from langchain.tools import Tool
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser

from app.agents.base import BaseAgent, run_async
from app.config.database import AsyncSessionLocal
from app.config.prompts.clinical_prompts import (
    NAIVE_RAG_HUMAN_PROMPT,
    NAIVE_RAG_SYSTEM_PROMPT,
    response_type,
)
from app.search.naive_search import NaiveSearch


class NaiveRagAgent(BaseAgent):
    """使用纯向量相似度检索的临床问答 Agent"""

    def __init__(self):
        self.naive_search = NaiveSearch()
        super().__init__()

    # ──────────────────────────────────────────────
    # Tool 配置
    # ──────────────────────────────────────────────

    def _setup_tools(self) -> List:
        def search_fn(query: str) -> str:
            """Search clinical knowledge base for relevant information"""
            async def _async_search():
                async with AsyncSessionLocal() as db:
                    results = await self.naive_search.search(query, db)
                    return self.naive_search.format_context(results)

            return run_async(_async_search())

        return [
            Tool(
                name="naive_search",
                func=search_fn,
                description=(
                    "使用向量相似度搜索临床知识库。"
                    "输入：临床问题或关键词。"
                    "输出：相关临床文献片段。"
                ),
            )
        ]

    # ──────────────────────────────────────────────
    # 图谱边
    # ──────────────────────────────────────────────

    def _add_retrieval_edges(self, workflow) -> None:
        workflow.add_edge("retrieve", "generate")

    # ──────────────────────────────────────────────
    # 关键词提取（Naive RAG 不使用图谱，返回空）
    # ──────────────────────────────────────────────

    def _extract_keywords(self, query: str) -> Dict[str, List[str]]:
        return {"low_level": [], "high_level": []}

    # ──────────────────────────────────────────────
    # Generate 节点
    # ──────────────────────────────────────────────

    def _generate_node(self, state) -> Dict:
        messages = state["messages"]
        try:
            # messages 结构：[HumanMessage, AIMessage(tool_call), ToolMessage(docs), ...]
            # 问题在第一条，检索结果在最后一条
            question = messages[0].content if messages else "未知问题"
            docs = messages[-1].content if len(messages) > 1 else ""
        except Exception:
            question = "未知问题"
            docs = ""

        prompt = ChatPromptTemplate.from_messages([
            ("system", NAIVE_RAG_SYSTEM_PROMPT),
            ("human", NAIVE_RAG_HUMAN_PROMPT),
        ])
        chain = prompt | self.llm | StrOutputParser()
        try:
            response = chain.invoke({
                "context": docs,
                "question": question,
                "response_type": response_type,
            })
            self._log_execution("generate", question, response[:200])
            return {"messages": [AIMessage(content=response)]}
        except Exception as e:
            return {"messages": [AIMessage(content=f"生成回答时出错：{str(e)}")]}
