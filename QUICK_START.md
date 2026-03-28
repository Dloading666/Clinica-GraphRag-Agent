# Quick Start

这份文档只做一件事：用最少步骤把项目跑起来，并完成首次知识库导入。

完整版说明见 [README.md](./README.md)。

## 5 分钟跑通

### 1. 准备配置文件

```powershell
Copy-Item .env.example .env
```

打开 `.env`，至少补齐这 6 项：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `EMBEDDING_API_KEY`
- `EMBEDDING_BASE_URL`
- `EMBEDDING_MODEL`

如果你走 Docker Compose，保留下面两个值不变：

- `POSTGRES_HOST=postgres`
- `NEO4J_URI=neo4j://neo4j:7687`

## 2. 启动全部服务

```powershell
docker compose up --build -d
```

启动后可访问：

- 前端：http://localhost:3000
- 后端：http://localhost:8000
- API 文档：http://localhost:8000/docs
- Neo4j Browser：http://localhost:7474

## 3. 导入示例知识库

项目里的示例知识库已经放在 [知识库/医疗知识库](./知识库/医疗知识库)。

执行整库导入并同时建图：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/knowledge-base/ingest-directory?path=/app/knowledge_base/医疗知识库&build_graph=true"
```

如果返回 `status = success`，说明导入完成。

## 4. 打开前端开始提问

浏览器访问：

```text
http://localhost:3000
```

可以直接点击左侧示例问题验证效果。

## 5. 快速检查是否正常

### 健康检查

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/health"
```

### 查看已导入文档

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/knowledge-base/documents"
```

### 查看图谱统计

```powershell
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/kg/stats"
```

## 本地开发模式

如果你想前后端在本机运行、数据库仍用 Docker：

### 1. 只启动数据库

```powershell
docker compose up -d postgres neo4j
```

### 2. 修改 `.env`

把以下两项改为本地地址：

```env
POSTGRES_HOST=localhost
NEO4J_URI=neo4j://localhost:7687
```

### 3. 启动后端

```powershell
python -m venv .venv
```

```powershell
.venv\Scripts\Activate.ps1
```

```powershell
pip install -r backend/requirements.txt
```

```powershell
python backend/main.py
```

### 4. 启动前端

```powershell
Set-Location .\frontend
```

```powershell
npm install
```

```powershell
npm run dev
```

### 5. 导入知识库

本地模式下也可以继续用 API 导入：

```powershell
$kbPath = (Resolve-Path .\知识库\医疗知识库).Path
Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:8000/api/knowledge-base/ingest-directory?path=$([System.Uri]::EscapeDataString($kbPath))&build_graph=true"
```

这条命令会自动读取当前仓库里的 `知识库/医疗知识库` 目录，无需手动改绝对路径。

## 常见问题

### 服务启动成功，但问答没有内容

优先检查：

- 模型 Key 是否正确
- 是否已完成知识库导入
- 图谱是否已构建

### 本地运行时报数据库连接错误

基本都是 `.env` 里的主机名没切到本地：

- `POSTGRES_HOST=localhost`
- `NEO4J_URI=neo4j://localhost:7687`

### 想重新构建图谱

```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/knowledge-base/rebuild-graph"
```

## 下一步

- 完整说明看 [README.md](./README.md)
- 查看接口文档看 http://localhost:8000/docs
