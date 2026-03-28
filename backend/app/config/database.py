"""数据库连接管理 - PostgreSQL (asyncpg) + Neo4j"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from neo4j import GraphDatabase
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from app.config.settings import settings


# ===== PostgreSQL =====

engine = create_async_engine(
    settings.postgres.async_url,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入：获取数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_postgres():
    """初始化 PostgreSQL：创建所有表"""
    async with engine.begin() as conn:
        # 先创建 pgvector 扩展
        await conn.execute(
            __import__("sqlalchemy").text("CREATE EXTENSION IF NOT EXISTS vector")
        )
        await conn.run_sync(Base.metadata.create_all)


# ===== Neo4j =====

class Neo4jManager:
    """Neo4j 连接管理器（单例）"""

    _instance = None
    _driver = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def driver(self):
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                settings.neo4j.uri,
                auth=(settings.neo4j.username, settings.neo4j.password),
            )
        return self._driver

    def get_session(self):
        return self.driver.session()

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    def execute_query(self, query: str, parameters: dict = None):
        """执行 Cypher 查询"""
        with self.get_session() as session:
            result = session.run(query, parameters or {})
            return [record.data() for record in result]


neo4j_manager = Neo4jManager()
