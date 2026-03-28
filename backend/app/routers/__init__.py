from fastapi import APIRouter
from app.routers import chat, knowledge_base, knowledge_graph, analytics

api_router = APIRouter()
api_router.include_router(chat.router, prefix="/api/chat", tags=["chat"])
api_router.include_router(knowledge_base.router, prefix="/api/knowledge-base", tags=["knowledge-base"])
api_router.include_router(knowledge_graph.router, prefix="/api/kg", tags=["knowledge-graph"])
api_router.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
