"""Chat service - handles conversation processing and SSE streaming."""

import asyncio
import json
import time
from typing import AsyncGenerator, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.config.database import AsyncSessionLocal
from app.models.db_models import ChatMessage, ChatSession
from app.services.agent_service import agent_manager
from app.services.kg_service import get_kg_for_query

STREAM_HEARTBEAT_SECONDS = 8.0


async def ensure_session_exists(session_id: str, db: AsyncSession) -> ChatSession:
    """Ensure the parent chat session exists in the current transaction."""
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if session:
        return session
    session = ChatSession(id=session_id, title="新对话")
    db.add(session)
    await db.flush()
    return session


async def get_or_create_session(
    session_id: Optional[str], db: AsyncSession
) -> ChatSession:
    """Get an existing session or create a new one."""
    import uuid

    if session_id:
        result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
        session = result.scalar_one_or_none()
        if session:
            return session

    new_id = session_id or str(uuid.uuid4())
    session = ChatSession(id=new_id, title="新对话")
    db.add(session)
    await db.flush()
    return session


async def save_message(
    session_id: str,
    role: str,
    content: str,
    agent_type: str = None,
    execution_log=None,
    kg_data=None,
    references=None,
    db: AsyncSession = None,
):
    """Persist a message to the database."""
    if db:
        await ensure_session_exists(session_id, db)
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            agent_type=agent_type,
            execution_log=execution_log,
            kg_data=kg_data,
            references=references,
        )
        db.add(message)
        return

    async with AsyncSessionLocal() as new_db:
        await ensure_session_exists(session_id, new_db)
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            agent_type=agent_type,
            execution_log=execution_log,
            kg_data=kg_data,
            references=references,
        )
        new_db.add(message)
        await new_db.commit()


def sse_event(event: str, data) -> str:
    return f"data: {json.dumps({'event': event, 'data': data}, ensure_ascii=False)}\n\n"


async def _maybe_stream_pause() -> None:
    pacing_ms = settings.chat.stream_pacing_ms
    if pacing_ms <= 0:
        return
    await asyncio.sleep(pacing_ms / 1000)


def _log_stream_warning(stage: str, exc: Exception, *, query_length: int) -> None:
    message = " ".join(str(exc).split())
    print(
        json.dumps(
            {
                "scope": "chat_stream",
                "stage": stage,
                "query_length": query_length,
                "error": message,
            },
            ensure_ascii=False,
        )
    )


async def process_chat_stream(
    message: str,
    session_id: Optional[str],
    agent_type: str = "naive_rag",
    top_k: int = 15,
    similarity_threshold: float = 0.82,
    debug: bool = False,
) -> AsyncGenerator[str, None]:
    """
    Process a chat request and yield SSE events.

    Handles the new tuple-based streaming from BaseAgent.ask_stream:
      - ("thinking", ThinkingEvent) → SSE "thinking" event
      - ("answer", str)             → SSE "answer" event
      - ("error", str)              → SSE "error" event
      - ("done", {})                → SSE "done" event
    """
    del similarity_threshold
    start_time = time.perf_counter()

    async with AsyncSessionLocal() as db:
        session = await get_or_create_session(session_id, db)
        actual_session_id = session.id
        await save_message(actual_session_id, "user", message, db=db)
        await db.commit()

    try:
        yield sse_event("session", {"session_id": actual_session_id})
        yield sse_event("status", "processing")

        agent = agent_manager.get_agent(agent_type, actual_session_id)

        answer_chunks: list[str] = []
        execution_log = []
        thinking_events: list[dict] = []
        stream_metrics: dict[str, int | bool | None] = {}
        kg_data = None
        retrieval_stats = None
        source_items = None

        if debug:
            # Debug mode: use blocking ask_with_trace for full trace
            trace_start = time.perf_counter()
            result = await asyncio.to_thread(
                agent.ask_with_trace, message, actual_session_id
            )
            answer = result.get("answer", "")
            execution_log = result.get("execution_log", [])

            for log_entry in execution_log:
                yield sse_event(
                    "trace",
                    {
                        "node": log_entry.get("node", ""),
                        "input": str(log_entry.get("input", ""))[:200],
                        "output": str(log_entry.get("output", ""))[:500],
                        "latency": round(time.perf_counter() - trace_start, 2),
                    },
                )
                await _maybe_stream_pause()

            for chunk in _chunk_text(answer):
                answer_chunks.append(chunk)
                yield sse_event("answer", chunk)
                await _maybe_stream_pause()

        else:
            # Production mode: true streaming with thinking events
            async for event_type, payload in agent.ask_stream(
                message, actual_session_id
            ):
                if event_type == "thinking":
                    te = payload
                    thinking_data = {
                        "node": te.node,
                        "label": te.label,
                        "content": te.content,
                        "done": te.done,
                    }
                    thinking_events.append(thinking_data)
                    yield sse_event("thinking", thinking_data)
                    await _maybe_stream_pause()

                elif event_type == "answer":
                    answer_chunks.append(payload)
                    yield sse_event("answer", payload)
                    await _maybe_stream_pause()

                elif event_type == "error":
                    yield sse_event("error", str(payload))

                elif event_type == "done":
                    if isinstance(payload, dict):
                        stream_metrics = payload
                        retrieval_stats = payload.get("retrieval_stats")
                        source_items = payload.get("source_items")

        answer = "".join(answer_chunks)
        total_latency = round(time.perf_counter() - start_time, 2)
        token_count = len(answer) // 2  # rough estimate; fixme: use tiktoken

        if not debug and not settings.chat.defer_kg:
            try:
                kg_candidate = await _build_kg_data(message, top_k)
                if kg_candidate and (kg_candidate.get("nodes") or kg_candidate.get("links")):
                    kg_data = kg_candidate
                    yield sse_event("kg_data", kg_data)
            except Exception as kg_exc:
                _log_stream_warning("kg", kg_exc, query_length=len(message))

        # Persist assistant message
        try:
            await save_message(
                actual_session_id,
                "assistant",
                answer,
                agent_type=agent_type,
                execution_log=execution_log if debug else thinking_events,
                kg_data=kg_data,
                references=source_items,
            )
        except Exception as persist_exc:
            _log_stream_warning("persist", persist_exc, query_length=len(message))

        done_payload = {
            "session_id": actual_session_id,
            "total_latency": total_latency,
            "token_count": token_count,
            "first_token_latency_ms": stream_metrics.get("first_token_latency_ms"),
            "retrieve_latency_ms": stream_metrics.get("retrieve_latency_ms"),
            "answer_complete_latency_ms": (
                stream_metrics.get("answer_complete_latency_ms")
                if stream_metrics.get("answer_complete_latency_ms") is not None
                else int(total_latency * 1000)
            ),
            "retrieval_stats": retrieval_stats,
            "source_items": source_items,
        }

        yield sse_event("done", done_payload)

    except Exception as exc:
        _log_stream_warning("stream", exc, query_length=len(message))
        yield sse_event("error", str(exc))


def _chunk_text(answer: str):
    """Keep the existing debug-mode pseudo-streaming behavior."""
    if not answer:
        return []

    chunks = []
    buffer = ""
    for char in answer:
        buffer += char
        if len(buffer) >= 30 or char in {"。", "！", "？", "!", "?", "\n"}:
            chunks.append(buffer)
            buffer = ""
    if buffer:
        chunks.append(buffer)
    return chunks


async def _build_kg_data(message: str, top_k: int) -> dict:
    async with AsyncSessionLocal() as db:
        graph_limit = max(12, min(60, top_k * 4))
        return await get_kg_for_query(message, db, limit=graph_limit)


async def _stream_with_keepalive(
    stream: AsyncGenerator[str, None],
    *,
    heartbeat_seconds: float = STREAM_HEARTBEAT_SECONDS,
) -> AsyncGenerator[Optional[str], None]:
    iterator = stream.__aiter__()
    pending = asyncio.create_task(iterator.__anext__())
    last_progress_at = time.perf_counter()
    max_stall_seconds = max(15, settings.chat.max_stall_seconds)

    while True:
        done, _ = await asyncio.wait(
            {pending},
            timeout=heartbeat_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )

        if not done:
            stalled_for = time.perf_counter() - last_progress_at
            if stalled_for >= max_stall_seconds:
                pending.cancel()
                try:
                    await pending
                except BaseException:
                    pass
                yield sse_event(
                    "error",
                    f"模型响应超时：连续 {int(stalled_for)} 秒未返回新内容，请重试。",
                )
                break
            yield None
            continue

        try:
            chunk = pending.result()
        except StopAsyncIteration:
            break
        else:
            last_progress_at = time.perf_counter()
            yield chunk
            pending = asyncio.create_task(iterator.__anext__())
