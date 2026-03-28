"""Knowledge graph visualization router"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.config.database import get_db
from app.models.schemas import KGData, ReasoningRequest
from app.services.kg_service import get_kg_for_query, get_kg_visualization, graph_reasoning

router = APIRouter()


@router.get("/visualization", response_model=KGData)
async def get_graph_visualization(
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Get full knowledge graph for visualization"""
    data = await get_kg_visualization(db, limit=limit)
    return KGData(**data)


@router.get("/query", response_model=KGData)
async def get_graph_for_query(
    q: str = Query(..., description="Query to get relevant subgraph"),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Get knowledge graph subgraph relevant to a query"""
    data = await get_kg_for_query(q, db, limit=limit)
    return KGData(**data)


@router.post("/reasoning")
async def perform_reasoning(
    request: ReasoningRequest,
    db: AsyncSession = Depends(get_db),
):
    """Perform graph reasoning"""
    result = await graph_reasoning(
        reasoning_type=request.type,
        entity_a=request.entity_a,
        entity_b=request.entity_b,
        max_depth=request.max_depth,
        db=db,
    )
    return result


@router.get("/stats")
async def get_graph_stats(db: AsyncSession = Depends(get_db)):
    """Get knowledge graph statistics"""
    from sqlalchemy import func, select
    from app.models.db_models import Entity, Relationship, Community

    entity_count = await db.scalar(select(func.count(Entity.id)))
    rel_count = await db.scalar(select(func.count(Relationship.id)))
    community_count = await db.scalar(select(func.count(Community.id)))
    return {
        "entities": entity_count or 0,
        "relationships": rel_count or 0,
        "communities": community_count or 0,
    }
