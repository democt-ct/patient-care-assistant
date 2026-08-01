# 患者照护助手（Patient Care Assistant）

面向患者端的照护协同助手原型：医生发布照护计划，患者完成待办，协调员处理求助；健康工作台还提供基于病历和就诊记录的 AI 问答、图片报告理解、连续对话记忆与语音播报。

## 核心能力

- 照护闭环：照护计划、患者待办、求助与协调处理。
- AI 健康问答：优先依据结构化病历、就诊记录和患者主档直答；复杂问题进入 Agent + RAG 链路。
- 安全与隐私：高风险医疗建议安全拦截；指标不记录患者 ID、会话 ID 或问题全文等敏感高基数标签。
- 内置可观测：聊天回答下方提供默认收起的“执行步骤”，展示身份校验、上下文加载、意图识别、信息查询和回答生成等用户可理解的阶段；不暴露原始病历、工具参数或模型内部推理。
- 质量评估：15 条集中管理的评估用例，支持服务端评分、RAGAS 指标、运行记录与趋势聚合。

## 技术栈

FastAPI、SQLAlchemy、PostgreSQL、Redis、ChromaDB、MCP、React 18、TypeScript、Vite、Prometheus 与 OpenTelemetry。

## 快速启动

### 1. 启动依赖服务

```bat
docker compose up -d
```

PostgreSQL 映射到 `5433`，Redis 映射到 `6380`。

### 2. 启动后端（端口 8001）

```bat
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

### 3. 启动前端

```bat
cd frontend
npm install
npm run dev
```

开发前端默认运行在 `http://localhost:3000`，并代理请求至后端 `http://127.0.0.1:8001`。也可双击 `start_dev.bat` 启动本地开发环境。

## 常用入口

| 地址 | 用途 |
| --- | --- |
| `http://localhost:3000` | React 健康工作台 |
| `http://localhost:3000/evaluate` | 内置质量评估控制台 |
| `http://127.0.0.1:8001/docs` | Swagger API 文档 |
| `http://127.0.0.1:8001/metrics` | Prometheus 指标 |
| `http://127.0.0.1:8001/evaluate` | 后端直连评估控制台 |

## 评估与可观测

运行完整评估：

```bat
python scripts/run_evaluation.py --verbose
```

评估用例统一定义在 `app/config/evaluation_cases.py`，前端、HTTP 接口和命令行复用同一数据源。运行结果只持久化回答指纹和评分，并关联 `trace_id`，不保存原始回答。

服务端会将结构化日志、Prometheus 指标和 OpenTelemetry span 通过相同的 `trace_id` 关联。需要将链路导出到兼容后端时，设置 `OTEL_EXPORTER_OTLP_ENDPOINT`。

## 项目结构

```text
app/        FastAPI、Agent/MCP、业务服务、模型与可观测基础设施
frontend/   React + TypeScript 前端
scripts/    数据导入、种子与质量评估工具
tests/      pytest 测试
docs/       架构、接口与项目说明
```

详细目录说明见 [docs/项目结构文档.md](docs/项目结构文档.md)。

## 配置

配置优先级为 `app/config/local_settings.py`、环境变量、默认值。复制并按实际环境调整 `.env` 后启动；不要提交其中的密钥。

主要可选配置包括：

- `TEXT_API_BASE`、`TEXT_MODEL`：文本模型。
- `VISION_API_BASE`、`VISION_MODEL`：视觉模型。
- `OTEL_EXPORTER_OTLP_ENDPOINT`：OTLP 链路导出地址。
- `RERANKER_ENABLED`、`SCHEDULER_ENABLED`：增强能力开关，默认关闭。

## 测试

```bat
python -m pytest -q
```

更多开发约定和更新记录见 [AGENTS.md](AGENTS.md) 与 [CHANGELOG.md](CHANGELOG.md)。
