"""应用配置 - 从环境变量加载所有配置项"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class LLMSettings(BaseSettings):
    """LLM 模型配置（独立 API Key）"""
    api_key: str = Field(default="sk-xxx", alias="LLM_API_KEY")
    base_url: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1", alias="LLM_BASE_URL")
    model: str = Field(default="qwen-turbo", alias="LLM_MODEL")

    model_config = {"env_file": ".env", "extra": "ignore"}


class EmbeddingSettings(BaseSettings):
    """Embedding 模型配置（独立 API Key）"""
    api_key: str = Field(default="sk-xxx", alias="EMBEDDING_API_KEY")
    base_url: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1", alias="EMBEDDING_BASE_URL")
    model: str = Field(default="text-embedding-v2", alias="EMBEDDING_MODEL")
    dimension: int = Field(default=1536, alias="EMBEDDING_DIMENSION")

    model_config = {"env_file": ".env", "extra": "ignore"}


class PostgresSettings(BaseSettings):
    """PostgreSQL 数据库配置"""
    host: str = Field(default="localhost", alias="POSTGRES_HOST")
    port: int = Field(default=5432, alias="POSTGRES_PORT")
    db: str = Field(default="clinical_qa", alias="POSTGRES_DB")
    user: str = Field(default="postgres", alias="POSTGRES_USER")
    password: str = Field(default="clinical_qa_2024", alias="POSTGRES_PASSWORD")

    @property
    def async_url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"

    @property
    def sync_url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"

    model_config = {"env_file": ".env", "extra": "ignore"}


class Neo4jSettings(BaseSettings):
    """Neo4j 图数据库配置"""
    uri: str = Field(default="neo4j://localhost:7687", alias="NEO4J_URI")
    username: str = Field(default="neo4j", alias="NEO4J_USERNAME")
    password: str = Field(default="clinical_neo4j_2024", alias="NEO4J_PASSWORD")

    model_config = {"env_file": ".env", "extra": "ignore"}


class ChunkSettings(BaseSettings):
    """文本分块配置"""
    chunk_size: int = Field(default=800, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=200, alias="CHUNK_OVERLAP")

    model_config = {"env_file": ".env", "extra": "ignore"}


class SearchSettings(BaseSettings):
    """搜索参数配置"""
    top_k: int = Field(default=15, alias="SEARCH_TOP_K")
    similarity_threshold: float = Field(default=0.82, alias="SIMILARITY_THRESHOLD")
    local_top_chunks: int = Field(default=3, alias="LOCAL_SEARCH_TOP_CHUNKS")
    local_top_communities: int = Field(default=3, alias="LOCAL_SEARCH_TOP_COMMUNITIES")
    local_top_inside_rels: int = Field(default=10, alias="LOCAL_SEARCH_TOP_INSIDE_RELS")
    local_top_outside_rels: int = Field(default=10, alias="LOCAL_SEARCH_TOP_OUTSIDE_RELS")
    local_top_entities: int = Field(default=10, alias="LOCAL_SEARCH_TOP_ENTITIES")
    hybrid_entity_limit: int = Field(default=15, alias="HYBRID_SEARCH_ENTITY_LIMIT")

    model_config = {"env_file": ".env", "extra": "ignore"}


class ServerSettings(BaseSettings):
    """服务器配置"""
    host: str = Field(default="0.0.0.0", alias="SERVER_HOST")
    port: int = Field(default=8000, alias="SERVER_PORT")
    workers: int = Field(default=2, alias="SERVER_WORKERS")

    model_config = {"env_file": ".env", "extra": "ignore"}


class PerformanceSettings(BaseSettings):
    """性能配置"""
    max_workers: int = Field(default=4, alias="MAX_WORKERS")
    batch_size: int = Field(default=100, alias="BATCH_SIZE")
    embedding_batch_size: int = Field(default=64, alias="EMBEDDING_BATCH_SIZE")

    model_config = {"env_file": ".env", "extra": "ignore"}


class Settings:
    """全局配置聚合"""

    def __init__(self):
        self.llm = LLMSettings()
        self.embedding = EmbeddingSettings()
        self.postgres = PostgresSettings()
        self.neo4j = Neo4jSettings()
        self.chunk = ChunkSettings()
        self.search = SearchSettings()
        self.server = ServerSettings()
        self.performance = PerformanceSettings()

    # 临床领域实体类型
    ENTITY_TYPES = [
        "疾病", "症状", "药物", "治疗方法", "中药方剂",
        "经络穴位", "病理机制", "药理作用", "毒副作用", "适应症"
    ]

    # 临床领域关系类型
    RELATION_TYPES = [
        "治疗", "引起", "属于", "配伍", "禁忌",
        "作用于", "表现为", "包含", "对应", "拮抗"
    ]

    # 示例问题
    EXAMPLE_QUESTIONS = [
        "从中医基础理论看，气滞、气逆、气陷分别有哪些辨证要点？",
        "病理学中，可逆性损伤、坏死和凋亡的核心区别是什么？",
        "药理学里的首过效应会怎样影响口服药物的生物利用度？",
        "抗菌药物的 MIC、最低杀菌浓度和耐药性在临床选药中应如何理解？",
    ]


# 单例
settings = Settings()
