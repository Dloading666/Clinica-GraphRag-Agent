"""FastAPI application entry point."""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.database import init_postgres, neo4j_manager
from app.config.settings import settings
from app.routers import api_router
from app.services.agent_service import agent_manager
from app.services.knowledge_base_task_service import knowledge_base_task_manager


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialize shared resources on startup and release them on shutdown."""
    print("Initializing PostgreSQL...")
    await init_postgres()

    print("Initializing Neo4j indexes...")
    try:
        from app.graph.neo4j_manager import clinical_graph_manager

        clinical_graph_manager.create_indexes()
    except Exception as exc:  # pragma: no cover - startup warning path
        print(f"Neo4j initialization warning: {exc}")

    try:
        bootstrap_status = await knowledge_base_task_manager.ensure_seeded()
        if bootstrap_status.get("active"):
            print(
                "[KnowledgeBase] Background bootstrap started: "
                f"{bootstrap_status.get('reason')}"
            )
    except Exception as exc:  # pragma: no cover - startup warning path
        print(f"Knowledge base bootstrap warning: {exc}")

    print("Service startup complete")
    yield

    agent_manager.close_all()
    neo4j_manager.close()
    print("Service shutdown complete")


app = FastAPI(
    title="Clinical QA Assistant API",
    description="Clinical decision support API backed by RAG and a knowledge graph.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health():
    """Simple health endpoint for container and local checks."""
    return {"status": "ok", "version": "1.0.0"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.server.host,
        port=settings.server.port,
        workers=settings.server.workers,
        reload=False,
    )
