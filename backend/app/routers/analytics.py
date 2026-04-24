"""Analytics router"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.config.database import get_db
from app.models.db_models import ChatSession, ChatMessage, Document, Chunk
from app.security import require_admin_api_key

router = APIRouter()


@router.get("/stats")
async def get_stats(request: Request, db: AsyncSession = Depends(get_db)):
    """Get usage statistics."""
    require_admin_api_key(request)
    session_count = await db.scalar(select(func.count(ChatSession.id)))
    message_count = await db.scalar(select(func.count(ChatMessage.id)))
    doc_count = await db.scalar(select(func.count(Document.id)))
    chunk_count = await db.scalar(select(func.count(Chunk.id)))

    return {
        "sessions": session_count or 0,
        "messages": message_count or 0,
        "documents": doc_count or 0,
        "chunks": chunk_count or 0,
    }


@router.get("/recent-sessions")
async def get_recent_sessions(
    request: Request,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """Get recent chat sessions with message counts."""
    require_admin_api_key(request)
    result = await db.execute(
        select(ChatSession).order_by(ChatSession.updated_at.desc()).limit(limit)
    )
    sessions = result.scalars().all()
    return [
        {
            "id": s.id,
            "title": s.title,
            "created_at": str(s.created_at),
        }
        for s in sessions
    ]
