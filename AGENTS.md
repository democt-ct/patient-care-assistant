# AGENTS.md — 患者医疗信息安全 Agent

> 每次新对话自动加载。修改项目后请调用 `/sync-docs` 同步 CHANGELOG 和项目文档。

---

## 1. 项目一句话

面向患者的高风险医疗信息 Agent。核心是「确定性安全门禁 → 任务路由 → 结构化记录/审核知识检索 → EvidencePack 证据判断 → 引用校验与安全输出」，用于病历事实核验、症状风险分流、连续对话澄清和健康教育；不替代医生诊断、处方或剂量调整。

---

## 2. 目录结构（简要）

| 目录/文件 | 作用 |
|-----------|------|
| `app/` | ★ 后端核心（FastAPI + Agent Graph + ORM + 服务层） |
| `app/api/` | HTTP 路由层（患者 CRUD、Agent、记忆、SSE 流式） |
| `app/core/` | 基础设施（PG 连接、Redis、调度器、结构化日志、Prometheus 指标、OTel 追踪） |
| `app/middleware/` | 安全中间件（访问控制、速率限制） |
| `app/mcp/` | 进程内医疗工具注册与执行层（6 工具 + LLM 编排 + 视觉 + TTS；不是标准 MCP 协议服务） |
| `app/models/` | SQLAlchemy ORM（17 张表） |
| `app/services/` | 业务服务（RAG 检索、记忆抽取、偏好管理、服务端评估评分） |
| `app/schemas/` | Pydantic 请求/响应 Schema |
| `app/static/` | 旧版前端 + 质量评估控制台（`evaluate.html` + `css/` + `js/`） |
| `app/config/` | 配置层（`production.py`、`local_settings.py`、`evaluation_cases.py`） |
| `frontend/` | ★ 新版前端（React 19 + TypeScript + Vite） |
| `data/chroma_knowledge/` | 本地生成的 ChromaDB 运行目录（不纳入版本控制；由导入/同步流程重建） |
| `docs/` | 项目文档 |
| `scripts/` | 工具脚本（批量导入、质量评估、种子数据、`dev.js` Node 开发启动器） |
| `tests/` | pytest 测试（341 个） |
| `docker-compose.yml` | PostgreSQL 15 (:5433) + Redis 7 (:6380) |
| `package.json` | 根目录统一启动/测试入口（`npm run dev` 等） |
| `start_dev.bat` / `start_tunnel.bat` | 兼容旧启动脚本（可选，功能已被 `npm run dev` 取代） |

> 完整目录树、每层详解、架构模式见 **[docs/项目结构文档.md](docs/项目结构文档.md)**

---

## 3. 启动方式

| 方式 | 命令 | 说明 |
|------|------|------|
| **一键全栈** | `npm run dev` | 拉起 Docker 基础设施 → 启动后端(:8001) + 前端(:3000) → 自动开浏览器；`-- --no-open` 关闭自动打开 |
| **后端开发** | `npm run dev:backend` | 等价 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload` |
| **前端开发** | `npm run dev:frontend` | 等价 `cd frontend && npm run dev`，:3000 代理到 :8001 |
| **Docker 服务** | `npm run docker:infra` | 等价 `docker compose up -d`，启动 PostgreSQL(:5433) 与 Redis(:6380) |
| **内网穿透** | `start_tunnel.bat`（可选） | 一键后端 + Cloudflare 隧道，依赖 cloudflared |
| **质量评估** | `python scripts/run_evaluation.py --split test --verbose` | 运行 51 条分层评估用例（21 开发 / 30 独立测试；用例数据源在 `app/config/evaluation_cases.py`） |

访问：
- `http://localhost:3000` — React 前端（聊天 + 记忆 + Debug）
- `http://localhost:3000/evaluate` — 质量评估控制台
- `http://127.0.0.1:8001/evaluate` — 评估控制台（直连）
- `http://127.0.0.1:8001/docs` — Swagger 文档
- `http://127.0.0.1:8001/metrics` — Prometheus 指标

---

## 4. 环境变量速查

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PG_HOST` / `PG_PORT` / `PG_USER` / `PG_PASSWORD` / `PG_DATABASE` | localhost:5433 / postgres / postgres / patient_agent | PostgreSQL（Docker 映射 5433→5432） |
| `REDIS_HOST` / `REDIS_PORT` | localhost:6380 | Redis（Docker 映射 6380→6379） |
| `TEXT_API_BASE` / `TEXT_MODEL` | ModelScope API / deepseek-ai/DeepSeek-V4-Flash | 文本 LLM |
| `TEXT_FALLBACK_MODEL` | Qwen/Qwen3-235B-A22B-Instruct-2507 | 备用 LLM（主模型失败时降级） |
| `VISION_API_BASE` / `VISION_MODEL` | ModelScope / Qwen3-VL-8B-Instruct | 视觉 LLM |
| `CORS_ORIGINS` | * | CORS 白名单（逗号分隔） |
| `RATE_LIMIT_PER_MINUTE` | 60 | 速率限制 |
| `KNOWLEDGE_HF_EMBEDDING_MODEL` | BAAI/bge-small-zh-v1.5 | 嵌入模型 |
| `RERANKER_ENABLED` | false | Cross-Encoder 重排序 |
| `QUERY_REWRITE_ENABLED` | true | LLM 查询改写 |
| `RERANKER_MODEL` | BAAI/bge-reranker-v2-m3 | 重排序模型 |
| `RETRIEVER_WARMUP_ENABLED` | false | 是否在启动时后台预热向量检索模型；离线或网络受限环境保持关闭 |
| `PATIENT_FACT_EMBEDDING_ENABLED` | false | 患者结构化事实的向量排序开关；默认使用关键词排序，避免首问加载模型 |
| `EVIDENCE_JUDGE_ENABLED` | true | V2 LLM 证据法官开关；LLM 不可用时静默降级确定性判定 |
| `EVIDENCE_JUDGE_TIMEOUT_SECONDS` | 8 | 证据法官调用超时（秒） |
| `LLM_CLASSIFIER_ENABLED` | false | 规则未命中时用 LLM 分类器兜底路由（灰度开关） |
| `CLARIFICATION_TTL_SECONDS` | 3600 | 澄清追问会话状态有效期（秒） |
| `SCHEDULER_ENABLED` | false | 后台定时任务 |
| `TTS_PROVIDER` | kokoro | TTS 引擎 |
| `STREAM_AGENT_TIMEOUT_SECONDS` | 20 | SSE Agent 后端调用超时秒数；超时后返回安全降级回答 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 未设置 | 可选 OTLP Collector 地址；设置后导出 Agent spans 到兼容的链路后端 |

---

## 5. 关键约定

- **数据库**: PostgreSQL 为主，支持 SQLite 测试模式（`TEST_DATABASE_URL` 环境变量）。连接前 `database.py` 会自动探测 TCP 端口
- **LLM 配置**: 优先级 `app/config/local_settings.py` > 环境变量 > 默认值。支持主模型 + 备用模型自动降级
- **前端**: React 新版在 `frontend/`（`localhost:3000`），旧版在 `app/static/`（保留兼容）。质量评估控制台在 `/evaluate` 路由，已拆分为 `evaluate.html` + `css/evaluate.css` + `js/evaluate.js`
- **评估用例数据源**: 用例统一定义在 `app/config/evaluation_cases.py`（单一数据源），HTTP 接口 `GET /api/v1/evaluation/cases`、命令行运行器、前端控制台均从此处取数，禁止硬编码副本。高风险用例使用 `safety_policy` 声明必须出现的安全提示与危险建议模式，不能以单个词的出现与否判定违规。
- **评估运行记录**: 服务端评分接口为 `POST /api/v1/evaluation/score`；`POST /api/v1/evaluation/runs` 会保存带用例/评分/模型/提示词/知识库版本与 `trace_id` 的结果，`GET /api/v1/evaluation/runs/summary` 返回聚合趋势。持久化记录仅保留回答指纹与评分，不保存原始回答；生产库执行 `migration/20260727_evaluation_runs.sql`
- **V2 对话型升级**: 证据双轨（LLM 证据法官为主、确定性兜底，`EVIDENCE_JUDGE_ENABLED` 开关）、模糊主诉澄清闭环（会话状态机 + Redis/内存存储）、规则手册知识块注入（`rulebook_knowledge.py`）、患者偏好个性化；确定性安全红线（危机/高危）始终短路，LLM 不可用时静默降级。
- **事实查询直答**: 对诊断、既往用药、手术、接诊医生、复诊安排、过敏史和紧急联系人等明确记录查询，优先直接依据结构化病历/就诊/主档返回，不调用 LLM 改写；需要综合分析或临床判断时才进入 Agent 生成链路。
- **工具层命名**: `ModularMCPServer` 是项目内部的工具注册/列表/调用抽象；在补齐标准协议握手与传输层前，公开文档和简历统一称“医疗工具注册与执行层”，不得宣称已实现标准 MCP Server。
- **种子数据同步**: `scripts/seed_patients.py` 可重复执行，按患者编码与记录标识补齐缺失的演示病历/就诊数据，不覆盖已存在记录。
- **向量库不入库**: `data/chroma_knowledge/` 是可重建的本地运行产物，禁止提交 SQLite/HNSW 二进制；公开仓库只保留虚构种子数据、知识来源清单与导入脚本。
- **可观测性与隐私**: `/metrics` 的 HTTP 标签使用路由模板，禁止添加患者 ID、会话 ID、问题全文等高基数或敏感标签。结构化日志与 OTel span 使用同一 `trace_id`；患者/会话 ID 仅以哈希属性写入 span
- **问答执行步骤**: React 聊天回答下方保留面向用户的“执行步骤”摘要，默认收起；展示身份校验、上下文加载、意图识别、信息查询和回答生成等阶段，不展示原始病历、工具参数或模型内部推理。
- **端口映射**: Docker PG 映射 5433→5432，Redis 映射 6380→6379（见 `docker-compose.yml`）
- **Reranker/Scheduler**: 默认关闭。都是"增强型"功能，不影响核心问答链路
- **启动脚本**: `start_dev.bat` / `start_tunnel.bat`（`.bat` 文件）

---

## 6. 更新记录

> 详见 **[CHANGELOG.md](./CHANGELOG.md)**
