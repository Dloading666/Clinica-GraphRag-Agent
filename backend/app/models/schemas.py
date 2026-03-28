"""Pydantic 请求/响应模型"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


# ===== 对话相关 =====

class ChatRequest(BaseModel):
    """对话请求"""
    message: str
    session_id: Optional[str] = None
    agent_type: str = "naive_rag"
    top_k: int = 15
    similarity_threshold: float = 0.82
    debug: bool = False


class ChatResponse(BaseModel):
    """对话响应"""
    answer: str
    session_id: str
    execution_log: Optional[List[Dict[str, Any]]] = None
    kg_data: Optional[Dict[str, Any]] = None
    references: Optional[List[Dict[str, Any]]] = None
    performance: Optional[Dict[str, Any]] = None


class StreamEvent(BaseModel):
    """SSE 流式事件"""
    event: str  # status, answer, execution_log, kg_data, done, error
    data: Any


# ===== 知识库相关 =====

class DocumentInfo(BaseModel):
    """文档信息"""
    id: int
    filename: str
    file_type: Optional[str] = None
    chunk_count: int = 0
    created_at: Optional[datetime] = None


class ChunkInfo(BaseModel):
    """文本块信息"""
    id: str
    content: str
    chapter: Optional[str] = None
    section: Optional[str] = None
    similarity: Optional[float] = None
    document_name: Optional[str] = None


# ===== 知识图谱相关 =====

class KGNode(BaseModel):
    """知识图谱节点"""
    id: str
    label: str
    type: str
    size: int = 10
    properties: Optional[Dict[str, Any]] = None


class KGLink(BaseModel):
    """知识图谱边"""
    source: str
    target: str
    label: str
    weight: float = 0.5


class KGData(BaseModel):
    """知识图谱数据"""
    nodes: List[KGNode] = []
    links: List[KGLink] = []


class ReasoningRequest(BaseModel):
    """图谱推理请求"""
    type: str  # shortest_path, one_two_hop, common_neighbors, entity_cycles, influence
    entity_a: Optional[str] = None
    entity_b: Optional[str] = None
    max_depth: int = 2
    algorithm: str = "dijkstra"


# ===== 分析相关 =====

class PerformanceMetrics(BaseModel):
    """性能指标"""
    total_latency: float
    token_count: int = 0
    steps: List[Dict[str, Any]] = []


# ===== 配置相关 =====

class AppConfig(BaseModel):
    """前端可获取的应用配置"""
    entity_types: List[str]
    relation_types: List[str]
    example_questions: List[str]
    search_strategies: List[Dict[str, str]]
    default_top_k: int
    default_similarity_threshold: float
