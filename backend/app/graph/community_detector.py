"""社区检测：使用 Neo4j GDS Leiden 算法，并用 LLM 生成社区摘要"""
import asyncio
from typing import List, Dict

from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.llm_factory import get_llm
from app.config.prompts.clinical_prompts import COMMUNITY_SUMMARY_PROMPT
from app.graph.neo4j_manager import clinical_graph_manager
from app.config.database import neo4j_manager
from app.models.db_models import Community, EntityCommunity, Entity


class CommunityDetector:
    """社区检测器：Leiden 算法 + LLM 摘要生成"""

    def __init__(self):
        self.llm = get_llm()

    # ──────────────────────────────────────────────
    # 主流程
    # ──────────────────────────────────────────────

    async def run_detection_and_summarize(self, db: AsyncSession) -> int:
        """
        完整流程：
        1. 在 Neo4j GDS 中运行 Leiden 社区检测
        2. 遍历每个社区，获取成员实体和关系
        3. LLM 生成社区摘要
        4. 存储到 PostgreSQL communities 表和 entity_community 表
        5. 将摘要写回 Neo4j __Community__ 节点
        返回创建的社区数量。
        """
        # 1. 运行社区检测
        community_count = await asyncio.to_thread(
            clinical_graph_manager.run_leiden_community_detection
        )
        if community_count == 0:
            print("[CommunityDetector] 社区检测未返回结果，跳过摘要生成")
            return 0

        print(f"[CommunityDetector] 检测到 {community_count} 个社区，开始生成摘要...")

        # 2. 获取所有社区 ID
        community_ids = await asyncio.to_thread(
            clinical_graph_manager.get_all_community_ids
        )

        created_count = 0
        for community_id in community_ids:
            try:
                await self._process_community(community_id, db)
                created_count += 1
            except Exception as e:
                print(f"[CommunityDetector] 处理社区 {community_id} 失败: {e}")

        await db.commit()
        print(f"[CommunityDetector] 完成，共处理 {created_count} 个社区")
        return created_count

    # ──────────────────────────────────────────────
    # 单社区处理
    # ──────────────────────────────────────────────

    async def _process_community(self, community_id: int, db: AsyncSession) -> None:
        """处理单个社区：获取成员 → 生成摘要 → 存储"""
        # 获取社区成员实体
        members = await asyncio.to_thread(
            clinical_graph_manager.get_community_members, community_id
        )
        if not members:
            return

        # 获取社区内部关系
        relationships = await asyncio.to_thread(
            clinical_graph_manager.get_community_relationships, community_id
        )

        # 生成摘要（同步 LLM 调用移到线程）
        summary = await asyncio.to_thread(
            self._generate_community_summary, members, relationships
        )

        # 计算社区权重（成员数量）
        rank = float(len(members))
        community_id_str = str(community_id)

        # 存储到 PostgreSQL
        pg_community = await self._upsert_community_pg(
            db, community_id_str, summary, level=0, rank=rank
        )

        # 建立实体-社区关联
        if pg_community:
            for member in members:
                pg_id = member.get("pg_id")
                if pg_id:
                    await self._upsert_entity_community(db, int(pg_id), pg_community.id)

        # 写回 Neo4j
        await asyncio.to_thread(
            clinical_graph_manager.write_community_summary,
            community_id_str, summary, 0, rank
        )

    # ──────────────────────────────────────────────
    # LLM 摘要生成
    # ──────────────────────────────────────────────

    def _generate_community_summary(
        self, entities: List[Dict], relationships: List[Dict]
    ) -> str:
        """调用 LLM 为社区生成摘要"""
        try:
            prompt = ChatPromptTemplate.from_messages([
                ("human", COMMUNITY_SUMMARY_PROMPT)
            ])
            chain = prompt | self.llm | StrOutputParser()
            return chain.invoke({
                "entities": str(entities),
                "relationships": str(relationships),
            })
        except Exception as e:
            print(f"[CommunityDetector] 摘要生成失败: {e}")
            # 降级：简单拼接实体名称
            names = [e.get("name", "") for e in entities]
            return f"该社区包含以下医学实体：{'、'.join(names[:10])}"

    # ──────────────────────────────────────────────
    # PostgreSQL 操作
    # ──────────────────────────────────────────────

    async def _upsert_community_pg(
        self,
        db: AsyncSession,
        community_id: str,
        summary: str,
        level: int,
        rank: float,
    ) -> Community:
        """在 PostgreSQL 中插入或更新社区记录"""
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
        else:
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
        """建立实体-社区归属关联"""
        result = await db.execute(
            select(EntityCommunity).where(
                EntityCommunity.entity_id == entity_id,
                EntityCommunity.community_id == community_db_id,
            )
        )
        if not result.scalar_one_or_none():
            ec = EntityCommunity(entity_id=entity_id, community_id=community_db_id)
            db.add(ec)
