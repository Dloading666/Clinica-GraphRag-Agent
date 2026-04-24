"""Application settings loaded from environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings


class LLMSettings(BaseSettings):
    """LLM provider configuration."""
    api_key: str = Field(default="sk-xxx", alias="LLM_API_KEY")
    base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="LLM_BASE_URL",
    )
    model: str = Field(default="qwen-turbo", alias="LLM_MODEL")
    timeout_seconds: int = Field(default=45, alias="LLM_TIMEOUT_SECONDS")
    stream_timeout_seconds: int = Field(
        default=90,
        alias="LLM_STREAM_TIMEOUT_SECONDS",
    )
    disable_thinking: bool = Field(default=True, alias="LLM_DISABLE_THINKING")

    model_config = {"env_file": ".env", "extra": "ignore"}


class FallbackLLMSettings(BaseSettings):
    """Optional fallback LLM used when the primary provider is temporarily unavailable."""
    enabled: bool = Field(default=False, alias="LLM_FALLBACK_ENABLED")
    api_key: str = Field(default="", alias="LLM_FALLBACK_API_KEY")
    base_url: str = Field(default="", alias="LLM_FALLBACK_BASE_URL")
    model: str = Field(default="", alias="LLM_FALLBACK_MODEL")

    model_config = {"env_file": ".env", "extra": "ignore"}


class EmbeddingSettings(BaseSettings):
    """Embedding provider configuration."""
    api_key: str = Field(default="sk-xxx", alias="EMBEDDING_API_KEY")
    base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="EMBEDDING_BASE_URL",
    )
    model: str = Field(default="text-embedding-v2", alias="EMBEDDING_MODEL")
    dimension: int = Field(default=1536, alias="EMBEDDING_DIMENSION")

    model_config = {"env_file": ".env", "extra": "ignore"}


class PostgresSettings(BaseSettings):
    """PostgreSQL database configuration."""
    host: str = Field(default="localhost", alias="POSTGRES_HOST")
    port: int = Field(default=5432, alias="POSTGRES_PORT")
    db: str = Field(default="clinical_qa", alias="POSTGRES_DB")
    user: str = Field(default="postgres", alias="POSTGRES_USER")
    password: str = Field(default="clinical_qa_2024", alias="POSTGRES_PASSWORD")

    @property
    def async_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}@"
            f"{self.host}:{self.port}/{self.db}"
        )

    @property
    def sync_url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"

    model_config = {"env_file": ".env", "extra": "ignore"}


class Neo4jSettings(BaseSettings):
    """Neo4j graph database configuration."""
    uri: str = Field(default="neo4j://localhost:7687", alias="NEO4J_URI")
    username: str = Field(default="neo4j", alias="NEO4J_USERNAME")
    password: str = Field(default="clinical_neo4j_2024", alias="NEO4J_PASSWORD")

    model_config = {"env_file": ".env", "extra": "ignore"}


class ChunkSettings(BaseSettings):
    """Configuration section."""
    chunk_size: int = Field(default=800, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=200, alias="CHUNK_OVERLAP")

    model_config = {"env_file": ".env", "extra": "ignore"}


class SearchSettings(BaseSettings):
    """Configuration section."""
    top_k: int = Field(default=15, alias="SEARCH_TOP_K")
    similarity_threshold: float = Field(default=0.82, alias="SIMILARITY_THRESHOLD")
    query_expansion_enabled: bool = Field(default=True, alias="QUERY_EXPANSION_ENABLED")
    query_expansion_mode: str = Field(default="synonym", alias="QUERY_EXPANSION_MODE")
    query_expansion_max_terms: int = Field(default=6, alias="QUERY_EXPANSION_MAX_TERMS")
    query_expansion_apply_to: str = Field(
        default="naive,hybrid,graph,fusion,deep_research",
        alias="QUERY_EXPANSION_APPLY_TO",
    )
    local_top_chunks: int = Field(default=3, alias="LOCAL_SEARCH_TOP_CHUNKS")
    local_top_communities: int = Field(default=3, alias="LOCAL_SEARCH_TOP_COMMUNITIES")
    local_top_inside_rels: int = Field(default=10, alias="LOCAL_SEARCH_TOP_INSIDE_RELS")
    local_top_outside_rels: int = Field(default=10, alias="LOCAL_SEARCH_TOP_OUTSIDE_RELS")
    local_top_entities: int = Field(default=10, alias="LOCAL_SEARCH_TOP_ENTITIES")
    hybrid_entity_limit: int = Field(default=15, alias="HYBRID_SEARCH_ENTITY_LIMIT")
    web_search_enabled: bool = Field(default=True, alias="WEB_SEARCH_ENABLED")
    web_search_top_k: int = Field(default=5, alias="WEB_SEARCH_TOP_K")
    web_search_timeout_seconds: int = Field(
        default=12,
        alias="WEB_SEARCH_TIMEOUT_SECONDS",
    )

    model_config = {"env_file": ".env", "extra": "ignore"}


class ServerSettings(BaseSettings):
    """Server configuration."""
    host: str = Field(default="0.0.0.0", alias="SERVER_HOST")
    port: int = Field(default=8000, alias="SERVER_PORT")
    workers: int = Field(default=2, alias="SERVER_WORKERS")

    model_config = {"env_file": ".env", "extra": "ignore"}


class PerformanceSettings(BaseSettings):
    """Performance configuration."""
    max_workers: int = Field(default=4, alias="MAX_WORKERS")
    batch_size: int = Field(default=100, alias="BATCH_SIZE")
    embedding_batch_size: int = Field(default=64, alias="EMBEDDING_BATCH_SIZE")

    model_config = {"env_file": ".env", "extra": "ignore"}


class ChatSettings(BaseSettings):
    """Chat streaming and latency tuning settings."""
    stream_pacing_ms: int = Field(default=0, alias="CHAT_STREAM_PACING_MS")
    defer_kg: bool = Field(default=True, alias="CHAT_DEFER_KG")
    fast_start_enabled: bool = Field(default=False, alias="CHAT_FAST_START_ENABLED")
    max_stall_seconds: int = Field(default=90, alias="CHAT_MAX_STALL_SECONDS")
    context_max_turns: int = Field(default=4, alias="CHAT_CONTEXT_MAX_TURNS")
    context_message_char_limit: int = Field(
        default=1200,
        alias="CHAT_CONTEXT_MESSAGE_CHAR_LIMIT",
    )
    context_topic_reset_enabled: bool = Field(
        default=True,
        alias="CHAT_CONTEXT_TOPIC_RESET_ENABLED",
    )

    model_config = {"env_file": ".env", "extra": "ignore"}


class FrontendSettings(BaseSettings):
    """Frontend runtime flags exposed through /api/chat/config."""
    typing_effect: bool = Field(default=False, alias="FRONTEND_TYPING_EFFECT")

    model_config = {"env_file": ".env", "extra": "ignore"}


class SecuritySettings(BaseSettings):
    """Lightweight anti-abuse settings for public demos."""

    proxy_shared_token: str = Field(default="", alias="PROXY_SHARED_TOKEN")
    admin_api_key: str = Field(default="", alias="ADMIN_API_KEY")
    allowed_origins_raw: str = Field(
        default=(
            "https://clinirag.top,https://www.clinirag.top,"
            "http://localhost:3000,http://127.0.0.1:3000,"
            "http://localhost:3002,http://127.0.0.1:3002"
        ),
        alias="ALLOWED_ORIGINS",
    )
    allowed_hosts_raw: str = Field(
        default="clinirag.top,www.clinirag.top,localhost,127.0.0.1",
        alias="ALLOWED_HOSTS",
    )
    public_session_access: bool = Field(default=False, alias="PUBLIC_SESSION_ACCESS")
    allow_public_debug: bool = Field(default=False, alias="ALLOW_PUBLIC_DEBUG")
    chat_rate_limit_count: int = Field(default=12, alias="CHAT_RATE_LIMIT_COUNT")
    chat_rate_limit_window_seconds: int = Field(
        default=300,
        alias="CHAT_RATE_LIMIT_WINDOW_SECONDS",
    )
    chat_max_concurrent_per_ip: int = Field(
        default=2,
        alias="CHAT_MAX_CONCURRENT_PER_IP",
    )
    chat_max_message_chars: int = Field(default=4000, alias="CHAT_MAX_MESSAGE_CHARS")
    chat_max_top_k: int = Field(default=20, alias="CHAT_MAX_TOP_K")
    max_reasoning_depth: int = Field(default=3, alias="MAX_REASONING_DEPTH")
    agent_cache_size: int = Field(default=64, alias="AGENT_CACHE_SIZE")
    agent_ttl_seconds: int = Field(default=3600, alias="AGENT_TTL_SECONDS")

    model_config = {"env_file": ".env", "extra": "ignore"}

    @staticmethod
    def _split_csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def allowed_origins(self) -> list[str]:
        return self._split_csv(self.allowed_origins_raw)

    @property
    def allowed_hosts(self) -> list[str]:
        return self._split_csv(self.allowed_hosts_raw)


class Settings:
    """Configuration section."""

    def __init__(self):
        self.llm = LLMSettings()
        self.llm_fallback = FallbackLLMSettings()
        self.embedding = EmbeddingSettings()
        self.postgres = PostgresSettings()
        self.neo4j = Neo4jSettings()
        self.chunk = ChunkSettings()
        self.search = SearchSettings()
        self.server = ServerSettings()
        self.performance = PerformanceSettings()
        self.chat = ChatSettings()
        self.frontend = FrontendSettings()
        self.security = SecuritySettings()

    ENTITY_TYPES = [
        "疾病",
        "症状",
        "药物",
        "治疗方法",
        "中药方剂",
        "经络穴位",
        "病理机制",
        "药理作用",
        "毒副作用",
        "适应症",
    ]

    RELATION_TYPES = [
        "治疗",
        "引起",
        "属于",
        "配伍",
        "禁忌",
        "作用于",
        "表现为",
        "包含",
        "对应",
        "拮抗",
    ]

    EXAMPLE_QUESTIONS = [
        "头痛应该怎么进行治疗？",
        "心脏不舒服加上高血压，怎么治疗？",
        "口服药效果不稳定，和首过效应有关吗？",
        "全身一热就全身发痒，这是什么原因？",
    ]


settings = Settings()
