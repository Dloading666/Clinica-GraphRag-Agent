"""Chat router with SSE streaming"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.config.settings import settings
from app.models.schemas import AppConfig, ChatRequest
from app.security import chat_stream_limiter, get_client_ip
from app.services.chat_service import _stream_with_keepalive, process_chat_stream, sse_event

router = APIRouter()


@router.post("/stream")
async def chat_stream(payload: ChatRequest, request: Request):
    """SSE streaming chat endpoint."""
    message = payload.message.strip()
    if not message:
        raise HTTPException(400, "问题内容不能为空")

    if len(message) > settings.security.chat_max_message_chars:
        raise HTTPException(
            413,
            f"问题长度不能超过 {settings.security.chat_max_message_chars} 个字符",
        )

    top_k = max(1, min(payload.top_k, settings.security.chat_max_top_k))
    similarity_threshold = min(max(payload.similarity_threshold, 0.0), 1.0)
    debug = payload.debug and settings.security.allow_public_debug
    release_slot = chat_stream_limiter.acquire(get_client_ip(request))

    async def event_generator():
        try:
            stream = process_chat_stream(
                message=message,
                session_id=payload.session_id,
                agent_type=payload.agent_type,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
                debug=debug,
            )
            async for chunk in _stream_with_keepalive(stream):
                yield chunk if chunk is not None else sse_event("status", "heartbeat")
        finally:
            release_slot()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions")
async def get_sessions(db: AsyncSession = Depends(get_db)):
    """Get all chat sessions."""
    if not settings.security.public_session_access:
        raise HTTPException(404, "Not found")

    from sqlalchemy import select
    from app.models.db_models import ChatSession

    result = await db.execute(
        select(ChatSession).order_by(ChatSession.updated_at.desc()).limit(50)
    )
    sessions = result.scalars().all()
    return [
        {
            "id": s.id,
            "title": s.title,
            "created_at": str(s.created_at),
            "updated_at": str(s.updated_at),
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str, db: AsyncSession = Depends(get_db)):
    """Get messages for a session."""
    if not settings.security.public_session_access:
        raise HTTPException(404, "Not found")

    from sqlalchemy import select
    from app.models.db_models import ChatMessage

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    messages = result.scalars().all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "agent_type": m.agent_type,
            "created_at": str(m.created_at),
        }
        for m in messages
    ]


@router.get("/config")
async def get_config():
    """Get app configuration for frontend."""
    return AppConfig(
        entity_types=settings.ENTITY_TYPES,
        relation_types=settings.RELATION_TYPES,
        example_questions=settings.EXAMPLE_QUESTIONS,
        search_strategies=[
            {"id": "naive_rag", "name": "NAIVE RAG", "description": "向量相似度检索"},
            {"id": "graph_rag", "name": "GRAPH RAG", "description": "知识图谱检索"},
            {"id": "hybrid_rag", "name": "HYBRID RAG", "description": "混合检索"},
            {"id": "fusion_rag", "name": "FUSION RAG", "description": "融合检索+重排"},
            {"id": "deep_research", "name": "DEEP RESEARCH", "description": "深度多跳研究"},
        ],
        default_top_k=min(settings.search.top_k, settings.security.chat_max_top_k),
        default_similarity_threshold=settings.search.similarity_threshold,
        chat_defer_kg=settings.chat.defer_kg,
        frontend_typing_effect=settings.frontend.typing_effect,
    )
