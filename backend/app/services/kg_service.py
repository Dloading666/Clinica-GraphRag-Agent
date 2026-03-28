"""Knowledge graph service - provides KG data for frontend visualization."""

import asyncio
import re
from typing import Dict, List

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.neo4j_manager import clinical_graph_manager
from app.models.db_models import Entity, Relationship
from app.models.llm_factory import get_embeddings


def _serialize_entity(entity: Entity, similarity: float | None = None) -> Dict:
    return {
        "id": entity.id,
        "name": entity.name,
        "entity_type": entity.entity_type,
        "description": entity.description,
        "similarity": similarity,
    }


async def _find_entities_by_embedding(
    query: str, db: AsyncSession, limit: int
) -> List[Dict]:
    embeddings_model = get_embeddings()
    query_embedding = await asyncio.to_thread(embeddings_model.embed_query, query)

    sql = text(
        """
        SELECT id, name, entity_type, description,
               1 - (embedding <=> CAST(:vec AS vector)) AS similarity
        FROM entities
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:vec AS vector)
        LIMIT :limit
        """
    )

    result = await db.execute(sql, {"vec": str(query_embedding), "limit": limit})
    rows = result.fetchall()
    return [
        {
            "id": row.id,
            "name": row.name,
            "entity_type": row.entity_type,
            "description": row.description,
            "similarity": float(row.similarity),
        }
        for row in rows
    ]


def _text_match_score(entity: Entity, query: str, tokens: List[str]) -> float:
    name = entity.name or ""
    description = entity.description or ""

    score = 0.0
    if name and name in query:
        score += 12
    if name == query:
        score += 10
    elif query and query.lower() in name.lower():
        score += 6
    elif query and query.lower() in description.lower():
        score += 3

    for token in tokens:
        if token in name:
            score += 2
        if token in description:
            score += 1

    return score


async def _find_entities_by_text(query: str, db: AsyncSession, limit: int) -> List[Dict]:
    clean_query = query.strip()
    if not clean_query:
        return []

    tokens = [
        token
        for token in re.split(r"[\s,，。；;、（）()]+", clean_query)
        if len(token.strip()) >= 2
    ]
    search_terms = [clean_query, *tokens]

    conditions = []
    for term in search_terms[:6]:
        pattern = f"%{term}%"
        conditions.append(Entity.name.ilike(pattern))
        conditions.append(Entity.description.ilike(pattern))

    if not conditions:
        return []

    sql = text(
        """
        SELECT id, name, entity_type, description
        FROM entities
        WHERE :query ILIKE '%' || name || '%'
           OR name ILIKE :query_pattern
           OR COALESCE(description, '') ILIKE :query_pattern
        LIMIT :limit
        """
    )
    direct_result = await db.execute(
        sql,
        {
            "query": clean_query,
            "query_pattern": f"%{clean_query}%",
            "limit": max(limit * 2, 20),
        },
    )
    direct_matches = direct_result.fetchall()

    result = await db.execute(
        select(Entity).where(or_(*conditions)).limit(max(limit * 3, 30))
    )
    entities = result.scalars().all()
    for row in direct_matches:
        entities.append(
            Entity(
                id=row.id,
                name=row.name,
                entity_type=row.entity_type,
                description=row.description,
            )
        )

    deduped: Dict[int, Entity] = {}
    for entity in entities:
        deduped[entity.id] = entity

    ranked = sorted(
        deduped.values(),
        key=lambda entity: _text_match_score(entity, clean_query, tokens),
        reverse=True,
    )

    matches: List[Dict] = []
    for entity in ranked:
        score = _text_match_score(entity, clean_query, tokens)
        if score <= 0:
            continue
        matches.append(_serialize_entity(entity, similarity=score))
        if len(matches) >= limit:
            break

    return matches


async def _load_entities_by_ids(entity_ids: List[int], db: AsyncSession) -> List[Dict]:
    if not entity_ids:
        return []

    result = await db.execute(select(Entity).where(Entity.id.in_(entity_ids)))
    return [_serialize_entity(entity) for entity in result.scalars().all()]


async def get_kg_for_query(query: str, db: AsyncSession, limit: int = 50) -> Dict:
    """
    Get knowledge graph data relevant to a query.
    1. Try embedding retrieval against the entity table.
    2. Fall back to lexical entity matching when embeddings are unavailable.
    3. Expand to connected relationships.
    4. Return as {nodes: [...], links: [...]} for frontend visualization.
    """
    entities: List[Dict] = []

    try:
        entities = await _find_entities_by_embedding(query, db, limit=min(limit, 20))
    except Exception as exc:
        # Keep the graph tab usable even if the embedding provider is unavailable.
        print(f"[KGService] Embedding lookup failed, falling back to text match: {exc}")

    if not entities:
        entities = await _find_entities_by_text(query, db, limit=min(limit, 20))

    if not entities:
        return {"nodes": [], "links": []}

    seed_entity_ids = [entity["id"] for entity in entities]

    rel_result = await db.execute(
        select(Relationship).where(
            or_(
                Relationship.source_entity_id.in_(seed_entity_ids),
                Relationship.target_entity_id.in_(seed_entity_ids),
            )
        ).limit(max(limit * 3, 30))
    )
    relationships = rel_result.scalars().all()

    related_entity_ids = set(seed_entity_ids)
    for relationship in relationships:
        related_entity_ids.add(relationship.source_entity_id)
        related_entity_ids.add(relationship.target_entity_id)

    extra_entities = await _load_entities_by_ids(
        list(related_entity_ids - set(seed_entity_ids)), db
    )

    entity_map = {entity["id"]: entity for entity in entities}
    for entity in extra_entities:
        entity_map.setdefault(entity["id"], entity)

    nodes = []
    for entity in entity_map.values():
        similarity = entity.get("similarity")
        nodes.append(
            {
                "id": str(entity["id"]),
                "label": entity["name"],
                "type": entity["entity_type"],
                "size": 12 + int(max(similarity or 0, 0) * 8),
                "properties": {
                    "description": entity.get("description") or "",
                    "similarity": (
                        round(float(similarity), 3) if similarity is not None else None
                    ),
                },
            }
        )

    links = []
    for relationship in relationships:
        if (
            relationship.source_entity_id in entity_map
            and relationship.target_entity_id in entity_map
        ):
            links.append(
                {
                    "source": str(relationship.source_entity_id),
                    "target": str(relationship.target_entity_id),
                    "label": relationship.relation_type,
                    "weight": relationship.weight or 0.5,
                }
            )

    return {"nodes": nodes, "links": links}


async def get_kg_visualization(db: AsyncSession, limit: int = 100) -> Dict:
    """Get full KG visualization data (for knowledge graph tab)."""
    sql = text(
        """
        SELECT e.id, e.name, e.entity_type, e.description,
               COUNT(r.id) as rel_count
        FROM entities e
        LEFT JOIN relationships r ON e.id = r.source_entity_id
        GROUP BY e.id, e.name, e.entity_type, e.description
        ORDER BY rel_count DESC
        LIMIT :limit
        """
    )
    result = await db.execute(sql, {"limit": limit})
    entities = result.fetchall()

    if not entities:
        return {"nodes": [], "links": []}

    entity_ids = [entity.id for entity in entities]
    entity_map = {entity.id: entity for entity in entities}

    rel_result = await db.execute(
        select(Relationship).where(
            Relationship.source_entity_id.in_(entity_ids)
        ).limit(200)
    )
    relationships = rel_result.scalars().all()

    nodes = [
        {
            "id": str(entity.id),
            "label": entity.name,
            "type": entity.entity_type,
            "size": 10 + min(entity.rel_count, 20),
        }
        for entity in entities
    ]
    links = [
        {
            "source": str(relationship.source_entity_id),
            "target": str(relationship.target_entity_id),
            "label": relationship.relation_type,
            "weight": relationship.weight or 0.5,
        }
        for relationship in relationships
        if (
            relationship.source_entity_id in entity_map
            and relationship.target_entity_id in entity_map
        )
    ]

    return {"nodes": nodes, "links": links}


async def graph_reasoning(
    reasoning_type: str,
    entity_a: str = None,
    entity_b: str = None,
    max_depth: int = 2,
    db: AsyncSession = None,
) -> Dict:
    """Perform graph reasoning operations."""
    try:
        if reasoning_type == "shortest_path" and entity_a and entity_b:
            path = clinical_graph_manager.find_shortest_path(entity_a, entity_b)
            return {"type": "shortest_path", "path": path}
        if reasoning_type == "entity_neighbors" and entity_a:
            neighbors = clinical_graph_manager.get_entity_relationships(entity_a, max_depth)
            return {"type": "entity_neighbors", "data": neighbors}
        return {"type": reasoning_type, "data": {}}
    except Exception as exc:
        return {"type": reasoning_type, "error": str(exc)}
