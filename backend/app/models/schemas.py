"""Pydantic request and response models."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Model definition."""

    message: str = Field(min_length=1, max_length=8000)
    session_id: Optional[str] = None
    agent_type: Literal[
        "naive_rag",
        "graph_rag",
        "hybrid_rag",
        "fusion_rag",
        "deep_research",
    ] = "naive_rag"
    top_k: int = Field(default=15, ge=1, le=200)
    similarity_threshold: float = Field(default=0.82, ge=0.0, le=1.0)
    debug: bool = False


class ChatResponse(BaseModel):
    """Model definition."""

    answer: str
    session_id: str
    execution_log: Optional[List[Dict[str, Any]]] = None
    kg_data: Optional[Dict[str, Any]] = None
    references: Optional[List[Dict[str, Any]]] = None
    performance: Optional[Dict[str, Any]] = None


class StreamEvent(BaseModel):
    """SSE event payload."""

    event: str
    data: Any


class DocumentInfo(BaseModel):
    """Model definition."""

    id: int
    filename: str
    file_type: Optional[str] = None
    chunk_count: int = 0
    created_at: Optional[datetime] = None


class ChunkInfo(BaseModel):
    """Model definition."""

    id: str
    content: str
    chapter: Optional[str] = None
    section: Optional[str] = None
    similarity: Optional[float] = None
    document_name: Optional[str] = None


class KGNode(BaseModel):
    """Model definition."""

    id: str
    label: str
    type: str
    size: int = 10
    properties: Optional[Dict[str, Any]] = None


class KGLink(BaseModel):
    """Model definition."""

    source: str
    target: str
    label: str
    weight: float = 0.5


class KGData(BaseModel):
    """Model definition."""

    nodes: List[KGNode] = []
    links: List[KGLink] = []


class ReasoningRequest(BaseModel):
    """Model definition."""

    type: Literal["shortest_path", "entity_neighbors"]
    entity_a: Optional[str] = None
    entity_b: Optional[str] = None
    max_depth: int = Field(default=2, ge=1, le=3)
    algorithm: str = "dijkstra"


class PerformanceMetrics(BaseModel):
    """Model definition."""

    total_latency: float
    token_count: int = 0
    steps: List[Dict[str, Any]] = []


class AppConfig(BaseModel):
    """Frontend-readable application config."""

    entity_types: List[str]
    relation_types: List[str]
    example_questions: List[str]
    search_strategies: List[Dict[str, str]]
    default_top_k: int
    default_similarity_threshold: float
    chat_defer_kg: bool = True
    frontend_typing_effect: bool = False
