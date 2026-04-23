"""Hybrid RAG agent."""

import asyncio
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
from app.config.settings import settings
from app.search.local_search import LocalSearch
from app.search.naive_search import NaiveSearch
from app.search.query_expansion import (
    build_query_expansion_plan,
    dedupe_source_items,
    merge_retrieval_stats,
)


class HybridAgent(BaseAgent):
    """Agent that blends vector retrieval and graph retrieval."""

    def __init__(self):
        self.naive_search = NaiveSearch()
        self.local_search = LocalSearch()
        super().__init__()
        self.require_knowledge_evidence = True

    def _setup_tools(self) -> List:
        async def hybrid_search_async(query: str) -> str:
            async with AsyncSessionLocal() as db:
                query_plan = build_query_expansion_plan(
                    query,
                    enabled=(
                        settings.search.query_expansion_enabled
                        and settings.search.query_expansion_mode == "synonym"
                        and "hybrid"
                        in {
                            item.strip().lower()
                            for item in settings.search.query_expansion_apply_to.split(",")
                            if item.strip()
                        }
                    ),
                    max_terms=settings.search.query_expansion_max_terms,
                )
                naive_task = self.naive_search.search_with_metadata(
                    query,
                    db,
                    query_plan=query_plan,
                )
                local_task = self.local_search.search(
                    query,
                    db,
                    query_plan=query_plan,
                )
                naive_payload, local_result = await asyncio.gather(
                    naive_task, local_task, return_exceptions=True
                )

                parts = []
                merged_sources = []
                merged_stats = merge_retrieval_stats()

                if isinstance(naive_payload, dict):
                    naive_results = naive_payload.get("items", [])
                    merged_stats = merge_retrieval_stats(
                        merged_stats,
                        naive_payload.get("stats", {}),
                    )
                    merged_sources.extend(naive_payload.get("sources", []))
                    if naive_results:
                        parts.append("## Vector Retrieval")
                        parts.append(self.naive_search.format_context(naive_results))

                if isinstance(local_result, dict):
                    merged_stats = merge_retrieval_stats(
                        merged_stats,
                        local_result.get("stats", {}),
                    )
                    merged_sources.extend(local_result.get("sources", []))
                    graph_ctx = self.local_search.format_context(local_result)
                    if graph_ctx and "未检索到" not in graph_ctx:
                        parts.append("## Graph Retrieval")
                        parts.append(graph_ctx)

                self._set_retrieval_metadata(
                    stats=merged_stats,
                    source_items=dedupe_source_items(merged_sources),
                )
                return "\n\n".join(parts) if parts else "未检索到相关临床资料。"

        def hybrid_search_fn(query: str) -> str:
            """Combine vector similarity and graph retrieval in one context."""

            return run_async(hybrid_search_async(query))

        return [
            Tool.from_function(
                func=hybrid_search_fn,
                coroutine=hybrid_search_async,
                name="hybrid_retriever",
                description=(
                    "Combine vector retrieval and graph retrieval for questions that "
                    "need both document evidence and entity relationships."
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
            docs = (
                self._normalize_retrieval_context(messages[-1].content)
                if len(messages) > 1
                else ""
            )
        except Exception:
            question = "Unknown question"
            docs = ""
        return {"question": question, "context": docs}

    def _generate_node(self, state) -> Dict:
        payload = self._build_payload(state["messages"])
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", LOCAL_SEARCH_SYSTEM_PROMPT),
                ("human", LOCAL_SEARCH_CONTEXT_PROMPT),
            ]
        )
        chain = prompt | self.llm | StrOutputParser()
        try:
            response = chain.invoke(
                {
                    "context": payload["context"],
                    "input": payload["question"],
                    "response_type": response_type,
                }
            )
            self._log_execution("generate", payload["question"], response[:200])
            return {"messages": [AIMessage(content=response)]}
        except Exception as exc:
            return {"messages": [AIMessage(content=f"Answer generation failed: {exc}")]}

    async def _stream_response(self, state) -> Dict:
        payload = self._build_payload(state["messages"])
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", LOCAL_SEARCH_SYSTEM_PROMPT),
                ("human", LOCAL_SEARCH_CONTEXT_PROMPT),
            ]
        )
        async for chunk in self._stream_prompt_response(
            prompt,
            {
                "context": payload["context"],
                "input": payload["question"],
                "response_type": response_type,
            },
            node_name="generate",
            log_input=payload["question"],
        ):
            yield chunk
