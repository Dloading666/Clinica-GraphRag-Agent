"""Naive RAG agent."""

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
    """RAG agent backed by direct vector retrieval."""

    def __init__(self):
        self.naive_search = NaiveSearch()
        super().__init__()
        self.require_knowledge_evidence = True

    def _setup_tools(self) -> List:
        async def search_fn_async(query: str) -> str:
            async with AsyncSessionLocal() as db:
                payload = await self.naive_search.search_with_metadata(query, db)
                self._set_retrieval_metadata(
                    stats=payload.get("stats"),
                    source_items=payload.get("sources"),
                )
                return self.naive_search.format_context(payload.get("items", []))

        def search_fn(query: str) -> str:
            """Search the clinical knowledge base for relevant information."""

            return run_async(search_fn_async(query))

        return [
            Tool.from_function(
                func=search_fn,
                coroutine=search_fn_async,
                name="naive_search",
                description=(
                    "Use vector similarity to search the clinical knowledge base. "
                    "Input should be a clinical question or a focused medical topic."
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
                ("system", NAIVE_RAG_SYSTEM_PROMPT),
                ("human", NAIVE_RAG_HUMAN_PROMPT),
            ]
        )
        chain = prompt | self.llm | StrOutputParser()
        try:
            response = chain.invoke(
                {
                    "context": payload["context"],
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
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", NAIVE_RAG_SYSTEM_PROMPT),
                ("human", NAIVE_RAG_HUMAN_PROMPT),
            ]
        )
        async for chunk in self._stream_prompt_response(
            prompt,
            {
                "context": payload["context"],
                "question": payload["question"],
                "response_type": response_type,
            },
            node_name="generate",
            log_input=payload["question"],
        ):
            yield chunk
