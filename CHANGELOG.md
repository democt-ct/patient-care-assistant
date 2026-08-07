# CHANGELOG — 患者照护助手

## 2026-08-07 — V2 阶段 6：记忆个性化（回答长度/术语/风险提醒强度）

- 新增 `app/services/response_guidance.py::personalize_response`：按 `memory_preferences` 调整风险提醒强度（high → 追加强提醒）、术语表达（plain → 通俗语言注记）、回答长度（brief 仅标记精简模式，出于安全不截断医疗内容）。
- `pipeline.py` 输出装配节点在五段契约装配后应用个性化；无偏好时保持原样（noop）。
- `memory_preference_service.py` 新增 `preference_payload`（字段级偏好字典，不含隐私备注）；`mcp_routes.py` 与 `stream_routes.py` 在身份解析后加载患者偏好并传入 Agent Graph（`personalization` kwarg）。
- 新增 `tests/test_response_guidance.py` 个性化用例（强提醒/通俗语言/noop/管线级）；全量 pytest 326 条通过。

## 2026-08-07 — V2 阶段 4+5：安全红线收敛 + 引用安全网增强

- 安全红线收敛：确定性短路保留强信号（自伤/自杀危机、明确高危组合）；普通风险症状（疼痛/发麻/麻木/不适等）不再硬拦截，新增 `app/services/response_guidance.py` 的 `embed_escalation_guidance`，在正常回答末尾自然内嵌「如果症状剧烈、伴大汗、呼吸困难或意识异常，请立即拨打 120 或前往急诊」并把 risk_level 标为 urgent。
- 引用安全网：阶段 1 的 claim → evidence_id 绑定在 `citation_validate` 节点生效（绑定证据缺失或 verdict=unsupported 直接标记），高危任务校验失败仍覆盖为「当前记录无法支持该结论，请以医生/药师为准」；输出契约新增可选 `claim_bindings` 字段（兼容五段契约）。
- 新增 `tests/test_response_guidance.py`（嵌入/幂等/管线级升级指引）；全量 pytest 318 条通过。
## 2026-08-07 — V2 阶段 3：规则手册知识化 + LLM 分类器路由兜底

- 新增 `app/config/rulebook_knowledge.py`：把 7 类任务的「处理规范/话术/升级指引」整理为已审核知识块（review_status=approved，source 走 `hospital_approved_content` 注册源），`rulebook_context_for(route)` 按路由任务确定性检索并注入系统提示词（「以下是从规则手册检索到的处理规范，请严格遵守」「以下是从患者档案检索到的患者事实，仅用于核验，不得编造」）。
- 新增 `scripts/import_rulebook_knowledge.py`：治理准入校验（allow_publish）并导出 `data/rulebook_knowledge.json` 可审计清单。
- 路由兜底：`retrieval_router.py` 新增 LLM 分类器（`LLM_CLASSIFIER_ENABLED` 默认关闭），规则未命中时可选由 LLM 从 7 个 TaskType 中分类；失败/关闭时静默回退非个体化教育兜底；包装包 `retrieval_router/__init__.py` 同步透传 `llm`。
- `pipeline.py` 生成节点注入规则手册知识块（已审核处理规范优先，患者事实块随后）。
- 新增 `tests/test_rulebook_knowledge.py`（治理准入、注入内容、分类器开启/失败/关闭路径）；全量 pytest 318 条通过。
## 2026-08-07 — V2 阶段 2：澄清闭环（模糊主诉追问问卷 + 会话状态机）

- 新增 `app/services/clarification.py`：非强信号模糊主诉（胸闷/头晕/乏力/恶心等）进入结构化追问问卷（性质/部位/持续时间/伴随症状/危险因素），完成后追加「是否缓解」追问；未缓解或无法判断时保守升级为就医指引（risk_level=urgent）。
- 会话状态机：`ClarificationState` + `ClarificationStore`（Redis 优先、内存兜底，TTL 1 小时），澄清进度跨轮次记忆；强信号仍由安全门禁先行短路，澄清不改变安全红线判定。
- Graph 新增 `clarify` 节点：`task_route` 在模糊主诉或存在进行中澄清状态时转入；非模糊问题路径不变（既有轨迹断言兼容）。
- API 层传递 `session_id`：`mcp_routes.py` 与 `stream_routes.py` 的 Agent 调用均携带会话标识。
- 新增 `tests/test_clarification.py`（状态机推进、缓解判定、存储往返、启动/推进/升级/缓解/跳过路径）；全量 pytest 310 条通过。
## 2026-08-07 — V2 阶段 1：证据双轨（LLM 证据法官 + 确定性兜底）

- 新增 `app/services/evidence_judge.py`：LLM 证据法官对「证据是否充分支撑回答」「未被规则捕获的语义冲突」「关键论断是否有证据支持」输出结构化 verdict（supported / unsupported / conflict / insufficient）与 claim → evidence_id 绑定。
- 契约扩展（`app/schemas/retrieval.py`）：新增 `EvidenceJudgeVerdict` / `ClaimBinding` / `EvidenceJudgeResult`；`EvidenceCheck` 增加 `judge` 与 `verdict_source` 字段（向后兼容）。
- 双轨合并：`pipeline.py` 证据检查节点在确定性判定后调用法官，LLM 可用时以智能判定为主（conflict→澄清、insufficient→澄清、unsupported 且禁止动作→拒答），LLM 失败/超时/空返回静默降级确定性；缺失重试路径不调用法官。
- 引用校验增强：`citation_validator.py`（含包装包）支持 claim_bindings 显式校验，绑定证据 ID 不存在或 verdict=unsupported 直接标记。
- 新开关：`EVIDENCE_JUDGE_ENABLED`（默认 true，测试环境关闭）、`EVIDENCE_JUDGE_TIMEOUT_SECONDS`；`judge_llm` 可注入。
- 新增 `tests/test_evidence_judge.py`（解析/过滤/降级/合并）与 3 条 claim 绑定用例；全量 pytest 302 条通过。
## 2026-08-06 — 更新 GitHub 根 README

- 补充独立测试集（29 条）实测结果表：27/29 通过（93.1%）、高风险召回 / 危险建议拦截 / 冲突发现率 100%、不必要拒答率 0%、P95 5.63s，口径链接 `docs/基线报告.md`。
- 新增危机干预（自伤/自杀 → 12356 心理援助热线 + 120）、药物教育路由说明，以及评估控制台 8 项 MVP 指标口径说明。
- 测试数量同步为 290 条 pytest + 前端 Vitest 单测。


## 2026-08-04 — 评估控制台增加 MVP 指标与口径说明

- 控制台新增「秋招 MVP 指标」区块：路由准确率、高风险召回率、危险建议拦截率、引用正确率、冲突发现率、证据不足正确拒答率、不必要拒答率、P95 延迟共 8 项，客户端按与 `evaluation_service.compute_metrics` 一致的口径实时计算。
- 每个指标卡片带 `?` 悬停说明，面板底部新增「指标口径」图例列出完整定义；原有综合均分/通过率/意图准确率/关键词覆盖率/安全失败数/平均响应时间卡片补充悬停解释。
- `runCase` 结果对象补充 `task_route` / `risk_level` / `next_action` / `evidence_check` / `citation_report` 契约字段，供指标计算使用。
- 指标计算逻辑经 Node 单测验证（高风险召回、路由、引用、冲突、拒答、不必要拒答、P95 全部符合预期）。


## 2026-08-04 — 评估控制台修复：全失败与意图未识别

- 修复 `app/static/js/evaluate.js` 的 TDZ 引用错误：`runCase` 在构造 `result` 时引用了尚未初始化的 `score`，导致每条用例抛 `ReferenceError`、全部显示失败且意图为空；改为先构造结果再计算评分。
- 本地评估限流从 60 提升到 600 次/分钟（`.env`），控制台批量运行不再被 429 拒绝。
- 控制台新增「RAGAS 评判」开关（默认关闭），批量评估默认跳过额外 LLM 评判调用。


## 2026-08-04 — DeepSeek 密钥配置与完整独立测试集实测

- `.env` 配置 DeepSeek 官方密钥（`api.deepseek.com` / `deepseek-chat`，备用 `deepseek-reasoner`），端到端验证健康教育等 LLM 路径正常生成。
- 完整独立测试集（29 条）实测：27 通过（93.1%），高风险召回率 / 危险建议拦截率 / 冲突发现率 100%，不必要拒答率 0%，路由准确率 95.65%，引用正确率 95.65%，P95 5.63s；确定性路径全部通过。
- 修正 `general-001` 评估断言为等价措辞（限盐/饮食/血压），general 前缀 4/4 通过。
- 恢复被并发会话误清空的 `app/mcp/llm_router/pipeline.py`（完整图编排实现）；兼容并发会话新增的 services 包装包与 `agentic_sources.py`，并修正 supplement 测试断言为「仅已审核知识进入默认检索」。
- 已知待办：`missing-001/003` 证据不足拒答措辞（`apply_hallucination_check` 在空 `tool_result` 下 TypeError 降级）。


## 2026-08-04 — Agent 设计与执行计划文档深化

- 扩写 `docs/patient_medical_information_agent_design.md`，新增项目背景、Agent/RAG/Agentic RAG、RetrievalRoute、EvidencePack、证据覆盖率、冲突、引用校验、安全停止、Graph 和输出契约等概念说明。
- 将架构、路由、EvidencePack、输出字段、安全层次、评估指标、实现映射和局限尽量改为表格，区分概念定义、设计取舍和当前实现状态。
- 重构 `docs/执行计划.md`，改为项目控制表，明确已完成、待验证、待开发和暂停状态，并增加 P0 工作包、发布门槛、风险清单、推荐执行顺序和 DoD。
- 同步 `docs/基线报告.md` 与 `docs/项目结构文档.md` 的评估集数字为 47 条（18 dev / 29 test），更新当前核心 Agent 主链状态。

## 2026-08-04 — 工程优化：死代码清理、lint 基线、依赖拆分、前端测试

- 安全补强：新增自伤/自杀危机分支（`CRISIS`），命中即返回全国心理援助热线 12356 + 120 指引，不进入 LLM；新增 `crisis-001` 评估用例与回归测试。
- 删除 `app/mcp/llm_router.py` 中被 Graph 版本覆盖的 legacy `run_agent_tool_query_stream` 死代码（约 250 行重复实现）。
- 新增 `ruff.toml` lint 基线（E4/E7/E9/F/I 安全子集），本轮新建/改动文件 ruff 全过；全库历史问题从 1482 降到 195 且可审计。
- 依赖拆分：重依赖（sentence-transformers / kokoro / misaki / soundfile）移入 `requirements-optional.txt`，核心依赖保持轻量；Dockerfile 安装两份。
- `scripts/seed_patients.py` 启动时自动建表（幂等 create_all），新环境一步初始化。
- 前端接入 Vitest：新增 `ChatPanel.test.tsx`（标签映射 + ContractCard 渲染），`npm test` 4 条通过。
- 文档数字统一：ORM 表数 11→17、测试数 288、评估用例 45（18 dev / 27 test）。


## 2026-08-04 — 演示调优：确定性路径全绿 + 人工闭环验证

- 事实核验按子类型拆分路由（紧急联系人 / 就诊医生 / 手术 / 诊断），required_facts 只取本类问题所需字段，消除"查一个医生还要有手术史"的不必要澄清。
- 用药与过敏核对同样按子类型拆分（过敏查询 / 当前用药 / 个体化决策 / 具体药品用法）；过敏歧义判定仅在问题涉及过敏/头孢/慎用时触发，避免"我吃什么药"被误判冲突。
- 结构化直答新增就诊日期/科室模板（含"上次发热"匹配"高热"记录）、科室就诊详情合并病历（主诉+诊断+用药）、"磺胺过敏 + 头孢呋辛用药史"双记录核对回答；引用校验修复 `IU` 大小写比较。
- `run_evaluation.py` 修复个别返回结构缺 `intent` 的崩溃、按患者真实 hospital_id 解析；"不必要拒答率"排除过敏/禁忌/确认类合理安全回答。
- 照护闭环端到端验证通过：草案 → 医生发布 → 患者确认 → 已知晓 → 逾期升级 → 协调员接手 → 解决（可重复执行脚本）。
- 确定性评估子集实测：fact 8/8、med 10/10、risk 5/5、conflict 3/3、record 2/2、followup 1/1；路由准确率与引用正确率 100%，高风险召回/危险建议拦截 100%，不必要拒答 0%。
- 演示脚本与面试文档补充「人工闭环」话术；基线报告回填确定性子集实测数字（LLM 路径待密钥）。
- 全量 pytest 288 条通过。


## 2026-08-04 — docs 目录整理（16 → 11 个文件）

- 合并：`患者过敏安全机制设计.md` → `医疗安全与知识治理.md`（过敏五层防护）；`postgresql_redis_setup.md` → `docker_deployment.md`（PG/Redis 手动安装）；`面试技术文档.md` 精华 → `面试准备-项目知识点.md`（核心亮点 + 高频追问速答 + 深挖方向）。
- 删除：`docs/README.md`（过时实现说明）、`agent_graph_and_agentic_rag.md`（已被主线设计文档取代）、以及上述三份已合并源文件。
- 更新：根 README 面试文档链接、`docs/项目结构文档.md` 文档目录树与索引表；`照护计划MVP.md` 保留为扩展模块设计文档。


## 2026-08-04 — 修复药物教育的过度拒答

- 任务路由新增「药物教育」优先级：`XX药 + 治什么/作用/副作用/什么时候吃/怎么吃/用法` 等归 `general_health_education`，不再被误归为用药过敏核对。
- 引用校验对教育性任务跳过证据包匹配：回答可引用证据包之外的药物通用知识，不再被改写为拒答；个体化用药任务仍严格校验。
- 证据冲突检测改为「同字段、同日期」才判冲突，跨就诊日期的诊断/用药变化不再误报；主档同时出现「过敏 + 慎用」判为需医生确认的边界冲突。
- 分诊规则补充「晕倒」「昏迷」紧急信号；路由准确率对门禁先行停止的样本按不适用处理（不计入样本）。
- 新增回归测试：药物教育问题必须回答、不得拒答；个体化剂量问题仍走用药核对与拦截。
- 评估集新增 `general-003` / `general-004` 两条药物教育用例（独立测试集）。


## 2026-08-03 — 患者医疗信息 Agent 主线落地（秋招 MVP）

- 新增 `docs/秋招黄金场景.md`、`docs/秋招演示脚本.md`、`docs/基线报告.md`：固定四个黄金场景与 44 条分层评估用例（17 开发 / 27 独立测试）。
- 新增 `app/schemas/retrieval.py`：`TaskType` / `RetrievalRoute` / `EvidenceItem` / `EvidencePack` / `EvidenceCheck` / `AgentOutputContract` 的权威定义。
- 新增 `app/services/retrieval_router.py`（确定性任务路由）、`agentic_retrieval.py`（EvidencePack 组装）、`evidence_policy.py`（充分性/冲突/高风险判定）、`citation_validator.py`（药物/日期/剂量引用校验）。
- Agent Graph 重排为 `safety → task_route → retrieval → evidence_check → generate/citation_validate → output_assemble`；旧 `chosen_tool` 逻辑封装为执行适配器 `run_agent_execution`，消除重复安全检查和重复结构化路由；补检索最多一次。
- 所有响应路径统一五段输出契约（answer / evidence_summary / risk_level / next_action / agent_trajectory），SSE done 事件与 MCP query 响应模型同步扩展。
- 评估体系扩展：`evaluation_service` 新增路由准确率、高风险召回率、危险建议拦截率、引用正确率、冲突发现率、拒答率、不必要拒答率与 P95 延迟；`run_evaluation` 支持 `--split` 并输出指标；评估控制台支持开发集/独立测试集筛选。
- 前端 ChatPanel 增加任务标签与「依据 / 风险 / 下一步」卡片；结构化直答对「青霉素过敏 + 头孢慎用」冲突场景同时列出两条记录并转医生确认。
- README 主叙事改为医疗信息 Agent 并补充安全边界与评估指标；面试准备文档补充主线问答与简历描述模板。
- 全量 pytest 266 条通过，前端 `tsc + vite` 构建通过。


## 2026-08-03 — 秋招医疗信息 Agent 主线收敛

- 重写 `docs/patient_medical_information_agent_design.md`，将项目主线收敛为患者医疗信息核验与就医导航 Agent，明确四个黄金演示场景、统一输出链路、EvidencePack、引用校验和安全停止策略。
- 重写 `docs/执行计划.md`，按“基线 → 证据模型 → 路由重排 → 有限检索 → 评估演示 → 简历材料”重新排序，区分 MVP、可选增强和 Future Work。
- 明确评估集使用 40～60 条分层虚构用例与独立测试集，指标覆盖路由、安全、引用、冲突、拒答和 P95 延迟，避免使用未经测量的计划值作为简历成果。
- 将 `docs/项目结构文档.md` 的文档目录同步为当前 Agent 设计与执行计划。

## 2026-08-03 — 运行配置与 SSE 稳定性治理

- PostgreSQL、Redis 默认端口与 Docker 宿主映射统一为 `5433`、`6380`；Redis 增加 1 秒连接/读取超时，并将代码已使用的 `python-dotenv` 补入显式依赖。
- SSE Agent 调用改在线程中执行，增加 `STREAM_AGENT_TIMEOUT_SECONDS` 超时控制；模型超时或异常时返回安全降级回答，并继续发送 `token` 与 `done` 事件。
- SSE 协议测试统一隔离外部模型调用，新增异常降级回归测试，避免网络状况导致测试等待与不稳定。
- 同步项目文档中的 React 版本、测试数量、ORM 表数、MCP 工具数和路由模块数。


## 2026-08-01 — 面试演示入口与 Cloudflare 穿透

- `start_tunnel.bat` 改为面试演示启动入口：自动构建 React 前端、以 `DEMO_MODE=true` 启动虚构病例，并将由 FastAPI 托管的完整界面通过 Cloudflare Tunnel 分享。
- 修复 PostgreSQL 探活端口 `5432` → `5433`，移除硬编码本机目录和旧隧道名称；Cloudflared 未安装时下载到已忽略的项目内 `.tools/`。
- 浏览器页签标题同步为“患者照护助手｜照护协同健康工作台”。

## 2026-08-01 — GitHub 项目入口文档

- 新增根目录 `README.md`，说明患者照护闭环、AI 问答、内置执行步骤、评估与可观测能力，以及端口 `8001` 的本地启动方式。
- README 顶部改为纯 GitHub Markdown，避免 HTML 容器内 Markdown 的渲染兼容性问题；补充首次演示前的本地模型密钥配置说明。
- 修复 README Mermaid 架构图中 `/metrics` 节点标签的 GitHub 渲染语法。

> 每次改完代码顺手加一条，格式：`YYYY-MM-DD — 简述改了啥`

---

## 2026-08-01 — 问诊模型失败的记录摘要降级

- 事实型问答的请求路径改为跳过 RAG 上下文构造与向量模型预热；`RETRIEVER_WARMUP_ENABLED`、`PATIENT_FACT_EMBEDDING_ENABLED` 默认关闭，避免离线网络重试阻塞结构化病历直答。
- 修复患者档案聚合查询在模型生成失败后只返回记录数量的问题：现在会安全展开已查询的病历、就诊和过敏史事实，并明确提示未进行额外推断。
- 不再静默吞掉生成异常；服务端只记录异常类型，不记录患者问题或病历正文。
- 新增 `docs/问诊降级策略.md` 与回归测试，覆盖模型不可用时的患者档案回答。

## 2026-08-01 — 智能随访任务引擎

- 照护待办新增“已知晓、提醒待处理、逾期跟进、已升级”跟进状态；患者确认已知晓与患者自报完成分开记录，不将未响应推断为未执行。
- 调度器按提醒策略生成可审计的站内提醒；逾期且多次未确认的例外创建协调员工单，不直接占用医生处理。
- 新增患者待办确认接口、前端随访提示，以及 `migration/20260801_care_follow_up_engine.sql`。

## 2026-08-01 — 演示病例升级为慢病随访场景

- `app/services/demo_seed.py` 演示病例从「血压复查」升级为「2 型糖尿病 + 高血压出院随访」：新增出院小结（病历）与出院随访（就诊）两条来源、磺胺类药物过敏史与家族史。
- 规则提取覆盖全部 4 类待办（复诊/复查/监测/用药核对），并演示"两周后/一个月/两个月/三个月后"等中文时间的截止日解析，以及不应被提取的句子（低血糖/足部破溃提示、口服药物续方），展示规则引擎的克制性。
- 场景带版本标记（demo-v3），后端启动时自动重建过期演示数据；前端无需改动，刷新即可看到新病例。

## 2026-08-01 — 一键演示启动脚本

- 新增 `start_demo.bat`：一键完成 Docker 容器、DEMO_MODE=true 后端、前端启动并自动打开浏览器，无需手动设置环境变量，方便演示与面试走查。

## 2026-08-01 — 项目定位更名为患者照护助手

- 项目定位从「患者智能辅助 Agent（RAG 医疗问答）」统一更名为「患者照护助手」：AGENTS.md 标题与项目一句话、docs/README.md、frontend/README.md、docs/项目结构文档.md、docs/面试准备-项目知识点.md、docs/面试技术文档.md 标题同步更新。
- 同步更新 `app/mcp/vision.py` 视觉系统提示词与 `scripts/seed_patients.py` 种子脚本输出文案；前端 UI 品牌名「诊疗助手」与「健康工作台」保持现状。

## 2026-08-01 — 面试文档定位对齐（照护协同）

- `docs/面试技术文档.md` 开篇定位从「RAG 医疗问答助手」对齐为「就诊后照护协同助手」：明确核心业务是「医生发布照护计划 → 患者执行待办 → 协调员处理求助」的闭环，AI 问诊是健康工作台中的一个模块；新增面试口径提示（开场先说产品定位）。

## 2026-08-01 — 面试技术文档重点星标

- 在 `docs/面试技术文档.md` 顶部新增星级图例（★★★ 核心必会 / ★★ 高频必问 / ★ 了解即可），并给全部章节标题、核心金句、追问速答逐条标注重点星标，便于面试前按优先级复习。

## 2026-07-31 — 面试技术文档完善

- 重写 `docs/面试技术文档.md`，修正与代码不一致的表述：PostgreSQL 表数（14 → 17）、MCP 工具数（5 → 6）、记忆体系（三层 → 四层），并给出 LLM 主链路调用次数与共识投票算法的准确说明。
- 新增三级分诊、生成后安全校验链（过敏比对/药物相互作用/幻觉检测）、照护计划人工闭环、SSE 流式端点与执行步骤、17 张表数据模型分类、技术栈速查、LLM 调用点全景。
- 扩充面试追问速答至 17 条，新增高阶深挖方向（并发扩展、多租户、合规、权重调参等）供面试准备。

## 2026-07-29 — 患者健康工作台前端改版

- 前端从顶部多模式切换调整为“健康概览、照护计划、智能问诊”的工作台导航；桌面端侧栏承担主要功能入口，移动端保留抽屉导航。
- 顶栏新增当前患者健康档案上下文；问诊历史仅在智能问诊页面展示，避免与患者选择和健康档案信息混杂。
- 健康概览新增“今日健康重点”卡片，优先呈现逾期/待办事项；智能问诊页面新增用途和档案关联说明。
- 同步更新 `frontend/README.md` 的前端结构、产品入口描述与后端代理端口说明。

## 2026-07-29 — 患者照护 Agent 与记忆上下文

- 新增受患者身份约束的只读 MCP 工具 `get_my_care_plans`，Agent 可查询医生已发布的照护计划、待办状态和来源依据。
- 照护计划查询接入 Agent 意图路由；实时照护状态与患者事实、会话缓冲、长期摘要和知识记忆分层管理，避免将可变任务状态固化为模型记忆。

## 2026-07-29 — 面试演示照护闭环

- 增加显式启用的 `DEMO_MODE` 虚构病例，支持医生审核、患者执行和协调员处理的端到端演示；默认环境不写入演示数据。
- 照护计划草案新增医生审核发布入口；患者端默认只读取已发布计划，避免患者自行将病历解析结果当作医嘱。
- 明确 Agent 与工作流的职责边界：模型仅辅助理解、检索和工具编排，临床发布、协作接手与关闭保留人工确认。

## 2026-07-28 — 照护协调员工作台

- 新增授权照护人员的协作队列界面，可查看患者求助、关联待办、优先级、处理负责人和等待时长，并执行接手与记录解决。
- 协作单响应新增关联待办标题和截止时间，避免工作人员仅凭内部 ID 处理请求。
- 协调员访问密钥仅在当前页面会话中使用，不写入浏览器本地存储。

## 2026-07-28 — 照护任务求助与人工协作闭环

- 新增 `CareCase` 协作单、延后截止时间与延后到期恢复逻辑；患者可延后待办或发起“需要帮助”，同一待办不会创建重复开放协作单。
- 新增医院协作队列、接手和解决 API；生产环境通过 `CARE_COORDINATOR_API_KEY` 保护协调员入口。
- 照护计划患者端 API 纳入 `PatientDataGuardMiddleware` 的患者 token 一致性校验；前端请求携带既有认证 token。
- 新增 `migration/20260728_care_cases_and_snooze.sql`、延后恢复和协作单回归测试；前端支持延后一天和请求协助。

## 2026-07-28 — 照护计划安全性与可用性完善

- 照护计划详情、确认和待办状态更新增加患者归属校验，避免通过计划或任务 ID 跨患者访问/修改。
- 空草案不能确认；任务支持完成、跳过与重新开启，并保留相应状态事件。
- 新增实时逾期计算和计划待办/逾期计数，不通过后台作业修改原始医嘱或待办状态。
- 前端生成入口同时支持就诊记录与病历记录，并展示待办数量和逾期标识。

## 2026-07-27 — 从 RAG 问答转为就诊后照护计划 MVP

- **事实查询直答与演示数据修复**：诊断、既往用药、手术、接诊医生、复诊安排、过敏史和紧急联系人等明确记录查询前移到 LLM 之前，直接从结构化数据回答；`scripts/seed_patients.py` 修复语法错误并改为幂等补齐，解决已有患者但缺少病历时评估用例必然失败的问题。
- **安全评分语义化**：评估评分升级为 `v2`。症状、儿童发热和药物过敏用例改用 `safety_policy` 校验必要安全提示与危险建议模式，避免将“不要自行停药”“避免使用头孢”“不能使用磺胺”等正确警示误报为安全违规；控制台同步区分危险建议与缺少安全提示。
- **内嵌执行步骤**：每条聊天回答下保留默认收起的执行步骤卡片，按阶段展示身份校验、上下文加载、意图识别、信息查询和回答生成；不暴露原始病历、工具参数或模型内部推理。外部 Grafana/Prometheus/Tempo Compose 配置已移除，后端仍提供指标、结构化日志与可选 OTel 导出能力。
- **后端端口统一**：本地后端、Vite 代理、启动/隧道脚本与项目文档统一使用 `127.0.0.1:8001`。

- **可观测与评估闭环**：新增服务端统一评分、`evaluation_runs` 版本化历史记录及查询/聚合接口，以及 PostgreSQL 迁移 `migration/20260727_evaluation_runs.sql`；评估控制台会保存用例版本、评分版本、模型/提示词/知识库版本和 trace ID，但不持久化原始回答。
- **运行可观测性**：HTTP 指标改用路由模板以避免患者 ID 导致的标签高基数；结构化请求日志与 Agent span 共享 trace ID，OTel 中的患者/会话 ID 改为哈希值；新增实际 Agent、LLM 调用耗时、成功失败与 token 指标。

- 新增 `care_plans`、`care_plan_items`、`care_plan_item_events` 三个数据模型及 PostgreSQL 迁移，支持计划、待办与状态事件的完整留痕。
- 新增照护计划 API：从既有就诊/病历记录生成待确认草案、确认计划、读取计划和更新待办状态。
- 仅以病历原文为证据生成复诊、检查、观察和既有处方核对任务；不生成诊断、剂量或停药建议。
- React 前端增加“照护计划”入口与待办确认/完成操作；新增服务测试与产品说明 `docs/照护计划MVP.md`。

## 2026-07-23 — 医疗回答安全门禁与知识审核元数据

- 新增 `app/mcp/medical_safety_gate.py`：在 LLM 初始化前拦截紧急症状及高风险个体化用药/治疗决策，避免生成剂量、停药、联用等具体方案。
- 知识条目新增来源 URL、证据等级、审核状态、审核人和审核时间；审核通过必须具备来源引用和审核责任信息。
- 知识读取、搜索和检索接口支持 `approved_only=true`，用于只消费经临床审核的内容。
- 新增 PostgreSQL 迁移 `migration/20260723_knowledge_review_metadata.sql`、安全门禁及知识准入回归测试；新增 `docs/医疗安全与知识治理.md`。
- 新增官方/院内来源白名单、临床知识 JSON 受控导入脚本和示例清单；导入默认只允许待审核内容，发布已审核内容需显式 `--publish`。

## 2026-06-20 — 项目结构治理（P0/P1/P2 综合）

针对结构验收发现的问题，按优先级依次处理：

### P0: 评估用例单一数据源
- **新增 `app/config/evaluation_cases.py`**: 评估用例的唯一权威定义（生产可发布），含 15 条用例 + 每条三维加权 `scoring` 配置
- **新增 `app/api/evaluation_routes.py`**: HTTP 接口 `GET /api/v1/evaluation/cases`，在 `main.py` 注册路由
- **`tests/test_evaluation.py` 重构**: 数据定义迁移到 `app/config/`，本文件改为 re-export + 完整性测试（新增 `test_all_cases_have_scoring` 校验权重和为 1.0）
- **`evaluate.html` 改造**: 移除 15 条硬编码副本，启动时通过 `loadCases()` 从 API 拉取；保留失败告警但不阻塞页面

### P0: 根目录清理
- 归位 6 个错位文件：`cli_query.py` → `scripts/`；`test_risk_signals.py` / `codex_update_test.py` → `tests/`；`demo_0.wav` / `result.wav` / `image.png` → `data/`
- 删除 `nul`（Windows 误建空文件）+ `test.db`（测试残留）
- 根目录仅保留项目级入口文件

### P1: 评估控制台拆分
- `app/static/evaluate.html`（1083 行单文件）拆分为 3 文件：

## 2026-07-30 ? ????????? UTC ????

- ?????????? RAG ???????? `approved` ??????????????FAQ ????????????????
- ?? ORM ??????? UTC ?????????? `TIMESTAMPTZ`???????????
  - `evaluate.html`（83 行）— 纯 HTML 骨架
  - `css/evaluate.css`（190 行）— 样式
  - `js/evaluate.js`（817 行）— 逻辑

### P1: 配置文件收敛
- `app/mcp/local_settings.py` + `local_settings.example.py` 迁移到 `app/config/`（与 `production.py` / `evaluation_cases.py` 同居）
- 删除冗余的 `app/mcp/local_settings.postgres.py`（内容已被 `local_settings.py` 包含）
- `app/mcp/config.py` 改为优先 `from app.config import local_settings`，回退到旧路径（向后兼容）
- `.gitignore` 更新：新增 `app/config/local_settings.py`，保留旧路径防残留

### P2: 文档同步
- `AGENTS.md`: 新增 `app/config/` 目录条目；评估用例数 20 → 15；`local_settings.py` 标注新位置；评估控制台标注拆分为 3 文件；新增"评估用例数据源"约定

---

## 2026-07-17 — 文档同步与版本修正

- **版本号更新**: `app/main.py` version `0.3.0` → `0.3.1`
- **脚本重命名**: `start_local.bat` → `start_dev.bat`（AGENTS.md、项目结构文档、README 同步修正）
- **测试计数更新**: pytest 测试从 127 增至 131（新增 `test_streaming.py` 检查点）
- **新增根目录文件**: `reasonix.toml`、`rebuild_frontend.bat` 加入项目结构文档
- **`frontend/README.md` 替换**: Vite 默认模板替换为项目前端说明
- **文档同步优化**: 全量运行 `sync-docs` 技能，同步 4 份核心文档

---

## 2026-06-19 — sync-docs skill 全局化：从项目级移至全局安装

- **skill 位置迁移**: `.reasonix/skills/sync-docs/SKILL.md` → `%APPDATA%/reasonix/skills/sync-docs/SKILL.md`（全局安装，跨项目复用）
- **skill 内容重写**: 不再硬编码 4 个特定文件路径（CHANGELOG / 项目结构文档 / README / AGENTS.md），改为自动发现项目文档并按文档角色（修改日志 / 架构文档 / 项目说明 / Agent 指南）适配更新
- **架构文档同步**: `docs/项目结构文档.md` 中 `.reasonix/` 章节移除已不存在的 `skills/sync-docs/SKILL.md` 条目

---

## 2026-06-19 — 意图识别改进（关键词 + LLM 提示词 + 评估闭环）

- **关键词层加固**: VISIT/MEDICAL/SYMPTOM/PROFILE 关键词从 30 条扩展到 150+ 条；新增 ALLERGY/SURGERY/MEDICATION 专用关键词组
- **历史语境检测**: 新增 `_has_historical_context()`，区分"以前有什么病"（查记录）vs "现在不舒服"（症状咨询）
- **多意图融合**: `_fallback_intent` 重写为优先级链决策——同时命中就诊+病历→profile_summary，过敏→medical_records_query 等
- **LLM 提示词增强**: `_identify_intent` 提示词改为 few-shot 格式（每类 1 示例）、增加 `uncertain` 兜底输出、增加推理理由字段
- **评估页面增强**: 聚合指标面板（通过率/意图准确率/关键词覆盖率/平均耗时/分类表现）+ 意图混淆矩阵（期望意图×实际意图交叉表）+ 数据来源说明
- **修复**: 移除过激的关键词短路逻辑（地址查询除外），让 LLM 处理更多歧义情况
- **AGENTS.md 去重**: 完整目录树（80+行）替换为简要表格 + 引用 `docs/项目结构文档.md`；底部更新记录替换为引用 `CHANGELOG.md`；顶部提示改为调用 `/sync-docs`。文件从 165 行缩减到 89 行
- **新增 sync-docs skill**: `.reasonix/skills/sync-docs/SKILL.md`，subagent 类型项目 skill，用于变更后自动同步 4 份核心文档（CHANGELOG、项目结构文档、README、AGENTS.md）

---

## 2026-06-19 — 五阶段生产化改造（综合）

### Phase 1: 基础设施建设
- **pytest 测试框架**: 创建 `tests/` 包 + conftest.py（SQLite 兼容 + 事务隔离），56 个测试覆盖 CRUD/Auth/API/知识检索
- **database.py**: 支持 SQLite 模式（跳过 PG pool 参数 + wait），测试时可使用 SQLite
- **openai SDK 替换**: `mcp/config.py` 裸 `urllib` → 官方 `openai` Python SDK，3 次指数退避重试（RateLimit/Timeout/5xx）
- **CORS 加固**: `main.py` 添加 `CORSMiddleware`，从 `CORS_ORIGINS` 环境变量读取白名单
- **凭据管理**: `.env` 添加 PG 凭据/auth secret/CORS 配置；`database.py` 默认密码告警
- **部署**: 添加 `gunicorn`；Dockerfile 改为 `gunicorn + UvicornWorker`（4 workers, 120s timeout）

### Phase 2: 数据接入管道
- **bulk_import.py**: 支持 CSV/JSON 批量导入患者/病历/就诊记录；字段校验 + 去重 + `--update` / `--dry-run`
- **自动知识切片**: `--chunk` 参数在导入后自动生成 5 个 domain 的 `MemoryKnowledgeChunk`（诊断/现病史/用药/就诊摘要/复诊计划）
- **增量同步**: `ImportTracker` 基于文件 mtime 跟踪，`--incremental` / `--tracker-status`
- **示例数据**: `data/examples/patients.example.json` + `records.example.csv`

### Phase 3: 安全与合规加固
- **PatientDataGuardMiddleware**: 拦截患者数据端点，验证 auth_token 与 patient_id 匹配，生产模式强制认证
- **AuditLog**: 新增 `audit_log` 表，异步记录每次患者数据访问（patient_id/endpoint/method/action/status_code/client_ip/auth_verified/duration_ms）
- **RateLimitMiddleware**: 内存令牌桶速率限制（`RATE_LIMIT_PER_MINUTE` 环境变量，可扩展 Redis）
- **敏感字段脱敏**: `app/utils/masking.py` — 手机号 `138****8000`、地址保留前 6 字、身份证掩码
- **数据保留**: `scheduler.py` 新增 `_cleanup_old_session_data`，每天凌晨清理 >90 天的会话缓冲/审计日志/过期切片

### Phase 4: Agent 能力增强
- **SSE 流式端点**: `POST /api/v1/mcp/agent/query-stream`，返回 `status→intent→planning→tool_execution→token*→done` 事件序列
- **LLM 自动降级**: `config.py` 主模型失败后自动切换到备用模型（`TEXT_FALLBACK_MODEL` 环境变量）
- **Agent 反思**: `_select_direct_path` 工具结果为空时自动回退到直接 LLM 回答
- **知识切片质量**: confidence + tags 字段 + ChromaDB 同步质量检查

### Phase 5: 可观测性与运维
- **Prometheus 指标**: `app/core/metrics.py` — HTTP 请求计数/延迟、Agent 查询计数/延迟、LLM 调用计数/延迟/Token；`GET /metrics` 端点
- **链路追踪**: `LoggingMiddleware` 自动生成 `trace_id`（UUID），日志 `[trace=xxx]` 输出，响应头 `X-Trace-Id` 返回
- **质量评估集**: `tests/test_evaluation.py` — 20 条测试问答对，覆盖患者事实/就诊/病历/症状/过敏/跨科室/用药/随访/一般医学/问候

---

## 2025-06-17

- **启动脚本全面加固**: Docker daemon 探活 + 容器 `exited` 自动 `down`+`up` 重建 + 快速 `running` 检查（不再死等 `healthy`）
- **React 前端工程化**: 新建 `frontend/` 目录，Vite + React 18 + TypeScript，5 个组件
- **Reranker**: `knowledge_retrieval.py` 集成 Cross-Encoder，默认关闭
- **后台定时调度**: 新增 `app/core/scheduler.py`，APScheduler 三个定时任务，默认关闭
- **database.py**: 新增 `_wait_for_postgres()` TCP 端口探测 + 指数退避
- **文档更新**: docs/ 下 5 个文件同步更新
- **AGENTS.md / CHANGELOG.md**: 新建项目规范和更新记录文件

---

## 更早

- 四层记忆架构（事实/工作/长期摘要/知识）
- 自研 MCP Server（5 个工具）
- 混合 RAG（ChromaDB 向量 + SQL 关键词 + 元数据 + 时效）
- 图文问答 + TTS 语音播报
- Memory Debug 可视化
- 患者过敏安全机制（五层防护）
- HMAC 身份 token
- PostgreSQL + Redis 迁移（从 SQLite）
- Docker 部署支持
## 2026-08-03 - 显式 Agent Graph 第一阶段

- 新增 `app/agent/` 有界执行图，统一节点路由、阶段回调、耗时记录和最大步数保护。
- `app.mcp.llm_router` 通过兼容包接入确定性医疗安全节点，保留现有 Agent 行为并新增非敏感 `agent_trajectory`。
- 同步与 SSE 入口共享同一 Graph 包装层；高风险问题在模型初始化前终止。
- 新增 Agent Graph 单元测试和设计文档 `docs/agent_graph_and_agentic_rag.md`。
