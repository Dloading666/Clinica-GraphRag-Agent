"""Chat service - handles conversation processing and SSE streaming"""
import json
import time
import asyncio
import traceback
import re
from typing import AsyncGenerator, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.db_models import ChatSession, ChatMessage
from app.services.agent_service import agent_manager
from app.services.kg_service import get_kg_for_query
from app.config.database import AsyncSessionLocal


async def get_or_create_session(session_id: Optional[str], db: AsyncSession) -> ChatSession:
    """Get existing session or create new one"""
    import uuid
    if session_id:
        result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
        session = result.scalar_one_or_none()
        if session:
            return session
    # Create new session
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
    """Save a message to the database"""
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        agent_type=agent_type,
        execution_log=execution_log,
        kg_data=kg_data,
        references=references,
    )
    if db:
        db.add(msg)
    else:
        async with AsyncSessionLocal() as new_db:
            new_db.add(msg)
            await new_db.commit()


async def process_chat_stream(
    message: str,
    session_id: Optional[str],
    agent_type: str = "naive_rag",
    top_k: int = 15,
    similarity_threshold: float = 0.82,
    debug: bool = False,
) -> AsyncGenerator[str, None]:
    """
    Process chat request and yield SSE events.

    SSE event format (JSON strings prefixed with "data: "):
    - {"event": "status", "data": "processing"}
    - {"event": "session", "data": {"session_id": "xxx"}}
    - {"event": "trace", "data": {"node": "...", "input": "...", "output": "...", "latency": 0.42}}
    - {"event": "answer", "data": "token text"}
    - {"event": "kg_data", "data": {"nodes": [...], "links": [...]}}
    - {"event": "done", "data": {"session_id": "...", "total_latency": 5.67, "token_count": 1248}}
    - {"event": "error", "data": "error message"}
    """
    start_time = time.time()

    # Create/get session
    async with AsyncSessionLocal() as db:
        session = await get_or_create_session(session_id, db)
        actual_session_id = session.id

        # Save user message
        await save_message(actual_session_id, "user", message, db=db)
        await db.commit()

    def sse_event(event: str, data) -> str:
        return f"data: {json.dumps({'event': event, 'data': data}, ensure_ascii=False)}\n\n"

    try:
        yield sse_event("session", {"session_id": actual_session_id})
        yield sse_event("status", "processing")

        # Get agent
        agent = agent_manager.get_agent(agent_type, actual_session_id)

        # Execute with trace
        trace_start = time.time()
        agent_task = asyncio.create_task(
            asyncio.to_thread(agent.ask_with_trace, message, actual_session_id)
        )
        while not agent_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(agent_task), timeout=5.0)
            except asyncio.TimeoutError:
                # SSE comments are ignored by the frontend parser but keep the stream alive.
                yield ": keep-alive\n\n"
        result = await agent_task
        answer = result.get("answer", "")
        execution_log = result.get("execution_log", [])
        kg_task = asyncio.create_task(_build_kg_data(message, top_k))

        # Send trace events
        if debug and execution_log:
            for log_entry in execution_log:
                yield sse_event("trace", {
                    "node": log_entry.get("node", ""),
                    "input": str(log_entry.get("input", ""))[:200],
                    "output": str(log_entry.get("output", ""))[:500],
                    "latency": round(time.time() - trace_start, 2),
                })
                await asyncio.sleep(0.05)

        # Stream answer tokens
        sentences = re.split(r'([。！？.!?\n])', answer)
        buffer = ""
        for chunk in sentences:
            buffer += chunk
            if len(buffer) >= 30 or any(p in buffer for p in ['。', '！', '？', '\n']):
                yield sse_event("answer", buffer)
                buffer = ""
                await asyncio.sleep(0.02)
        if buffer:
            yield sse_event("answer", buffer)

        total_latency = round(time.time() - start_time, 2)
        token_count = len(answer) // 2  # rough estimate

        kg_data = None
        try:
            kg_candidate = await kg_task
            if kg_candidate and (kg_candidate.get("nodes") or kg_candidate.get("links")):
                kg_data = kg_candidate
                yield sse_event("kg_data", kg_data)
        except Exception as kg_exc:
            print(f"[ChatService] Failed to build KG payload: {kg_exc}")

        # Save AI response
        await save_message(
            actual_session_id,
            "assistant",
            answer,
            agent_type=agent_type,
            execution_log=execution_log if debug else None,
            kg_data=kg_data,
        )

        yield sse_event("done", {
            "session_id": actual_session_id,
            "total_latency": total_latency,
            "token_count": token_count,
        })

    except Exception as e:
        traceback.print_exc()
        yield sse_event("error", str(e))


async def _build_kg_data(message: str, top_k: int) -> dict:
    async with AsyncSessionLocal() as db:
        graph_limit = max(12, min(60, top_k * 4))
        return await get_kg_for_query(message, db, limit=graph_limit)
