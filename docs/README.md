# 患者照护助手 — 当前实现说明

本仓库是一套可运行的患者端照护协同助手原型系统，经过五阶段生产化改造，覆盖：

- 患者主档、病历、就诊记录的数据存储与查询
- 自研 MCP 工具层（6 个工具）
- 记忆聊天与通用聊天
- 四层记忆系统：短期工作记忆、长期摘要记忆、知识记忆、患者事实记忆
- 医疗安全防护：安全门禁、三级分诊、幻觉检测、药物相互作用检查
- 照护计划：草案生成、任务管理、协作工单
- 基于 ChromaDB 的混合检索 RAG
- 图文问答、语音播报
- 生产级安全加固（访问控制、审计日志、速率限制、敏感字段脱敏）
- 批量数据导入（CSV/JSON + 自动知识切片）
- SSE 流式响应端点
- Prometheus 可观测性指标
- 质量评估控制台 + 131 个测试

## 1. 当前技术栈

**后端**:
- `FastAPI` + `gunicorn` + `uvicorn workers`
- `SQLAlchemy` 2.0
- `PostgreSQL` 15（主数据库）
- `Redis` 7（会话缓存）
- `ChromaDB`（向量存储）
- `sentence-transformers`（嵌入模型）
- `APScheduler`（定时任务）
- `prometheus_client`（可观测性）

**模型接入**:
- 文本生成：OpenAI-compatible 接口，支持主模型 + 备用模型自动降级
- 当前默认：`deepseek-ai/DeepSeek-V4-Flash` → 备用 `Qwen/Qwen3-235B-A22B-Instruct-2507`
- 图片理解：`Qwen/Qwen3-VL-8B-Instruct`
- 向量模型：`BAAI/bge-small-zh-v1.5`

**前端**:
- React 18 + TypeScript + Vite（`frontend/`）
- 质量评估控制台（`app/static/evaluate.html`）
- 旧版兼容页（`app/static/tester.html`）

**测试**:
- `pytest` + 131 个测试
- SQLite 内存数据库（测试隔离）
- 覆盖 CRUD / Auth / API / 中间件 / 批量导入 / SSE 流式 / 质量评估

## 2. 核心能力

### 2.1 数据层
17 张表：`patients`、`medical_records`、`visit_records`、`memory_*`（7 张）、`care_plans` + `care_plan_items` + `care_plan_item_events` + `care_cases`（4 张照护计划）、`audit_log`、`evaluation_runs`

### 2.2 Agent 编排
- 安全门禁（确定性规则，LLM 前拦截高危请求）
- 三级分诊（EMERGENCY/URGENT/ROUTINE）+ 紧急升级
- 意图分类（关键词 + LLM，6 类 + uncertain 兜底 + 多意图融合）
- 规划候选生成 + 共识投票（plan-then-execute，非 ReAct）
- 幻觉检测（回答后校验事实一致性）
- SSE 流式响应（`/api/v1/mcp/agent/query-stream`）
- LLM 自动降级（主模型失败 → 备用模型）

### 2.3 安全与合规
- `PatientDataGuardMiddleware`：数据访问控制
- `AuditLog`：异步审计日志
- `RateLimitMiddleware`：速率限制
- `masking.py`：敏感字段脱敏
- 数据保留策略（>90 天自动清理）

### 2.4 RAG 检索
混合检索：向量召回（ChromaDB）+ 关键词补召回 + 元数据过滤 + 时效性评分 + 可选 reranker

### 2.5 可观测性
- `GET /metrics`（Prometheus 格式）
- `trace_id` 链路追踪
- 结构化日志（JSON/text 可切换）
- Agent 与 LLM 的成功/失败、耗时和 token 指标；HTTP 指标按路由模板聚合，不将患者标识写入 Prometheus 标签
- 质量评估统一由服务端评分，`POST /api/v1/evaluation/runs` 保存无原始回答的版本化结果，`GET /api/v1/evaluation/runs/summary` 提供聚合趋势
- 对诊断、既往用药、复诊安排、紧急联系人和已登记药物过敏等明确事实，系统会先查结构化病历并直接作答；这类查询不依赖 LLM，也不会把“不能使用已过敏药物”误判为风险建议。
- 向量检索预热和患者事实向量排序默认关闭（`RETRIEVER_WARMUP_ENABLED=false`、`PATIENT_FACT_EMBEDDING_ENABLED=false`），避免离线或受限网络下的模型下载重试拖慢服务；具备本地模型缓存时可显式开启。
- 聊天回答下方提供默认收起的“执行步骤”，以用户可读摘要展示身份校验、上下文加载、意图识别、信息查询和回答生成

## 3. 启动方式

```bash
# 安装依赖
pip install -r requirements.txt
cd frontend && npm install

# 启动 PostgreSQL + Redis（Docker）
docker compose up -d

# 后端开发服务器
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload

# 前端开发服务器（另一个终端）
cd frontend && npm run dev
```

### 访问地址

| 地址 | 内容 |
|------|------|
| `http://localhost:3000` | React 前端（聊天 + Memory Debug） |
| `http://localhost:3000/evaluate` | 质量评估控制台 |
| `http://127.0.0.1:8001/evaluate` | 评估控制台（直连） |
| `http://127.0.0.1:8001/docs` | Swagger 文档 |
| `http://127.0.0.1:8001/metrics` | Prometheus 指标 |

## 4. 测试

```bash
# 全部 131 个测试
python -m pytest tests/

# 质量评估用例
python scripts/run_evaluation.py --verbose

# 按类别
python scripts/run_evaluation.py --case allergy
```

## 5. 项目结构

```
patient-care-assistant/
├── app/                    # 后端
│   ├── main.py
│   ├── api/                # 路由层
│   │   ├── routes.py       # 患者 CRUD
│   │   ├── mcp_routes.py   # Agent 接口
│   │   ├── care_plan_routes.py # 照护计划
│   │   ├── memory_routes.py # 记忆接口
│   │   ├── stream_routes.py # SSE 流式
│   │   └── evaluation_routes.py # 质量评估
│   ├── core/               # 基础设施
│   │   ├── database.py, redis_client.py
│   │   ├── scheduler.py, logging.py
│   │   └── metrics.py      # Prometheus
│   ├── middleware/          # 中间件
│   │   ├── patient_data_guard.py
│   │   └── rate_limit.py
│   ├── mcp/                # MCP 工具 + Agent 编排 + 安全防护
│   │   ├── config.py       # LLM 客户端
│   │   ├── llm_router.py   # 意图→规划→执行→回答
│   │   ├── server.py       # 6 个工具
│   │   ├── medical_safety_gate.py # 安全门禁
│   │   ├── triage.py       # 三级分诊
│   │   ├── hallucination_guard.py # 幻觉检测
│   │   ├── drug_interaction.py    # 药物检查
│   │   └── speech.py, vision.py, auth.py
│   ├── models/             # 17 张 ORM 表
│   ├── services/           # 8 个业务服务
│   ├── utils/masking.py    # 脱敏
│   └── static/
│       ├── index.html, tester.html  # 旧版
│       └── evaluate.html   # 质量评估控制台
├── frontend/               # React 前端 (TypeScript + Vite)
│   └── src/
│       ├── App.tsx, components/, pages/, types/
├── scripts/
│   ├── bulk_import.py      # 批量导入
│   ├── run_evaluation.py   # 质量评估
│   └── seed_patients.py    # 种子数据
├── tests/                  # 131 个测试
├── data/                   # ChromaDB 向量库
└── docs/
