"""Graph RAG agent."""

import asyncio
import json
import re
from typing import Any, Dict, List

from langchain.prompts import ChatPromptTemplate
from langchain.tools import Tool
from langchain_core.messages import AIMessage, BaseMessage
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
from app.models.llm_factory import content_to_text
from app.search.global_search import GlobalSearch
from app.search.local_search import LocalSearch
from app.search.query_expansion import has_visible_evidence


class GraphAgent(BaseAgent):
    """Agent that routes between local KG retrieval and global summaries."""

    def __init__(self):
        self.local_search = LocalSearch()
        self.global_search = GlobalSearch()
        super().__init__()
        self.require_knowledge_evidence = True

    def _setup_tools(self) -> List:
        async def local_search_async(query: str) -> str:
            async with AsyncSessionLocal() as db:
                result = await self.local_search.search(query, db)
                self._set_retrieval_metadata(
                    stats=result.get("stats"),
                    source_items=result.get("sources"),
                )
                return self.local_search.format_context(result)

        def local_search_fn(query: str) -> str:
            """Search the clinical knowledge graph for entity-level evidence."""

            return run_async(local_search_async(query))

        def global_search_fn(query: str) -> str:
            """Search the whole knowledge base using community summaries."""

            payload = self.global_search.search_with_metadata(query, level=1)
            self._set_retrieval_metadata(
                stats=payload.get("stats"),
                source_items=payload.get("sources"),
            )
            return payload.get("context", "")

        return [
            Tool.from_function(
                func=local_search_fn,
                coroutine=local_search_async,
                name="local_retriever",
                description=(
                    "Search the clinical knowledge graph for specific diseases, drugs, "
                    "symptoms, and relationships."
                ),
            ),
            Tool(
                name="global_retriever",
                func=global_search_fn,
                description=(
                    "Search community-level summaries for broad or synthesis-heavy "
                    "clinical questions."
                ),
            ),
        ]

    def _add_retrieval_edges(self, workflow) -> None:
        workflow.add_node("reduce", self._reduce_node)
        workflow.add_conditional_edges(
            "retrieve",
            self._grade_documents,
            {"generate": "generate", "reduce": "reduce"},
        )
        workflow.add_edge("reduce", END)

    def _grade_documents(self, state) -> str:
        messages = state["messages"]
        for msg in reversed(messages):
            tool_calls = getattr(msg, "tool_calls", None) or getattr(
                msg, "additional_kwargs", {}
            ).get("tool_calls", [])
            if not tool_calls:
                continue

            first_tool_call = tool_calls[0]
            if isinstance(first_tool_call, dict):
                tool_name = (
                    first_tool_call.get("name")
                    or first_tool_call.get("function", {}).get("name", "")
                )
            else:
                tool_name = getattr(first_tool_call, "name", "")

            if tool_name == "global_retriever":
                return "reduce"
            break

        return "generate"

    def _extract_keywords(self, query: str) -> Dict[str, List[str]]:
        try:
            result = self.llm.invoke(GRAPH_KEYWORD_PROMPT.format(query=query))
            content = (
                content_to_text(result.content)
                if hasattr(result, "content")
                else str(result)
            )
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception:
            pass
        return {"low_level": [], "high_level": []}

    def _build_question_and_docs(self, messages) -> Dict[str, str]:
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
        return {"question": question, "docs": docs}

    def _generate_node(self, state) -> Dict:
        payload = self._build_question_and_docs(state["messages"])
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", LOCAL_SEARCH_SYSTEM_PROMPT),
                ("human", GRAPH_GENERATE_PROMPT),
            ]
        )
        chain = prompt | self.llm | StrOutputParser()
        try:
            response = chain.invoke(
                {
                    "context": payload["docs"],
                    "question": payload["question"],
                    "response_type": response_type,
                }
            )
            self._log_execution("generate", payload["question"], response[:200])
            return {"messages": [AIMessage(content=response)]}
        except Exception as exc:
            return {"messages": [AIMessage(content=f"Answer generation failed: {exc}")]}

    async def _handle_missing_tool_calls(
        self,
        query: str,
        messages: List[BaseMessage],
        response: BaseMessage | None = None,
    ) -> Dict[str, Any] | None:
        if not self.require_knowledge_evidence:
            return None

        del response
        async with AsyncSessionLocal() as db:
            local_result = await self.local_search.search(query, db)

        local_stats = local_result.get("stats")
        local_sources = local_result.get("sources")
        local_context = self.local_search.format_context(local_result)
        self._set_retrieval_metadata(stats=local_stats, source_items=local_sources)

        if has_visible_evidence(local_stats):
            self._log_execution("agent", query, "forced_retrieval:local_retriever")
            self._log_execution("retrieve", query, content_to_text(local_context))
            messages.append(AIMessage(content=local_context))
            return {
                "messages": messages,
                "direct_answer": "",
                "forced_retrieval_tool": "local_retriever",
            }

        global_payload = await asyncio.to_thread(
            self.global_search.search_with_metadata,
            query,
            1,
        )
        global_stats = global_payload.get("stats")
        global_sources = global_payload.get("sources")
        self._set_retrieval_metadata(
            stats=global_stats,
            source_items=global_sources,
        )
        global_context = global_payload.get("context", "")
        if has_visible_evidence(global_stats):
            self._log_execution("agent", query, "forced_retrieval:global_retriever")
            self._log_execution("retrieve", query, content_to_text(global_context))
            messages.append(AIMessage(content=global_context))
            return {
                "messages": messages,
                "direct_answer": "",
                "forced_retrieval_tool": "global_retriever",
            }

        return await self._attempt_web_search_fallback(query, messages)

    def _reduce_node(self, state) -> Dict:
        payload = self._build_question_and_docs(state["messages"])
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", REDUCE_SYSTEM_PROMPT),
                ("human", GRAPH_REDUCE_PROMPT),
            ]
        )
        chain = prompt | self.llm | StrOutputParser()
        try:
            response = chain.invoke(
                {
                    "report_data": payload["docs"],
                    "question": payload["question"],
                    "response_type": response_type,
                }
            )
            self._log_execution("reduce", payload["question"], response[:200])
            return {"messages": [AIMessage(content=response)]}
        except Exception as exc:
            return {"messages": [AIMessage(content=f"Answer generation failed: {exc}")]}

    async def _stream_response(self, state) -> Dict:
        payload = self._build_question_and_docs(state["messages"])
        forced_tool_name = state.get("forced_retrieval_tool")
        route = "reduce" if forced_tool_name == "global_retriever" else self._grade_documents(state)

        if route == "reduce":
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", REDUCE_SYSTEM_PROMPT),
                    ("human", GRAPH_REDUCE_PROMPT),
                ]
            )
            async for chunk in self._stream_prompt_response(
                prompt,
                {
                    "report_data": payload["docs"],
                    "question": payload["question"],
                    "response_type": response_type,
                },
                node_name="reduce",
                log_input=payload["question"],
            ):
                yield chunk
            return

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", LOCAL_SEARCH_SYSTEM_PROMPT),
                ("human", GRAPH_GENERATE_PROMPT),
            ]
        )
        async for chunk in self._stream_prompt_response(
            prompt,
            {
                "context": payload["docs"],
                "question": payload["question"],
                "response_type": response_type,
            },
            node_name="generate",
            log_input=payload["question"],
        ):
            yield chunk
