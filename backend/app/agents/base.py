"""Base LangGraph agent with true streaming via astream_events."""

import asyncio
import threading
import time
from abc import ABC, abstractmethod
from typing import Annotated, Any, AsyncGenerator, Dict, List, Sequence, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from app.config.settings import settings
from app.models.llm_factory import content_to_text, get_embeddings, get_llm
from app.search.query_expansion import (
    empty_retrieval_stats,
    has_visible_evidence,
    summarize_retrieval_stats,
)


_RUN_ASYNC_LOOP: asyncio.AbstractEventLoop | None = None
_RUN_ASYNC_THREAD: threading.Thread | None = None
_RUN_ASYNC_LOCK = threading.Lock()


def _ensure_run_async_loop() -> asyncio.AbstractEventLoop:
    """Keep one dedicated loop for sync-to-async tool bridges.

    The retrieval tools are invoked from worker threads, but they depend on
    async database sessions. Reusing a single background loop avoids attaching
    pooled asyncpg futures to whichever temporary loop happened to execute the
    last request.
    """
    global _RUN_ASYNC_LOOP, _RUN_ASYNC_THREAD

    with _RUN_ASYNC_LOCK:
        if _RUN_ASYNC_LOOP and _RUN_ASYNC_LOOP.is_running():
            return _RUN_ASYNC_LOOP

        ready = threading.Event()
        loop_holder: dict[str, asyncio.AbstractEventLoop] = {}

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop_holder["loop"] = loop
            ready.set()
            loop.run_forever()
            loop.close()

        _RUN_ASYNC_THREAD = threading.Thread(
            target=_runner,
            name="clinirag-run-async-loop",
            daemon=True,
        )
        _RUN_ASYNC_THREAD.start()
        ready.wait()
        _RUN_ASYNC_LOOP = loop_holder["loop"]
        return _RUN_ASYNC_LOOP


def run_async(coro):
    """Run async code safely from sync contexts."""
    loop = _ensure_run_async_loop()

    if _RUN_ASYNC_THREAD is not None and threading.current_thread() is _RUN_ASYNC_THREAD:
        raise RuntimeError("run_async cannot block on its own event loop thread")

    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


# ──────────────────────────────────────────────────────────────────
# Thinking event helpers
# ──────────────────────────────────────────────────────────────────

class ThinkingEvent:
    """Structured thinking event emitted per node during streaming."""
    __slots__ = ("node", "label", "content", "done")

    def __init__(self, node: str, label: str, content: str = "", done: bool = False):
        self.node = node
        self.label = label
        self.content = content
        self.done = done

    def to_sse(self) -> str:
        import json
        payload = {'event': 'thinking', 'data': {
            'node': self.node,
            'label': self.label,
            'content': self.content,
            'done': self.done,
        }}
        return 'data: ' + json.dumps(payload, ensure_ascii=False) + '\\n\\n\\'


# ──────────────────────────────────────────────────────────────────
# Base Agent
# ──────────────────────────────────────────────────────────────────

class BaseAgent(ABC):
    """Base class for LangGraph-powered clinical QA agents."""

    def __init__(self):
        self.llm = get_llm()
        self.stream_llm = get_llm(streaming=True)
        self.embeddings = get_embeddings()
        self.memory = MemorySaver()
        self.execution_log: List[Dict] = []
        self.require_knowledge_evidence = False
        self._latest_retrieval_stats: Dict[str, Any] = empty_retrieval_stats()
        self._latest_source_items: List[Dict[str, Any]] = []
        self.tools = self._setup_tools()
        self._setup_graph()

    # ──────────────────────────────────────────────────────────────
    # Abstract methods (override in subclasses)
    # ──────────────────────────────────────────────────────────────

    @abstractmethod
    def _setup_tools(self) -> List:
        """Return the tool list used by the agent."""

    @abstractmethod
    def _add_retrieval_edges(self, workflow: StateGraph) -> None:
        """Wire retrieval edges for the agent workflow."""

    @abstractmethod
    def _generate_node(self, state: AgentState) -> Dict:
        """Generate the final answer for the current state."""

    @abstractmethod
    def _extract_keywords(self, query: str) -> Dict[str, List[str]]:
        """Extract query keywords when an agent needs them."""

    @abstractmethod
    async def _stream_response(self, state: AgentState) -> AsyncGenerator[str, None]:
        """Stream the final answer for a prepared graph state."""

    # ──────────────────────────────────────────────────────────────
    # Graph setup
    # ──────────────────────────────────────────────────────────────

    def _setup_graph(self) -> None:
        workflow = StateGraph(AgentState)
        workflow.add_node("agent", self._agent_node)
        workflow.add_node("retrieve", ToolNode(self.tools))
        workflow.add_node("generate", self._generate_node)
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            tools_condition,
            {"tools": "retrieve", END: END},
        )
        self._add_retrieval_edges(workflow)
        workflow.add_edge("generate", END)
        self.graph = workflow.compile(checkpointer=self.memory)

    # ──────────────────────────────────────────────────────────────
    # Node implementations
    # ──────────────────────────────────────────────────────────────

    def _agent_node(self, state: AgentState) -> Dict:
        messages = state["messages"]
        model = self.llm.bind_tools(self.tools)
        response = model.invoke(messages)
        self._log_execution(
            "agent",
            content_to_text(messages[-1].content) if messages else "",
            content_to_text(response.content) if hasattr(response, "content") else "",
        )
        return {"messages": [response]}

    def _log_execution(self, node_name: str, input_data: Any, output_data: Any) -> None:
        self.execution_log.append({
            "node": node_name,
            "timestamp": time.time(),
            "input": str(input_data)[:200] if input_data else "",
            "output": str(output_data)[:500] if output_data else "",
        })

    def _reset_retrieval_metadata(self) -> None:
        self._latest_retrieval_stats = empty_retrieval_stats()
        self._latest_source_items = []

    def _set_retrieval_metadata(
        self,
        *,
        stats: Dict[str, Any] | None = None,
        source_items: List[Dict[str, Any]] | None = None,
    ) -> None:
        self._latest_retrieval_stats = stats or empty_retrieval_stats()
        self._latest_source_items = source_items or []

    def _build_no_evidence_answer(self) -> str:
        return (
            "当前未从知识库检索到可展示证据，本轮不输出伪装成知识库支撑的 RAG 正式回答。"
            "建议你换一种问法、缩小问题范围，或先补充对应的知识库资料后再试。"
        )

    def _normalize_retrieval_context(self, value: Any) -> str:
        text = content_to_text(value).strip()
        normalized = text.lower()
        hidden_markers = (
            "未检索到相关临床资料", "未检索到相关资料",
            "未找到与该问题相关的信息", "知识图谱中暂无社区数据",
            "处理问题时出错", "生成回答时出错",
            "agent execution failed", "streaming generation failed",
            "event loop", "事件循环", "runtime error",
            "naive_rag_agent.py", "no relevant information",
            "no relevant knowledge", "no relevant context",
        )
        if any(m in text for m in hidden_markers):
            return ""
        if any(m in normalized for m in hidden_markers):
            return ""
        return text

    def _get_latest_user_message(self, messages: Sequence[BaseMessage]) -> str:
        for message in reversed(messages):
            if isinstance(message, HumanMessage):
                return content_to_text(message.content).strip()
        if messages:
            return content_to_text(messages[-1].content).strip()
        return ""

    def _is_retryable_llm_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        retryable = (
            "429",
            "503",
            "529",
            "busy",
            "overloaded_error",
            "rate limit",
            "temporarily unavailable",
            "timeout",
            "connection reset",
            "service unavailable",
        )
        return any(m in message for m in retryable)

    def _user_facing_error_message(self, exc: Exception) -> str:
        if self._is_retryable_llm_error(exc):
            return "模型服务当前较忙，请稍后再试。"
        return "当前生成回答时出现问题，请稍后重试。"

    def _invoke_llm_with_retry(self, invoke_fn, *, max_attempts: int = 3):
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return invoke_fn()
            except Exception as exc:
                last_exc = exc
                if attempt >= max_attempts or not self._is_retryable_llm_error(exc):
                    raise
                time.sleep(attempt)
        if last_exc is not None:
            raise last_exc

    def _should_fast_start(self, query: str) -> bool:
        if not settings.chat.fast_start_enabled:
            return False
        normalized = query.strip().lower()
        if len(normalized) < 6:
            return False
        small_talk = ("hi", "hello", "thanks", "thank you",
                      "你好", "您好", "谢谢", "在吗", "测试")
        return not any(m in normalized for m in small_talk)

    # ──────────────────────────────────────────────────────────────
    # Streaming helpers
    # ──────────────────────────────────────────────────────────────

    def _extract_fallback_context(self, payload: Dict[str, Any]) -> str:
        for key in ("context", "report_data", "all_results", "context_data"):
            value = payload.get(key)
            normalized = self._normalize_retrieval_context(value)
            if normalized:
                return normalized
        return ""

    def _build_busy_context_fallback(self, payload: Dict[str, Any]) -> str | None:
        context = self._extract_fallback_context(payload)
        if not context:
            return None

        sections = [
            section.strip()
            for section in context.split("\n\n---\n\n")
            if section.strip()
        ]
        excerpts: List[str] = []

        for index, section in enumerate(sections[:3], 1):
            lines = [line.strip() for line in section.splitlines() if line.strip()]
            if not lines:
                continue
            excerpt = "\n".join(lines[:4]).strip()
            if len(excerpt) > 400:
                excerpt = excerpt[:400].rstrip() + "..."
            excerpts.append(f"[{index}] {excerpt}")

        if not excerpts:
            compact = context.strip()
            if len(compact) > 800:
                compact = compact[:800].rstrip() + "..."
            excerpts.append(compact)

        joined = "\n\n".join(excerpts)
        return (
            "当前模型服务暂时繁忙，先返回已检索到的参考资料摘录，供快速查看：\n\n"
            f"{joined}\n\n"
            "建议稍后重试，以获取完整的结构化分析。"
        )

    async def _run_single_tool_retrieval(
        self,
        query: str,
        messages: List[BaseMessage],
        reason: Exception | None = None,
    ) -> Dict[str, Any] | None:
        if len(self.tools) != 1:
            return None

        tool = self.tools[0]
        tool_name = getattr(tool, "name", "single_tool")

        try:
            if hasattr(tool, "ainvoke"):
                result = await tool.ainvoke(query)
            elif hasattr(tool, "invoke"):
                result = await asyncio.to_thread(tool.invoke, query)
            else:
                result = await asyncio.to_thread(tool.func, query)
        except Exception as tool_exc:
            self._log_execution(
                "agent",
                query,
                f"single_tool_fallback_failed:{tool_name}:{tool_exc}",
            )
            if reason is not None:
                raise reason
            raise

        normalized = content_to_text(result).strip()
        self._log_execution(
            "agent",
            query,
            (
                f"single_tool_fallback:{tool_name}:{type(reason).__name__}"
                if reason is not None
                else f"single_tool_retrieval:{tool_name}"
            ),
        )
        self._log_execution("retrieve", query, normalized)
        messages.append(AIMessage(content=normalized))
        return {"messages": messages, "direct_answer": ""}

    async def _stream_fast_start_preamble(
        self, query: str
    ) -> AsyncGenerator[str, None]:
        """Stream a short opening answer while retrieval runs in parallel."""
        opener = "先给你一个简要结论：\n"
        yield opener

        prompt_messages = [
            SystemMessage(content=(
                "You are answering a user in real time. Respond immediately with a "
                "brief, high-confidence preliminary answer in the user's language. "
                "Do not mention retrieval, tools, sources, knowledge bases, or that "
                "you are still thinking. Keep it concise and naturally lead into a "
                "more detailed explanation."
            )),
            HumanMessage(content=query),
        ]

        chunks: List[str] = []
        try:
            async for chunk in self.stream_llm.astream(prompt_messages):
                text = content_to_text(getattr(chunk, "content", chunk))
                if not text:
                    continue
                chunks.append(text)
                yield text
                combined = "".join(chunks)
                if len(combined) >= 180 and combined.rstrip().endswith(
                    ("。", ".", "！", "!", "？", "?", "\n")):
                    break
            preamble = "".join(chunks).strip()
            if preamble:
                self._log_execution("fast_start", query, preamble[:500])
        except Exception as exc:
            self._log_execution("fast_start", query, f"skipped ({exc})")

        yield "\n\n"

    async def _stream_prompt_response(
        self, prompt, payload: Dict[str, Any], *, node_name: str, log_input: str,
    ) -> AsyncGenerator[str, None]:
        prompt_messages = prompt.format_messages(**payload)
        last_exc: Exception | None = None

        for attempt in range(1, 4):
            chunks: List[str] = []
            try:
                async for chunk in self.stream_llm.astream(prompt_messages):
                    text = content_to_text(getattr(chunk, "content", chunk))
                    if not text:
                        continue
                    chunks.append(text)
                    yield text
                self._log_execution(node_name, log_input, "".join(chunks))
                return
            except Exception as exc:
                last_exc = exc
                if chunks:
                    self._log_execution(node_name, log_input, "".join(chunks))
                    return
                try:
                    sync_response = await asyncio.to_thread(
                        self._invoke_llm_with_retry,
                        lambda: self.llm.invoke(prompt_messages),
                    )
                    sync_text = content_to_text(
                        getattr(sync_response, "content", sync_response)
                    ).strip()
                    if sync_text:
                        self._log_execution(
                            node_name,
                            log_input,
                            (
                                f"{sync_text[:500]} "
                                f"[sync_fallback:{type(exc).__name__}]"
                            ),
                        )
                        yield sync_text
                        return
                except Exception as sync_exc:
                    last_exc = sync_exc
                if attempt < 3 and self._is_retryable_llm_error(exc):
                    await asyncio.sleep(attempt)
                    continue
                fallback = self._build_busy_context_fallback(payload)
                if fallback:
                    self._log_execution(
                        node_name,
                        log_input,
                        f"{fallback[:500]} [fallback:{type(exc).__name__}]",
                    )
                    yield fallback
                    return
                error = self._user_facing_error_message(exc)
                self._log_execution(node_name, log_input, f"{error} ({exc})")
                yield error
                return

        if last_exc is not None:
            fallback = self._build_busy_context_fallback(payload)
            if fallback:
                self._log_execution(
                    node_name,
                    log_input,
                    f"{fallback[:500]} [fallback:{type(last_exc).__name__}]",
                )
                yield fallback
                return
            error = self._user_facing_error_message(last_exc)
            self._log_execution(node_name, log_input, f"{error} ({last_exc})")
            yield error

    def _load_thread_history(self, thread_id: str) -> List[BaseMessage]:
        config = {"configurable": {"thread_id": thread_id}}
        state = self.memory.get(config)
        if not state:
            return []
        return list(state["channel_values"].get("messages", []))

    async def _prepare_stream_state(self, query: str, thread_id: str) -> Dict[str, Any]:
        """Prepare retrieval state without crossing event loops."""
        history = self._load_thread_history(thread_id)
        messages: List[BaseMessage] = [*history, HumanMessage(content=query)]
        model = self.llm.bind_tools(self.tools)
        try:
            response = await asyncio.to_thread(
                self._invoke_llm_with_retry,
                lambda: model.invoke(messages),
            )
        except Exception as exc:
            fallback = await self._run_single_tool_retrieval(query, messages, exc)
            if fallback is not None:
                return fallback
            raise
        self._log_execution(
            "agent",
            content_to_text(messages[-1].content) if messages else "",
            content_to_text(response.content) if hasattr(response, "content") else "",
        )
        messages.append(response)
        tool_calls = getattr(response, "tool_calls", None) or \
            getattr(response, "additional_kwargs", {}).get("tool_calls", [])
        if not tool_calls:
            return {
                "messages": messages,
                "direct_answer": content_to_text(
                    response.content if hasattr(response, "content") else response),
            }
        tool_result = await ToolNode(self.tools).ainvoke({"messages": messages})
        tool_messages = tool_result.get("messages", [])
        for tool_message in tool_messages:
            self._log_execution("retrieve", query, content_to_text(tool_message.content))
        messages.extend(tool_messages)
        return {"messages": messages, "direct_answer": ""}

    # ──────────────────────────────────────────────────────────────
    # Core streaming entry point — yields (event_type, payload) tuples
    # ──────────────────────────────────────────────────────────────

    async def ask_stream(
        self, query: str, thread_id: str = "default"
    ) -> AsyncGenerator[tuple[str, Any], None]:
        """
        True streaming: emit thinking events as each node completes,
        then stream answer chunks as they arrive.

        Yields (event_type, payload) tuples:
          - ("thinking", ThinkingEvent) — intermediate node output
          - ("answer", str) — answer text chunk
          - ("done", {}) — final marker
          - ("error", str) — error message
        """
        self.execution_log = []
        self._reset_retrieval_metadata()
        answer_parts: List[str] = []
        stream_start = time.perf_counter()
        first_token_latency_ms: int | None = None
        retrieve_latency_ms: int | None = None
        used_fast_start = False

        def mark_first_token(chunk: str) -> None:
            nonlocal first_token_latency_ms
            if first_token_latency_ms is None and chunk and chunk.strip():
                first_token_latency_ms = int((time.perf_counter() - stream_start) * 1000)

        try:
            yield (
                "thinking",
                ThinkingEvent(
                    node="agent",
                    label="理解问题",
                    content=query[:120],
                    done=True,
                ),
            )

            # 1. Kick off retrieval in background
            prepared_task = asyncio.create_task(
                self._prepare_stream_state(query, thread_id)
            )

            # 2. Fast start preamble while retrieval runs
            if self._should_fast_start(query):
                async for chunk in self._stream_fast_start_preamble(query):
                    if not chunk:
                        continue
                    used_fast_start = True
                    mark_first_token(chunk)
                    answer_parts.append(chunk)
                    yield ("answer", chunk)

            # 3. Wait for retrieval
            try:
                prepared = await prepared_task
            except Exception as exc:
                yield ("error", self._user_facing_error_message(exc))
                return
            retrieve_latency_ms = int((time.perf_counter() - stream_start) * 1000)
            retrieval_summary = summarize_retrieval_stats(self._latest_retrieval_stats)

            # 4. Emit thinking for completed planning / retrieval steps
            for log_entry in self.execution_log:
                if log_entry["node"] not in {"agent", "retrieve"}:
                    continue

                yield (
                    "thinking",
                    ThinkingEvent(
                        node=log_entry["node"],
                        label="规划检索" if log_entry["node"] == "agent" else "知识检索",
                        content=(
                            log_entry["output"][:300]
                            if log_entry["node"] == "agent"
                            else retrieval_summary
                        ),
                        done=True,
                    ),
                )

            if self.require_knowledge_evidence and not has_visible_evidence(
                self._latest_retrieval_stats
            ):
                no_evidence_answer = self._build_no_evidence_answer()
                mark_first_token(no_evidence_answer)
                answer_parts.append(no_evidence_answer)
                config = {"configurable": {"thread_id": thread_id}}
                try:
                    self.graph.update_state(
                        config,
                        {"messages": [
                            HumanMessage(content=query),
                            AIMessage(content=no_evidence_answer)
                        ]},
                        as_node="generate",
                    )
                except Exception:
                    pass
                yield (
                    "thinking",
                    ThinkingEvent(
                        node="generate",
                        label="组织回答",
                        content="知识库未命中可展示证据，已阻止伪装成证据支撑的回答。",
                        done=True,
                    ),
                )
                yield ("answer", no_evidence_answer)
                yield (
                    "done",
                    {
                        "retrieve_latency_ms": retrieve_latency_ms,
                        "first_token_latency_ms": first_token_latency_ms,
                        "answer_complete_latency_ms": int((time.perf_counter() - stream_start) * 1000),
                        "used_fast_start": used_fast_start,
                        "retrieval_stats": self._latest_retrieval_stats,
                        "source_items": self._latest_source_items,
                    },
                )
                return

            # 5. Stream the response
            yield (
                "thinking",
                ThinkingEvent(
                    node="generate",
                    label="组织回答",
                    content="正在基于当前上下文生成回答",
                    done=False,
                ),
            )
            direct_answer = prepared.get("direct_answer", "")
            if direct_answer:
                direct_text = direct_answer.lstrip() if used_fast_start else direct_answer
                if direct_text:
                    mark_first_token(direct_text)
                    answer_parts.append(direct_text)
                    yield ("answer", direct_text)
            else:
                state = {"messages": prepared["messages"]}
                async for chunk in self._stream_response(state):
                    if not chunk:
                        continue
                    mark_first_token(chunk)
                    answer_parts.append(chunk)
                    yield ("answer", chunk)

            yield (
                "thinking",
                ThinkingEvent(
                    node="generate",
                    label="组织回答",
                    content="回答生成完成",
                    done=True,
                ),
            )

        except Exception as exc:
            error = self._user_facing_error_message(exc)
            answer_parts = [error]
            yield ("error", error)

        # 6. Persist to checkpointer
        final_answer = "".join(answer_parts)
        if final_answer and not final_answer.isspace():
            config = {"configurable": {"thread_id": thread_id}}
            try:
                self.graph.update_state(
                    config,
                    {"messages": [
                        HumanMessage(content=query),
                        AIMessage(content=final_answer)
                    ]},
                    as_node="generate",
                )
            except Exception:
                pass

        yield (
            "done",
            {
                "retrieve_latency_ms": retrieve_latency_ms,
                "first_token_latency_ms": first_token_latency_ms,
                "answer_complete_latency_ms": int((time.perf_counter() - stream_start) * 1000),
                "used_fast_start": used_fast_start,
                "retrieval_stats": self._latest_retrieval_stats,
                "source_items": self._latest_source_items,
            },
        )

    # ──────────────────────────────────────────────────────────────
    # Legacy sync / trace interfaces (unchanged)
    # ──────────────────────────────────────────────────────────────

    def ask(self, query: str, thread_id: str = "default") -> str:
        self.execution_log = []
        config = {"configurable": {"thread_id": thread_id}}
        inputs = {"messages": [HumanMessage(content=query)]}
        try:
            for _ in self.graph.stream(inputs, config=config):
                pass
            state = self.memory.get(config)
            chat_history = state["channel_values"]["messages"]
            if not chat_history:
                return "No answer generated."
            return content_to_text(chat_history[-1].content)
        except Exception as exc:
            return self._user_facing_error_message(exc)

    def ask_with_trace(self, query: str, thread_id: str = "default") -> Dict:
        self.execution_log = []
        config = {"configurable": {"thread_id": thread_id}}
        inputs = {"messages": [HumanMessage(content=query)]}
        try:
            for _ in self.graph.stream(inputs, config=config):
                pass
            state = self.memory.get(config)
            chat_history = state["channel_values"]["messages"]
            answer = (
                content_to_text(chat_history[-1].content)
                if chat_history else "No answer generated."
            )
            return {"answer": answer, "execution_log": self.execution_log}
        except Exception as exc:
            error = self._user_facing_error_message(exc)
            return {"answer": error, "execution_log": self.execution_log}
