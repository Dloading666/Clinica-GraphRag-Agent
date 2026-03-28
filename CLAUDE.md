# 临床诊疗问答助手 (Clinical Q&A Assistant)

GraphRAG 临床问答系统：FastAPI + PostgreSQL(pgvector) + Neo4j + LangGraph + React

## 架构概览

三层架构：React 前端 → FastAPI 后端 → 双数据库(PostgreSQL + Neo4j)

- **后端**: FastAPI async，LangGraph 状态机 Agent，SSE 流式输出
- **前端**: React 18 + TypeScript + Ant Design 5 + Zustand + Vite
- **存储**: PostgreSQL(pgvector HNSW) 存文档/向量/会话，Neo4j 存知识图谱/社区
- **部署**: Docker Compose 四服务 (postgres, neo4j, backend, frontend)

## 项目结构

```
backend/
  main.py                          # FastAPI 入口，lifespan 管理
  requirements.txt                 # Python 依赖
  app/
    config/
      settings.py                  # Pydantic 配置，读取 .env
      database.py                  # SQLAlchemy async engine + Neo4j 连接管理
      prompts/clinical_prompts.py  # 所有 LLM prompt 模板
    models/
      db_models.py                 # ORM 模型: Document, Chunk, Entity, Relationship, Community, ChatSession, ChatMessage
      schemas.py                   # Pydantic 请求/响应 schema
      llm_factory.py               # ChatOpenAI / OpenAIEmbeddings 工厂函数
    agents/                        # 五种 RAG Agent (LangGraph 状态机)
      base.py                      # BaseAgent 抽象基类
      naive_rag_agent.py           # 纯向量检索
      graph_agent.py               # 知识图谱检索 (local + global)
      hybrid_agent.py              # 向量 + 图谱并行检索
      fusion_agent.py              # 多源检索 + LLM 重排序
      deep_research_agent.py       # 迭代式多跳研究
    search/
      naive_search.py              # pgvector 向量相似度搜索 + 关键词回退
      local_search.py              # 实体图谱扩展检索
      global_search.py             # 社区级 Map-Reduce 检索
    graph/
      neo4j_manager.py             # Neo4j CRUD + 图扩展 + 社区查询
      entity_extractor.py          # LLM 实体/关系抽取
      graph_builder.py             # 图构建编排器
      community_detector.py        # Louvain 社区检测 + LLM 摘要
    pipelines/
      file_reader.py               # .docx/.pdf 文件读取，按标题层级解析
      text_chunker.py              # 中文医学文本分句感知分块
      document_processor.py        # 端到端: 读取 → 分块 → 批量 embedding → 存储
    services/
      agent_service.py             # AgentManager: 按会话管理 Agent 实例
      chat_service.py              # 聊天流处理: SSE 流, 会话管理, 消息持久化
      ingestion_service.py         # 文档导入 + 图谱构建编排
      kg_service.py                # 知识图谱可视化/查询/推理
    routers/
      chat.py                      # POST /chat/stream, GET /chat/sessions
      knowledge_base.py            # POST /upload, POST /ingest-directory
      knowledge_graph.py           # GET /kg/visualization, POST /kg/reasoning
      analytics.py                 # GET /analytics/stats
  scripts/
    init_db.py                     # 建表 + pgvector 扩展
    ingest_documents.py            # 批量导入文档
    build_graph.py                 # 实体抽取 + 社区检测

frontend/src/
  main.tsx                         # React 入口
  App.tsx                          # 主应用
  index.css                        # 全局样式 + 滚动条 + Markdown 样式
  components/
    Layout/MainLayout.tsx          # 三栏布局: 侧边栏 | 聊天 | 详情面板
    Chat/ChatPanel.tsx             # 聊天界面
    Chat/MessageItem.tsx           # 消息渲染 (Markdown)
    Sidebar/Sidebar.tsx            # 策略选择 + 示例问题 + 搜索参数
    Detail/DetailPanel.tsx         # Tab 面板容器
    Detail/TracePanel.tsx          # 执行轨迹
    Detail/KnowledgeGraphPanel.tsx # 知识图谱可视化
    Detail/SourcePanel.tsx         # 源文档引用
    Detail/PerformancePanel.tsx    # 性能监控
  stores/
    chatStore.ts                   # Zustand: 消息, 会话, 流式状态, 轨迹, KG 数据
    configStore.ts                 # Zustand: 策略, top_k, 相似度阈值, debug
    profileStore.ts                # Zustand: 用户配置
  hooks/
    useChat.ts                     # sendMessage hook, SSE 连接
  api/
    index.ts                       # Axios 客户端 + SSE 连接
  types/
    index.ts                       # TypeScript 接口定义
  constants/
    exampleQuestions.ts            # 临床示例问题
```

## 技术栈

| 层 | 技术 |
|---|------|
| LLM | 智谱 GLM (OpenAI 兼容接口) |
| Embedding | 智谱 Embedding-3 (1024维) |
| Agent 框架 | LangGraph 状态机 |
| 后端框架 | FastAPI (async) |
| 向量数据库 | PostgreSQL 16 + pgvector (HNSW) |
| 图数据库 | Neo4j 5.22 + APOC + GDS |
| ORM | SQLAlchemy 2.x (async) |
| 前端 | React 18 + TypeScript + Vite 5 |
| UI 组件库 | Ant Design 5 |
| 状态管理 | Zustand |
| 流式通信 | Server-Sent Events (SSE) |
| 部署 | Docker Compose |

## 环境配置 (.env)

```bash
# LLM - 智谱 GLM
LLM_API_KEY=xxx
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-4-flash

# Embedding - 智谱 Embedding-3
EMBEDDING_API_KEY=xxx
EMBEDDING_BASE_URL=https://open.bigmodel.cn/api/paas/v4
EMBEDDING_MODEL=embedding-3
EMBEDDING_DIMENSION=1024       # 必须与模型输出维度一致

# PostgreSQL
POSTGRES_HOST=postgres         # Docker 内用服务名, 本地开发用 localhost
POSTGRES_PORT=5432
POSTGRES_DB=clinical_qa
POSTGRES_USER=postgres
POSTGRES_PASSWORD=clinical_qa_2024

# Neo4j
NEO4J_URI=neo4j://neo4j:7687   # Docker 内用服务名
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=clinical_neo4j_2024
```

## 常用命令

```bash
# 启动全部服务
docker compose up --build -d

# 仅重启后端 (改 .env 后需 --force-recreate)
docker compose up -d --force-recreate backend

# 仅重建前端
docker compose up -d --build frontend

# 查看后端日志
docker compose logs -f backend

# 初始化数据库
docker exec clinical_qa_backend python scripts/init_db.py

# 导入知识库文档
curl -X POST "http://localhost:8000/api/knowledge-base/ingest-directory?path=/app/knowledge_base/医疗知识库&build_graph=true"
```

## 五种 Agent 策略

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| naive_rag | 纯向量相似度检索 | 快速事实查询 |
| graph_rag | 实体图谱扩展 + 社区分析 | 关系推理 |
| hybrid_rag | 向量 + 图谱并行 | 平衡检索 |
| fusion_rag | 多源检索 + LLM 重排序 | 高精度综合 |
| deep_research | 迭代分解-检索-评估 | 复杂多跳问题 |

每个 Agent 继承 `BaseAgent`，通过 LangGraph `StateGraph` 实现状态机流转：
`agent → (tool_call?) → retrieve → generate → END`

## 数据库 Schema

**PostgreSQL 核心表:**
- `chunks`: 文档分块 + `Vector(1024)` embedding 列，HNSW 索引
- `entities`: 实体 (疾病/症状/药物等10类) + embedding
- `relationships`: 实体关系 (治疗/引起/配伍等10类)
- `communities`: Louvain 社区 + LLM 摘要
- `chat_sessions` / `chat_messages`: 会话历史

**Neo4j:**
- `__Entity__` 节点 + 关系边 + `__Community__` 节点
- 与 PostgreSQL 通过 `pg_id` 关联

## SSE 流式协议

```
POST /api/chat/stream → SSE 事件流:
  session  → { session_id }
  status   → "processing" | "searching" | ...
  trace    → { node, input, output, latency }
  answer   → "逐句文本..."
  kg_data  → { nodes: [...], links: [...] }
  done     → { total_latency, token_count }
  error    → 错误信息
```

## 开发注意事项

- `EMBEDDING_DIMENSION` 必须与 embedding 模型实际输出维度一致，否则向量写入会报错
- `docker compose restart` 不会重新加载 `.env`，必须用 `docker compose up -d --force-recreate`
- Ant Design 5.x: `Slider` 无 `size` prop，`TextArea` 用 `variant="borderless"` 替代 `bordered={false}`
- 目录名含中文时 docker-compose 需在 yaml 中显式设置 `name: clinical-qa`
- LLM/Embedding 均使用 OpenAI 兼容接口，可通过修改 `LLM_BASE_URL` 切换任意兼容提供商

## 扩展新 Agent

1. 在 `app/agents/` 新建文件，继承 `BaseAgent`
2. 实现 `_setup_tools()` 和 `_generate_node()`
3. 在 `agent_service.py` 的 `AgentManager` 中注册
4. 前端 `configStore.ts` 添加策略选项
