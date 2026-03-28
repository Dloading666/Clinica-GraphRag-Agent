"""Chat router with SSE streaming"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.models.schemas import AppConfig
from app.services.chat_service import process_chat_stream
from app.config.settings import settings

router = APIRouter()


@router.post("/stream")
async def chat_stream(request: Request):
    """SSE streaming chat endpoint"""
    data = await request.json()
    message = data.get("message", "")
    session_id = data.get("session_id")
    agent_type = data.get("agent_type", "naive_rag")
    top_k = data.get("top_k", settings.search.top_k)
    similarity_threshold = data.get("similarity_threshold", settings.search.similarity_threshold)
    debug = data.get("debug", False)

    async def event_generator():
        async for chunk in process_chat_stream(
            message=message,
            session_id=session_id,
            agent_type=agent_type,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            debug=debug,
        ):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/sessions")
async def get_sessions(db: AsyncSession = Depends(get_db)):
    """Get all chat sessions"""
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
    """Get messages for a session"""
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
    """Get app configuration for frontend"""
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
        default_top_k=settings.search.top_k,
        default_similarity_threshold=settings.search.similarity_threshold,
    )
