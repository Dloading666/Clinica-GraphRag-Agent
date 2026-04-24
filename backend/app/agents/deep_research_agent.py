"""Deep Research Agent - true per-node streaming with astream_events."""

import asyncio
import re
import json
import time
from typing import Annotated, Any, AsyncGenerator, Dict, List, Optional, Sequence, TypedDict

from langchain.prompts import ChatPromptTemplate
from langchain.tools import Tool
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agents.base import BaseAgent, run_async, ThinkingEvent
from app.config.database import AsyncSessionLocal
from app.config.settings import settings
from app.config.prompts.clinical_prompts import (
    LOCAL_SEARCH_SYSTEM_PROMPT,
    response_type,
)
from app.models.llm_factory import get_embeddings, get_llm
from app.search.global_search import GlobalSearch
from app.search.local_search import LocalSearch
from app.search.naive_search import NaiveSearch
from app.search.web_search import WebSearch
from app.search.query_expansion import (
    dedupe_source_items,
    empty_retrieval_stats,
    merge_retrieval_stats,
    summarize_retrieval_stats,
)


# ──────────────────────────────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────────────────────────────

_DECOMPOSE_PROMPT = """你是一名临床研究专家。请将以下复杂临床问题分解为 2-4 个具体的子问题，以便逐步检索和分析。

## 复杂临床问题
{question}

## 已有证据摘要（若有）
{evidence_summary}

## 任务
请输出 JSON 格式的子问题列表：
{{"sub_questions": ["子问题1", "子问题2", "子问题3"]}}

注意：
- 子问题应具体、可检索
- 子问题应覆盖原问题的不同方面
- 避免重复已有证据中已回答的内容

请直接输出 JSON："""

_EVALUATE_PROMPT = """你是一名临床研究质量评估专家。请评估当前收集的证据是否足以回答原始问题。

## 原始临床问题
{question}

## 已收集的证据
{evidence}

## 评估标准
- 证据是否覆盖了问题的核心方面？
- 是否有明显的信息缺口？
- 证据质量是否满足临床决策需要？

## 输出要求
返回 JSON：{{"sufficient": true/false, "missing_aspects": ["缺失方面1", "缺失方面2"], "confidence": 0.0-1.0}}

请直接输出 JSON："""

_SYNTHESIZE_PROMPT = """## 原始临床问题
{question}

## 多轮深度研究收集的证据
{evidence}

## 子问题与回答摘要
{sub_answers}

## 要求
请综合以上多轮研究证据，提供{response_type}。
- 按逻辑顺序组织回答
- 对各来源信息进行批判性整合
- 指出证据的强度和局限性
- 提供可操作的临床建议"""


# ──────────────────────────────────────────────────────────────────
_NO_EVIDENCE_ANSWER = (
    "\u5f53\u524d\u672a\u4ece\u77e5\u8bc6\u5e93\u68c0\u7d22\u5230\u53ef\u5c55\u793a\u8bc1\u636e\uff0c"
    "\u672c\u8f6e\u4e0d\u8f93\u51fa\u4f2a\u88c5\u6210\u77e5\u8bc6\u5e93\u652f\u6491\u7684 RAG \u6b63\u5f0f\u56de\u7b54\u3002\n\n"
    "\u5efa\u8bae\u6362\u4e00\u79cd\u95ee\u6cd5\u3001\u7f29\u5c0f\u95ee\u9898\u8303\u56f4\uff0c"
    "\u6216\u5148\u8865\u5145\u5bf9\u5e94\u7684\u77e5\u8bc6\u5e93\u8d44\u6599\u540e\u518d\u8bd5\u3002"
)


# State
# ──────────────────────────────────────────────────────────────────

class ResearchState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    question: str
    sub_questions: List[str]
    current_iteration: int
    max_iterations: int
    evidence: List[Dict]
    sub_answers: List[Dict]
    evidence_sufficient: bool
    final_answer: str


# ──────────────────────────────────────────────────────────────────
# Agent
# ──────────────────────────────────────────────────────────────────

class DeepResearchAgent:
    """
    Deep Research Agent: iterative multi-hop with true per-node streaming.

    ask_stream yields ThinkingEvent tuples as each graph node completes,
    enabling real-time UI updates without waiting for the full answer.
    """

    def __init__(self):
        self.llm = get_llm()
        self.stream_llm = get_llm(streaming=True)
        self.embeddings = get_embeddings()
        self.naive_search = NaiveSearch()
        self.local_search = LocalSearch()
        self.global_search = GlobalSearch()
        self.web_search = WebSearch()
        self.memory = MemorySaver()
        self.execution_log: List[Dict] = []
        self._latest_retrieval_stats: Dict[str, Any] = empty_retrieval_stats()
        self._latest_source_items: List[Dict[str, Any]] = []
        self._setup_chains()
        self._setup_graph()

    def _setup_chains(self) -> None:
        self._decompose_chain = (
            ChatPromptTemplate.from_messages([
                ("system", "你是一名擅长临床研究方法论的专家。"),
                ("human", _DECOMPOSE_PROMPT),
            ])
            | self.llm
            | StrOutputParser()
        )
        self._evaluate_chain = (
            ChatPromptTemplate.from_messages([
                ("system", "你是一名临床证据质量评估专家。"),
                ("human", _EVALUATE_PROMPT),
            ])
            | self.llm
            | StrOutputParser()
        )
        self._synthesize_chain = (
            ChatPromptTemplate.from_messages([
                ("system", LOCAL_SEARCH_SYSTEM_PROMPT),
                ("human", _SYNTHESIZE_PROMPT),
            ])
            | self.llm
            | StrOutputParser()
        )

    def _setup_graph(self) -> None:
        workflow = StateGraph(ResearchState)
        workflow.add_node("decompose", self._decompose_node)
        workflow.add_node("search", self._search_node)
        workflow.add_node("evaluate", self._evaluate_node)
        workflow.add_node("synthesize", self._synthesize_node)

        workflow.add_edge(START, "decompose")
        workflow.add_edge("decompose", "search")
        workflow.add_edge("search", "evaluate")
        workflow.add_conditional_edges(
            "evaluate",
            self._should_continue,
            {"continue": "decompose", "synthesize": "synthesize"},
        )
        workflow.add_edge("synthesize", END)

        self.graph = workflow.compile(checkpointer=self.memory)

    # ──────────────────────────────────────────────────────────────
    # Node implementations
    # ──────────────────────────────────────────────────────────────

    def _decompose_node(self, state: ResearchState) -> Dict:
        question = state["question"]
        iteration = state.get("current_iteration", 0)
        evidence = state.get("evidence", [])
        evidence_summary = ""
        if evidence:
            summaries = [e.get("summary", "")[:200] for e in evidence[-3:]]
            evidence_summary = "\n".join(summaries)

        self._log("decompose", f"第{iteration+1}轮，原问题: {question[:100]}", "")

        try:
            raw = self._decompose_chain.invoke({
                "question": question,
                "evidence_summary": evidence_summary,
            })
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                sub_questions = data.get("sub_questions", [])
            else:
                sub_questions = [question]
        except Exception as e:
            print(f"[DeepResearch] 问题分解失败: {e}")
            sub_questions = [question]

        self._log("decompose", "", f"子问题: {sub_questions}")
        return {"sub_questions": sub_questions[:4]}

    def _search_node(self, state: ResearchState) -> Dict:
        sub_questions = state.get("sub_questions", [])
        existing_evidence = list(state.get("evidence", []))
        sub_answers = list(state.get("sub_answers", []))

        for sub_q in sub_questions:
            self._log("search", sub_q, "")
            try:
                payload = run_async(self._search_for_question(sub_q))
                context = payload.get("context", "")
                evidence_total = int(
                    payload.get("stats", {}).get("evidence_total", 0) or 0
                )
                if evidence_total > 0 and context:
                    existing_evidence.append({
                        "question": sub_q,
                        "context": context,
                        "summary": context[:300],
                        "iteration": state.get("current_iteration", 0),
                        "stats": payload.get("stats", {}),
                        "sources": payload.get("sources", []),
                    })
                    sub_answers.append({"question": sub_q, "context": context[:500]})
                    self._latest_retrieval_stats = merge_retrieval_stats(
                        self._latest_retrieval_stats,
                        payload.get("stats", {}),
                    )
                    self._latest_source_items = dedupe_source_items(
                        [*self._latest_source_items, *payload.get("sources", [])]
                    )
                    self._log("search", sub_q, context[:200])
            except Exception as e:
                print(f"[DeepResearch] 子问题检索失败 ({sub_q}): {e}")

        return {"evidence": existing_evidence, "sub_answers": sub_answers}

    def _evaluate_node(self, state: ResearchState) -> Dict:
        question = state["question"]
        evidence = state.get("evidence", [])
        iteration = state.get("current_iteration", 0)

        if iteration >= state.get("max_iterations", 3) - 1:
            return {"evidence_sufficient": True, "current_iteration": iteration + 1}

        if not evidence:
            return {"evidence_sufficient": False, "current_iteration": iteration + 1}

        evidence_text = "\n\n---\n\n".join(
            [f"[子问题: {e['question']}]\n{e.get('summary', '')}" for e in evidence[-6:]]
        )

        try:
            raw = self._evaluate_chain.invoke({
                "question": question,
                "evidence": evidence_text[:2000],
            })
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                sufficient = data.get("sufficient", False)
                self._log("evaluate", f"迭代{iteration+1}", f"证据充分: {sufficient}")
                return {"evidence_sufficient": sufficient, "current_iteration": iteration + 1}
        except Exception as e:
            print(f"[DeepResearch] 证据评估失败: {e}")

        return {"evidence_sufficient": False, "current_iteration": iteration + 1}

    def _synthesize_node(self, state: ResearchState) -> Dict:
        question = state["question"]
        evidence = state.get("evidence", [])
        sub_answers = state.get("sub_answers", [])

        if not evidence:
            return {
                "final_answer": _NO_EVIDENCE_ANSWER,
                "messages": [AIMessage(content=_NO_EVIDENCE_ANSWER)],
            }

        evidence_text = "\n\n---\n\n".join(
            [f"[迭代{e['iteration']+1} | 子问题: {e['question']}]\n{e.get('context', '')[:600]}"
             for e in evidence]
        )
        sub_answers_text = "\n".join(
            [f"Q: {sa['question']}\nA: {sa.get('context', '')[:200]}"
             for sa in sub_answers]
        )

        self._log("synthesize", question[:100], "开始综合...")
        try:
            answer = self._synthesize_chain.invoke({
                "question": question,
                "evidence": evidence_text[:4000],
                "sub_answers": sub_answers_text[:2000],
                "response_type": response_type,
            })
            self._log("synthesize", "", answer[:200])
        except Exception as e:
            answer = f"综合分析时出错：{str(e)}\n\n已收集的证据摘要：\n{evidence_text[:1000]}"

        return {"final_answer": answer, "messages": [AIMessage(content=answer)]}

    def _should_continue(self, state: ResearchState) -> str:
        sufficient = state.get("evidence_sufficient", False)
        iteration = state.get("current_iteration", 0)
        max_iter = state.get("max_iterations", 3)
        if sufficient or iteration >= max_iter:
            return "synthesize"
        return "continue"

    async def _search_state_async(self, state: ResearchState) -> Dict[str, Any]:
        """Run sub-question retrieval directly on the active event loop."""
        sub_questions = state.get("sub_questions", [])
        existing_evidence = list(state.get("evidence", []))
        sub_answers = list(state.get("sub_answers", []))

        for sub_q in sub_questions:
            self._log("search", sub_q, "")
            try:
                payload = await self._search_for_question(sub_q)
                context = payload.get("context", "")
                stats = payload.get("stats", {})
                sources = payload.get("sources", [])
                evidence_total = int(stats.get("evidence_total", 0) or 0)

                if evidence_total > 0 and context:
                    existing_evidence.append(
                        {
                            "question": sub_q,
                            "context": context,
                            "summary": context[:300],
                            "iteration": state.get("current_iteration", 0),
                            "stats": stats,
                            "sources": sources,
                        }
                    )
                    sub_answers.append({"question": sub_q, "context": context[:500]})
                    self._latest_retrieval_stats = merge_retrieval_stats(
                        self._latest_retrieval_stats,
                        stats,
                    )
                    self._latest_source_items = dedupe_source_items(
                        [*self._latest_source_items, *sources]
                    )
                    self._log("search", sub_q, context[:200])
                else:
                    self._log("search", sub_q, "no_visible_evidence")
            except Exception as exc:
                print(f"[DeepResearch] sub-question retrieval failed ({sub_q}): {exc}")

        return {"evidence": existing_evidence, "sub_answers": sub_answers}

    async def _search_for_question(self, question: str) -> Dict[str, Any]:
        async with AsyncSessionLocal() as db:
            naive_task = self.naive_search.search_with_metadata(question, db, top_k=5)
            local_task = self.local_search.search(question, db)
            naive_payload, local_result = await asyncio.gather(
                naive_task,
                local_task,
                return_exceptions=True,
            )
            parts = []
            merged_stats = merge_retrieval_stats()
            merged_sources = []
            if isinstance(naive_payload, dict):
                naive_results = naive_payload.get("items", [])[:3]
                merged_stats = merge_retrieval_stats(
                    merged_stats,
                    naive_payload.get("stats", {}),
                )
                merged_sources.extend(naive_payload.get("sources", []))
                if naive_results:
                    parts.append(self.naive_search.format_context(naive_results))
            if isinstance(local_result, dict):
                local_stats = local_result.get("stats", {})
                merged_stats = merge_retrieval_stats(
                    merged_stats,
                    local_stats,
                )
                merged_sources.extend(local_result.get("sources", []))
                ctx = self.local_search.format_context(local_result)
                if int(local_stats.get("evidence_total", 0) or 0) > 0 and ctx:
                    parts.append(ctx)

            if int(merged_stats.get("evidence_total", 0) or 0) <= 0:
                try:
                    global_payload = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.global_search.search_with_metadata,
                            question,
                            1,
                        ),
                        timeout=12,
                    )
                except Exception:
                    global_payload = None

                if isinstance(global_payload, dict):
                    global_stats = global_payload.get("stats", {})
                    merged_stats = merge_retrieval_stats(
                        merged_stats,
                        global_stats,
                    )
                    merged_sources.extend(global_payload.get("sources", []))
                    ctx = str(global_payload.get("context", "")).strip()
                    if int(global_stats.get("evidence_total", 0) or 0) > 0 and ctx:
                        parts.append(ctx)

            if int(merged_stats.get("evidence_total", 0) or 0) <= 0 and settings.search.web_search_enabled:
                try:
                    web_payload = await self.web_search.search_with_metadata(question, max_results=4)
                except Exception:
                    web_payload = None

                if isinstance(web_payload, dict):
                    web_stats = web_payload.get("stats", {})
                    merged_stats = merge_retrieval_stats(
                        merged_stats,
                        web_stats,
                    )
                    merged_sources.extend(web_payload.get("sources", []))
                    ctx = str(web_payload.get("context", "")).strip()
                    if int(web_stats.get("evidence_total", 0) or 0) > 0 and ctx:
                        parts.append(ctx)
            return {
                "context": "\n\n".join(parts) if parts else "未检索到相关资料",
                "stats": merged_stats,
                "sources": dedupe_source_items(merged_sources),
            }

    def _log(self, node: str, input_data: Any, output_data: Any) -> None:
        self.execution_log.append({
            "node": node,
            "timestamp": time.time(),
            "input": str(input_data)[:200],
            "output": str(output_data)[:500],
        })

    # ──────────────────────────────────────────────────────────────
    # True streaming: astream_events per-node
    # ──────────────────────────────────────────────────────────────

    async def ask_stream(
        self, query: str, thread_id: str = "default"
    ) -> AsyncGenerator[tuple[str, Any], None]:
        """
        Stream each node's output as it completes using astream_events.

        Yields:
          - ("thinking", ThinkingEvent) per node completion
          - ("answer", str) chunk from synthesis streaming
          - ("error", str)
          - ("done", {})
        """
        self.execution_log = []
        config = {"configurable": {"thread_id": thread_id}}
        initial_state: ResearchState = {
            "messages": [HumanMessage(content=query)],
            "question": query,
            "sub_questions": [],
            "current_iteration": 0,
            "max_iterations": 3,
            "evidence": [],
            "sub_answers": [],
            "evidence_sufficient": False,
            "final_answer": "",
        }

        node_labels = {
            "decompose": "问题分解",
            "search": "知识检索",
            "evaluate": "证据评估",
            "synthesize": "综合生成",
        }

        try:
            async for event in self.graph.astream_events(initial_state, config=config, version="v2"):
                event_type = event.get("event")
                node_name = event.get("name", "")

                if event_type == "on_node_start":
                    yield (
                        "thinking",
                        ThinkingEvent(
                            node=node_name,
                            label=node_labels.get(node_name, node_name),
                            content=f"开始 {node_labels.get(node_name, node_name)}...",
                            done=False,
                        ),
                    )

                elif event_type == "on_node_end":
                    # Emit thinking with actual output
                    output = event.get("data", {}).get("output", {})
                    if node_name == "decompose":
                        sub_qs = output.get("sub_questions", [])
                        yield (
                            "thinking",
                            ThinkingEvent(
                                node="decompose",
                                label="问题分解",
                                content=f"分解为 {len(sub_qs)} 个子问题: {', '.join(sub_qs[:3])}",
                                done=True,
                            ),
                        )
                    elif node_name == "search":
                        sub_answers = output.get("sub_answers", [])
                        yield (
                            "thinking",
                            ThinkingEvent(
                                node="search",
                                label="知识检索",
                                content=f"完成 {len(sub_answers)} 个子问题的检索",
                                done=True,
                            ),
                        )
                    elif node_name == "evaluate":
                        sufficient = output.get("evidence_sufficient", False)
                        iteration = output.get("current_iteration", 0)
                        decision = "足够，停止迭代" if sufficient else "继续下一轮"
                        yield (
                            "thinking",
                            ThinkingEvent(
                                node="evaluate",
                                label="证据评估",
                                content=f"第 {iteration+1} 轮: {decision}",
                                done=True,
                            ),
                        )
                    elif node_name == "synthesize":
                        # Stream the synthesis response
                        final_answer = output.get("final_answer", "")
                        if final_answer:
                            # Stream it chunk by chunk
                            sentences = re.split(r"([。！？.!?]\s*)", final_answer)
                            buffer = ""
                            for sentence in sentences:
                                buffer += sentence
                                if len(buffer) >= 10:
                                    yield ("answer", buffer)
                                    buffer = ""
                            if buffer:
                                yield ("answer", buffer)

        except Exception as exc:
            yield ("error", f"深度研究出错：{str(exc)}")
            return

        yield ("done", {})

    # ──────────────────────────────────────────────────────────────
    # Legacy sync interfaces
    # ──────────────────────────────────────────────────────────────

    def ask(self, query: str, thread_id: str = "default") -> str:
        self.execution_log = []
        config = {"configurable": {"thread_id": thread_id}}
        initial_state: ResearchState = {
            "messages": [HumanMessage(content=query)],
            "question": query,
            "sub_questions": [],
            "current_iteration": 0,
            "max_iterations": 3,
            "evidence": [],
            "sub_answers": [],
            "evidence_sufficient": False,
            "final_answer": "",
        }
        try:
            for _ in self.graph.stream(initial_state, config=config):
                pass
            state = self.memory.get(config)
            return state["channel_values"].get("final_answer", "未能生成回答")
        except Exception as e:
            return f"深度研究过程中出错：{str(e)}"

    def ask_with_trace(self, query: str, thread_id: str = "default") -> Dict:
        answer = self.ask(query, thread_id)
        return {"answer": answer, "execution_log": self.execution_log}


async def _stable_deep_research_ask_stream(
    self: DeepResearchAgent,
    query: str,
    thread_id: str = "default",
) -> AsyncGenerator[tuple[str, Any], None]:
    """Stable streaming implementation independent of LangGraph event names."""
    del thread_id
    self.execution_log = []
    self._latest_retrieval_stats = empty_retrieval_stats()
    self._latest_source_items = []
    stream_start = time.perf_counter()
    first_token_latency_ms: int | None = None
    retrieve_latency_ms: int | None = None
    state: ResearchState = {
        "messages": [HumanMessage(content=query)],
        "question": query,
        "sub_questions": [],
        "current_iteration": 0,
        "max_iterations": 3,
        "evidence": [],
        "sub_answers": [],
        "evidence_sufficient": False,
        "final_answer": "",
    }

    def mark_first_token(chunk: str) -> None:
        nonlocal first_token_latency_ms
        if first_token_latency_ms is None and chunk.strip():
            first_token_latency_ms = int(
                (time.perf_counter() - stream_start) * 1000
            )

    try:
        while True:
            iteration = state.get("current_iteration", 0) + 1
            yield (
                "thinking",
                ThinkingEvent(
                    node="decompose",
                    label="问题分解",
                    content=f"开始第 {iteration} 轮问题分解...",
                    done=False,
                ),
            )
            decompose_output = await asyncio.to_thread(self._decompose_node, state)
            state.update(decompose_output)
            seen_questions: set[str] = set()
            sub_questions = []
            for candidate in [query, *state.get("sub_questions", [])]:
                normalized = candidate.strip()
                if normalized and normalized not in seen_questions:
                    seen_questions.add(normalized)
                    sub_questions.append(normalized)
            state["sub_questions"] = sub_questions[:4]
            sub_questions = state["sub_questions"]
            yield (
                "thinking",
                ThinkingEvent(
                    node="decompose",
                    label="问题分解",
                    content=(
                        f"分解为 {len(sub_questions)} 个子问题: "
                        f"{', '.join(sub_questions[:3])}"
                    ),
                    done=True,
                ),
            )

            yield (
                "thinking",
                ThinkingEvent(
                    node="search",
                    label="知识检索",
                    content=f"正在检索 {len(sub_questions)} 个子问题...",
                    done=False,
                ),
            )
            search_output = await self._search_state_async(state)
            state.update(search_output)
            retrieve_latency_ms = int((time.perf_counter() - stream_start) * 1000)
            sub_answers = state.get("sub_answers", [])
            evidence = state.get("evidence", [])
            yield (
                "thinking",
                ThinkingEvent(
                    node="search",
                    label="知识检索",
                    content=(
                        f"已完成 {len(sub_answers)} 个子问题检索，"
                        f"累计 {len(evidence)} 条证据。"
                    ),
                    done=True,
                ),
            )

            yield (
                "thinking",
                ThinkingEvent(
                    node="search",
                    label="知识检索",
                    content=summarize_retrieval_stats(self._latest_retrieval_stats),
                    done=True,
                ),
            )

            if not evidence:
                yield (
                    "thinking",
                    ThinkingEvent(
                        node="evaluate",
                        label="证据评估",
                        content="知识库未检索到可展示证据，已停止伪装成证据支撑的 RAG 回答。",
                        done=True,
                    ),
                )
                yield (
                    "thinking",
                    ThinkingEvent(
                        node="synthesize",
                        label="综合生成",
                        content="未生成正式 RAG 答案，请调整问法或补充知识库资料后重试。",
                        done=True,
                    ),
                )
                mark_first_token(_NO_EVIDENCE_ANSWER)
                yield ("answer", _NO_EVIDENCE_ANSWER)
                yield (
                    "done",
                    {
                        "retrieve_latency_ms": retrieve_latency_ms,
                        "first_token_latency_ms": first_token_latency_ms,
                        "answer_complete_latency_ms": int(
                            (time.perf_counter() - stream_start) * 1000
                        ),
                        "retrieval_stats": self._latest_retrieval_stats,
                        "source_items": self._latest_source_items,
                    },
                )
                return

            yield (
                "thinking",
                ThinkingEvent(
                    node="evaluate",
                    label="证据评估",
                    content="正在评估证据是否足以回答原问题...",
                    done=False,
                ),
            )
            evaluate_output = await asyncio.to_thread(self._evaluate_node, state)
            state.update(evaluate_output)
            current_iteration = state.get("current_iteration", iteration)
            sufficient = state.get("evidence_sufficient", False)
            decision = "证据足够，进入综合回答" if sufficient else "证据不足，继续研究"
            yield (
                "thinking",
                ThinkingEvent(
                    node="evaluate",
                    label="证据评估",
                    content=f"第 {current_iteration} 轮评估：{decision}。",
                    done=True,
                ),
            )

            if self._should_continue(state) == "synthesize":
                break

        yield (
            "thinking",
            ThinkingEvent(
                node="synthesize",
                label="综合生成",
                content="正在综合多轮证据生成最终回答...",
                done=False,
            ),
        )
        synthesize_output = await asyncio.to_thread(self._synthesize_node, state)
        state.update(synthesize_output)
        final_answer = state.get("final_answer", "")
        if final_answer:
            sentences = re.split(r"([。！？.!?]\s*)", final_answer)
            buffer = ""
            for sentence in sentences:
                buffer += sentence
                if len(buffer) >= 24:
                    mark_first_token(buffer)
                    yield ("answer", buffer)
                    buffer = ""
            if buffer:
                mark_first_token(buffer)
                yield ("answer", buffer)

        yield (
            "thinking",
            ThinkingEvent(
                node="synthesize",
                label="综合生成",
                content="深度研究回答生成完成。",
                done=True,
            ),
        )

    except Exception as exc:
        yield ("error", f"深度研究出错：{str(exc)}")
        return

    yield (
        "done",
        {
            "retrieve_latency_ms": retrieve_latency_ms,
            "first_token_latency_ms": first_token_latency_ms,
            "answer_complete_latency_ms": int(
                (time.perf_counter() - stream_start) * 1000
            ),
            "retrieval_stats": self._latest_retrieval_stats,
            "source_items": self._latest_source_items,
        },
    )


DeepResearchAgent.ask_stream = _stable_deep_research_ask_stream
