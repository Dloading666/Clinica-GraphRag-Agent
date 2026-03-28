"""SQLAlchemy ORM 模型 - PostgreSQL 表结构"""

from sqlalchemy import (
    Column, Integer, String, Text, Float, DateTime, Boolean, ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.config.database import Base
from app.config.settings import settings


class Document(Base):
    """文档表"""
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), unique=True, nullable=False)
    file_type = Column(String(50))
    file_path = Column(Text)
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Chunk(Base):
    """文本块 + 向量嵌入"""
    __tablename__ = "chunks"

    id = Column(String(64), primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer)
    chapter = Column(String(255))
    section = Column(String(255))
    embedding = Column(Vector(settings.embedding.dimension))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_chunks_embedding", "embedding",
              postgresql_using="hnsw",
              postgresql_with={"m": 16, "ef_construction": 64},
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )


class Entity(Base):
    """实体表"""
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    entity_type = Column(String(100), nullable=False)
    description = Column(Text)
    embedding = Column(Vector(settings.embedding.dimension))
    properties = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_entities_name", "name"),
        Index("idx_entities_type", "entity_type"),
        Index("idx_entities_embedding", "embedding",
              postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        # 唯一约束
        Index("uq_entity_name_type", "name", "entity_type", unique=True),
    )


class Relationship(Base):
    """关系表"""
    __tablename__ = "relationships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    target_entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    relation_type = Column(String(100), nullable=False)
    description = Column(Text)
    weight = Column(Float, default=0.5)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_rel_source", "source_entity_id"),
        Index("idx_rel_target", "target_entity_id"),
    )


class EntityChunkMention(Base):
    """实体-文本块关联"""
    __tablename__ = "entity_chunk_mentions"

    entity_id = Column(Integer, ForeignKey("entities.id"), primary_key=True)
    chunk_id = Column(String(64), ForeignKey("chunks.id"), primary_key=True)


class Community(Base):
    """社区表"""
    __tablename__ = "communities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    community_id = Column(String(50), unique=True, nullable=False)
    level = Column(Integer, default=0)
    summary = Column(Text)
    community_rank = Column(Float)
    weight = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EntityCommunity(Base):
    """实体-社区归属"""
    __tablename__ = "entity_community"

    entity_id = Column(Integer, ForeignKey("entities.id"), primary_key=True)
    community_id = Column(Integer, ForeignKey("communities.id"), primary_key=True)


class ChatSession(Base):
    """对话会话"""
    __tablename__ = "chat_sessions"

    id = Column(String(64), primary_key=True)
    title = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ChatMessage(Base):
    """对话消息"""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    agent_type = Column(String(50))
    execution_log = Column(JSONB)
    kg_data = Column(JSONB)
    references = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_messages_session", "session_id"),
    )
