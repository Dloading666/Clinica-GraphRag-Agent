"""Community detection and summary generation."""

import asyncio
from typing import Dict, List

from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.prompts.clinical_prompts import COMMUNITY_SUMMARY_PROMPT
from app.graph.neo4j_manager import clinical_graph_manager
from app.models.db_models import Community, Entity, EntityCommunity
from app.models.llm_factory import get_llm


class CommunityDetector:
    """Run Leiden community detection and persist community summaries."""

    def __init__(self):
        self.llm = get_llm()

    async def run_detection_and_summarize(self, db: AsyncSession) -> int:
        """Detect communities in Neo4j, summarize them, and persist results."""
        community_count = await asyncio.to_thread(
            clinical_graph_manager.run_leiden_community_detection
        )
        if community_count == 0:
            print("[CommunityDetector] No communities returned, skipping summary generation")
            return 0

        print(f"[CommunityDetector] Detected {community_count} communities, generating summaries...")

        community_ids = await asyncio.to_thread(
            clinical_graph_manager.get_all_community_ids
        )
        total_communities = len(community_ids)

        created_count = 0
        for index, community_id in enumerate(community_ids, start=1):
            try:
                processed = await self._process_community(community_id, db)
                if not processed:
                    continue

                await db.commit()
                created_count += 1

                if index == total_communities or index % 25 == 0:
                    print(
                        "[CommunityDetector] Progress "
                        f"{index}/{total_communities}, committed {created_count} communities"
                    )
            except Exception as exc:
                await db.rollback()
                print(f"[CommunityDetector] Failed to process community {community_id}: {exc}")

        print(f"[CommunityDetector] Completed, processed {created_count} communities")
        return created_count

    async def _process_community(self, community_id: int, db: AsyncSession) -> bool:
        """Process a single community end to end."""
        members = await asyncio.to_thread(
            clinical_graph_manager.get_community_members,
            community_id,
        )
        if not members:
            return False

        relationships = await asyncio.to_thread(
            clinical_graph_manager.get_community_relationships,
            community_id,
        )
        summary = await asyncio.to_thread(
            self._generate_community_summary,
            members,
            relationships,
        )

        rank = float(len(members))
        community_id_str = str(community_id)

        pg_community = await self._upsert_community_pg(
            db,
            community_id_str,
            summary,
            level=0,
            rank=rank,
        )

        if pg_community:
            for member in members:
                pg_id = member.get("pg_id")
                if pg_id:
                    await self._upsert_entity_community(db, int(pg_id), pg_community.id)

        await asyncio.to_thread(
            clinical_graph_manager.write_community_summary,
            community_id_str,
            summary,
            0,
            rank,
        )
        return True

    def _generate_community_summary(
        self,
        entities: List[Dict],
        relationships: List[Dict],
    ) -> str:
        """Generate a community summary with the configured LLM."""
        try:
            prompt = ChatPromptTemplate.from_messages(
                [("human", COMMUNITY_SUMMARY_PROMPT)]
            )
            chain = prompt | self.llm | StrOutputParser()
            return chain.invoke(
                {
                    "entities": str(entities),
                    "relationships": str(relationships),
                }
            )
        except Exception as exc:
            print(f"[CommunityDetector] Summary generation failed: {exc}")
            names = [entity.get("name", "") for entity in entities if entity.get("name")]
            joined = "、".join(names[:10]) if names else "暂无实体信息"
            return f"该社区包含以下医学实体：{joined}"

    async def _upsert_community_pg(
        self,
        db: AsyncSession,
        community_id: str,
        summary: str,
        level: int,
        rank: float,
    ) -> Community:
        """Insert or update a community row in PostgreSQL."""
        result = await db.execute(
            select(Community).where(Community.community_id == community_id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.summary = summary
            existing.community_rank = rank
            existing.level = level
            await db.flush()
            return existing

        community = Community(
            community_id=community_id,
            level=level,
            summary=summary,
            community_rank=rank,
            weight=0,
        )
        db.add(community)
        await db.flush()
        return community

    async def _upsert_entity_community(
        self,
        db: AsyncSession,
        entity_id: int,
        community_db_id: int,
    ) -> None:
        """Create the entity-to-community mapping if the entity still exists."""
        entity = await db.get(Entity, entity_id)
        if entity is None:
            return

        result = await db.execute(
            select(EntityCommunity).where(
                EntityCommunity.entity_id == entity_id,
                EntityCommunity.community_id == community_db_id,
            )
        )
        if result.scalar_one_or_none():
            return

        db.add(EntityCommunity(entity_id=entity_id, community_id=community_db_id))
