"""基于 LLM 的实体与关系抽取器"""
import re
import asyncio
import concurrent.futures
from typing import List, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
)

from app.models.llm_factory import get_llm, get_embeddings
from app.models.db_models import Entity, Relationship, EntityChunkMention
from app.config.prompts.clinical_prompts import (
    ENTITY_EXTRACTION_SYSTEM_PROMPT,
    ENTITY_EXTRACTION_HUMAN_PROMPT,
)
from app.config.settings import settings
from app.graph.neo4j_manager import clinical_graph_manager


class EntityRelationExtractor:
    """从临床文本块中抽取实体和关系，同步写入 PostgreSQL 和 Neo4j"""

    def __init__(self):
        self.llm = get_llm()
        self.embeddings = get_embeddings()
        self.tuple_delimiter = " : "
        self.record_delimiter = "\n"
        self.completion_delimiter = "\n\n"

        # 构建 LangChain 提示链
        system_prompt = SystemMessagePromptTemplate.from_template(
            ENTITY_EXTRACTION_SYSTEM_PROMPT
        )
        human_prompt = HumanMessagePromptTemplate.from_template(
            ENTITY_EXTRACTION_HUMAN_PROMPT
        )
        prompt = ChatPromptTemplate.from_messages(
            [system_prompt, MessagesPlaceholder("chat_history"), human_prompt]
        )
        self.chain = prompt | self.llm

    # ──────────────────────────────────────────────
    # LLM 抽取
    # ──────────────────────────────────────────────

    def extract_from_text(self, text: str) -> str:
        """调用 LLM 从文本中抽取实体/关系，返回原始输出"""
        try:
            result = self.chain.invoke({
                "entity_types": "、".join(settings.ENTITY_TYPES),
                "relationship_types": "、".join(settings.RELATION_TYPES),
                "tuple_delimiter": self.tuple_delimiter,
                "record_delimiter": self.record_delimiter,
                "completion_delimiter": self.completion_delimiter,
                "input_text": text,
                "chat_history": [],
            })
            return result.content if hasattr(result, "content") else str(result)
        except Exception as e:
            print(f"[EntityExtractor] LLM 抽取失败: {e}")
            return ""

    # ──────────────────────────────────────────────
    # 解析
    # ──────────────────────────────────────────────

    def parse_entities(self, raw_output: str) -> List[Dict]:
        """
        解析 LLM 输出中的实体记录。
        格式：("entity" : "name" : "type" : "description")
        """
        entities = []
        # 匹配括号内以 "entity" 开头的记录（大小写不敏感）
        pattern = re.compile(
            r'\(\s*["\']?entity["\']?\s*:\s*["\']?(.+?)["\']?\s*:\s*["\']?(.+?)["\']?\s*:\s*["\']?(.+?)["\']?\s*\)',
            re.IGNORECASE | re.DOTALL,
        )
        for m in pattern.finditer(raw_output):
            name = m.group(1).strip().strip('"\'')
            etype = m.group(2).strip().strip('"\'')
            desc = m.group(3).strip().strip('"\'')
            if name and etype:
                entities.append({"name": name, "type": etype, "description": desc})
        return entities

    def parse_relationships(self, raw_output: str) -> List[Dict]:
        """
        解析 LLM 输出中的关系记录。
        格式：("relationship" : "source" : "target" : "type" : "description" : weight)
        """
        relationships = []
        pattern = re.compile(
            r'\(\s*["\']?relationship["\']?\s*:\s*["\']?(.+?)["\']?\s*:\s*["\']?(.+?)["\']?\s*:\s*["\']?(.+?)["\']?\s*:\s*["\']?(.+?)["\']?\s*:\s*([\d.]+)\s*\)',
            re.IGNORECASE | re.DOTALL,
        )
        for m in pattern.finditer(raw_output):
            source = m.group(1).strip().strip('"\'')
            target = m.group(2).strip().strip('"\'')
            rel_type = m.group(3).strip().strip('"\'')
            desc = m.group(4).strip().strip('"\'')
            try:
                weight = float(m.group(5))
            except ValueError:
                weight = 0.5
            if source and target and rel_type:
                relationships.append({
                    "source": source,
                    "target": target,
                    "type": rel_type,
                    "description": desc,
                    "weight": weight,
                })
        return relationships

    # ──────────────────────────────────────────────
    # 批量异步处理
    # ──────────────────────────────────────────────

    async def process_chunks_async(
        self,
        chunks: List[Dict],
        db: AsyncSession,
    ) -> None:
        """
        并发处理多个文本块（每块调用一次 LLM）。
        chunks 格式：[{"id": str, "content": str, "document_id": int}, ...]
        使用 ThreadPoolExecutor 并发调用同步 LLM API。
        """
        max_workers = min(settings.performance.max_workers, len(chunks))
        loop = asyncio.get_event_loop()

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 并发调用 LLM 抽取（同步调用移到线程池）
            futures = {
                executor.submit(self.extract_from_text, chunk["content"]): chunk
                for chunk in chunks
            }
            extract_results = {}
            for future in concurrent.futures.as_completed(futures):
                chunk = futures[future]
                try:
                    raw = future.result()
                    extract_results[chunk["id"]] = raw
                except Exception as e:
                    print(f"[EntityExtractor] 块 {chunk['id']} 抽取失败: {e}")
                    extract_results[chunk["id"]] = ""

        # 逐块存储（异步 DB 操作必须在主线程）
        for chunk in chunks:
            raw = extract_results.get(chunk["id"], "")
            if raw:
                await self._process_single_chunk(chunk["id"], chunk["content"], raw, db)

    async def _process_single_chunk(
        self,
        chunk_id: str,
        content: str,
        raw_output: str,
        db: AsyncSession,
    ) -> None:
        """处理单个块：解析 → 嵌入 → 存储到 PG + Neo4j"""
        entities = self.parse_entities(raw_output)
        relationships = self.parse_relationships(raw_output)

        if not entities:
            return

        # 嵌入实体描述
        descriptions = [e["description"] or e["name"] for e in entities]
        try:
            embeddings = await asyncio.to_thread(
                self.embeddings.embed_documents, descriptions
            )
        except Exception as e:
            print(f"[EntityExtractor] 实体嵌入失败: {e}")
            dim = settings.embedding.dimension
            embeddings = [[0.0] * dim for _ in entities]

        # 存储实体到 PostgreSQL
        pg_entity_map: Dict[str, int] = {}  # name → pg id
        for entity_data, emb in zip(entities, embeddings):
            pg_id = await self._upsert_entity_pg(db, entity_data, emb)
            if pg_id:
                pg_entity_map[entity_data["name"]] = pg_id
                # 同步写入 Neo4j
                clinical_graph_manager.upsert_entity(
                    name=entity_data["name"],
                    entity_type=entity_data["type"],
                    description=entity_data["description"],
                    pg_id=pg_id,
                )
                # 创建 EntityChunkMention
                await self._upsert_mention(db, pg_id, chunk_id)

        # 存储关系
        for rel in relationships:
            source_id = pg_entity_map.get(rel["source"])
            target_id = pg_entity_map.get(rel["target"])
            if source_id and target_id:
                await self._upsert_relationship_pg(db, rel, source_id, target_id)
                clinical_graph_manager.upsert_relationship(
                    source_name=rel["source"],
                    target_name=rel["target"],
                    rel_type=rel["type"],
                    description=rel["description"],
                    weight=rel["weight"],
                )

        await db.flush()

    # ──────────────────────────────────────────────
    # PG 数据库操作
    # ──────────────────────────────────────────────

    async def _upsert_entity_pg(
        self,
        db: AsyncSession,
        entity_data: Dict,
        embedding: List[float],
    ) -> Optional[int]:
        """在 PostgreSQL entities 表中插入或更新实体，返回 id"""
        try:
            result = await db.execute(
                select(Entity).where(
                    and_(
                        Entity.name == entity_data["name"],
                        Entity.entity_type == entity_data["type"],
                    )
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.description = entity_data["description"]
                existing.embedding = embedding
                await db.flush()
                return existing.id
            else:
                entity = Entity(
                    name=entity_data["name"],
                    entity_type=entity_data["type"],
                    description=entity_data["description"],
                    embedding=embedding,
                )
                db.add(entity)
                await db.flush()
                return entity.id
        except Exception as e:
            print(f"[EntityExtractor] _upsert_entity_pg 失败 ({entity_data['name']}): {e}")
            return None

    async def _upsert_relationship_pg(
        self,
        db: AsyncSession,
        rel: Dict,
        source_id: int,
        target_id: int,
    ) -> None:
        """在 PostgreSQL relationships 表中插入或更新关系"""
        try:
            result = await db.execute(
                select(Relationship).where(
                    and_(
                        Relationship.source_entity_id == source_id,
                        Relationship.target_entity_id == target_id,
                        Relationship.relation_type == rel["type"],
                    )
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.description = rel["description"]
                existing.weight = rel["weight"]
            else:
                relationship = Relationship(
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                    relation_type=rel["type"],
                    description=rel["description"],
                    weight=rel["weight"],
                )
                db.add(relationship)
        except Exception as e:
            print(f"[EntityExtractor] _upsert_relationship_pg 失败: {e}")

    async def _upsert_mention(
        self,
        db: AsyncSession,
        entity_id: int,
        chunk_id: str,
    ) -> None:
        """创建实体-文本块关联记录"""
        try:
            result = await db.execute(
                select(EntityChunkMention).where(
                    and_(
                        EntityChunkMention.entity_id == entity_id,
                        EntityChunkMention.chunk_id == chunk_id,
                    )
                )
            )
            if not result.scalar_one_or_none():
                mention = EntityChunkMention(entity_id=entity_id, chunk_id=chunk_id)
                db.add(mention)
        except Exception as e:
            print(f"[EntityExtractor] _upsert_mention 失败: {e}")
