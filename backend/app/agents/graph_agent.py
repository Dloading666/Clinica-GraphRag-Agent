"""Graph RAG Agent - 使用本地图谱搜索（向量 + 知识图谱）"""
import json
import re
from typing import Dict, List

from langchain.prompts import ChatPromptTemplate
from langchain.tools import Tool
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import END

from app.agents.base import BaseAgent, run_async
from app.config.database import AsyncSessionLocal
from app.config.prompts.clinical_prompts import (
    GRAPH_GENERATE_PROMPT,
    GRAPH_KEYWORD_PROMPT,
    GRAPH_REDUCE_PROMPT,
    LOCAL_SEARCH_SYSTEM_PROMPT,
    REDUCE_SYSTEM_PROMPT,
    response_type,
)
from app.search.global_search import GlobalSearch
from app.search.local_search import LocalSearch


class GraphAgent(BaseAgent):
    """使用知识图谱本地/全局搜索的临床问答 Agent"""

    def __init__(self):
        self.local_search = LocalSearch()
        self.global_search = GlobalSearch()
        super().__init__()

    # ──────────────────────────────────────────────
    # Tool 配置
    # ──────────────────────────────────────────────

    def _setup_tools(self) -> List:
        def local_search_fn(query: str) -> str:
            """Search clinical knowledge graph for specific entities and relationships"""
            async def _async():
                async with AsyncSessionLocal() as db:
                    result = await self.local_search.search(query, db)
                    return self.local_search.format_context(result)

            return run_async(_async())

        def global_search_fn(query: str) -> str:
            """Search entire clinical knowledge base using community-level analysis"""
            return self.global_search.search(query, level=1)

        return [
            Tool(
                name="local_retriever",
                func=local_search_fn,
                description=(
                    "搜索临床知识图谱，适合查询特定疾病、药物、症状及其关系。"
                    "输入：具体的临床实体名称或问题。"
                ),
            ),
            Tool(
                name="global_retriever",
                func=global_search_fn,
                description=(
                    "全局搜索整个临床知识库，适合宏观性、综合性临床问题。"
                    "输入：广泛的临床问题或诊疗策略查询。"
                ),
            ),
        ]

    # ──────────────────────────────────────────────
    # 图谱边（含 reduce 节点）
    # ──────────────────────────────────────────────

    def _add_retrieval_edges(self, workflow) -> None:
        workflow.add_node("reduce", self._reduce_node)
        workflow.add_conditional_edges(
            "retrieve",
            self._grade_documents,
            {"generate": "generate", "reduce": "reduce"},
        )
        workflow.add_edge("reduce", END)

    def _grade_documents(self, state) -> str:
        """判断使用 generate 还是 reduce 节点"""
        messages = state["messages"]
        # 找到最近的 AI 消息，检查是否调用了 global_retriever
        for msg in reversed(messages):
            tool_calls = getattr(msg, "additional_kwargs", {}).get("tool_calls", [])
            if tool_calls:
                tool_name = tool_calls[0].get("function", {}).get("name", "")
                if tool_name == "global_retriever":
                    return "reduce"
                break
        return "generate"

    # ──────────────────────────────────────────────
    # 关键词提取
    # ──────────────────────────────────────────────

    def _extract_keywords(self, query: str) -> Dict[str, List[str]]:
        try:
            result = self.llm.invoke(GRAPH_KEYWORD_PROMPT.format(query=query))
            content = result.content if hasattr(result, "content") else str(result)
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception:
            pass
        return {"low_level": [], "high_level": []}

    # ──────────────────────────────────────────────
    # Generate 节点（本地搜索）
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
            ("human", GRAPH_GENERATE_PROMPT),
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

    # ──────────────────────────────────────────────
    # Reduce 节点（全局搜索）
    # ──────────────────────────────────────────────

    def _reduce_node(self, state) -> Dict:
        messages = state["messages"]
        try:
            question = messages[0].content if messages else "未知问题"
            docs = messages[-1].content if len(messages) > 1 else ""
        except Exception:
            question, docs = "未知问题", ""

        prompt = ChatPromptTemplate.from_messages([
            ("system", REDUCE_SYSTEM_PROMPT),
            ("human", GRAPH_REDUCE_PROMPT),
        ])
        chain = prompt | self.llm | StrOutputParser()
        try:
            response = chain.invoke({
                "report_data": docs,
                "question": question,
                "response_type": response_type,
            })
            self._log_execution("reduce", question, response[:200])
            return {"messages": [AIMessage(content=response)]}
        except Exception as e:
            return {"messages": [AIMessage(content=f"生成回答时出错：{str(e)}")]}
