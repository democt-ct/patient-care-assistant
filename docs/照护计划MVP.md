# 就诊后照护计划 MVP

项目的主链路由开放式医疗问答调整为“病历事实 → 待确认待办 → 患者跟踪”。聊天仍可作为辅助入口，但不再是唯一主界面。

## 使用流程

1. 患者绑定后，在前端选择“照护计划”。
2. 从一次既有就诊记录生成计划草案。
3. 系统仅从 `follow_up_plan`、`visit_summary`、`treatment_plan`、`notes` 和既有处方中抽取复诊、检查、观察、用药核对等候选任务。
4. 每项任务显示对应病历片段；患者确认计划后，任务才从 `proposed` 转为 `pending`。
5. 患者可标记完成、延后、跳过或请求医院协助，系统写入不可覆盖的状态事件。

计划详情、确认和任务状态更新均需带患者 ID，并按计划/任务的归属校验；空草案不可确认。任务逾期由 `due_at` 与当前时间实时计算，保留原任务状态和原始证据，不以后台任务篡改记录。

患者将任务延后时必须给出未来的 `snoozed_until`。调度器到期后把任务恢复为 `pending`，并写入 `snooze_expired` 事件。患者选择“需要帮助”时，系统创建关联该任务的 `CareCase`；同一任务只有一个未解决协作单。

不会由模型生成新的诊断、处方、剂量或停药建议。处方相关任务只提示按原始医嘱和药师说明核对执行。

## 协作工作台

患者选择“需要帮助”后会创建 `CareCase`。前端的“协作工作台”供院内授权协调员查看同一院区的协作队列，并执行接手与记录解决：

- 队列展示关联待办、优先级、患者说明、当前负责人和已等待时长；不在页面中展示诊断或模型推断。
- 接手和解决操作必须填写处理人员标识；处理备注会持久化到协作单。
- 生产环境请求必须携带 `X-Care-Coordinator-Key`；前端仅临时保留输入值，不写入本地存储。
- “已等待时长”用于工作排序，不等同于临床响应承诺。正式上线前应由医院配置分级 SLA、升级规则和正式人员身份认证。

## Agent 与工作流边界

照护链路采用“Agent 负责理解与编排，工作流负责约束与留痕”的组合：

- **患者照护 Agent** 可解释已发布任务、查询任务依据，并在患者明确确认后调用完成、延期或求助工具；不得生成诊断、处方或剂量调整。
- **医生审核 Agent** 可归纳候选待办及其原始证据，辅助医生核对；只有医生操作“审核并发布”才能使计划对患者可见。
- **协调员 Agent** 可总结求助和队列信息，辅助生成处理摘要；接手与关闭协作单必须由工作人员确认。
- 每个角色的工具集、可访问数据和可写入状态均受权限与状态机约束。模型输出不会直接成为临床决定或不可逆写操作。

患者侧继续沿用既有的“患者事实—会话缓冲—长期摘要—知识记忆”四层记忆。照护计划、待办状态和协作单属于**实时业务上下文**，每次通过受患者身份约束的 MCP 工具 `get_my_care_plans` 查询；它不写入长期记忆，也不以模型记忆替代数据库中的当前状态。

## API

- `POST /api/v1/care-plans/generate`：从一条就诊/病历记录生成草案。
- `GET /api/v1/care-plans?patient_id=...`：读取患者计划。
- `POST /api/v1/care-plans/{id}/confirm`：确认草案。
- `PATCH /api/v1/care-plans/items/{id}`：将任务标记为 `completed`、`skipped` 或恢复为 `pending`。
- `GET /api/v1/care-plans/cases/queue`：医院协调员读取协作队列。
- `POST /api/v1/care-plans/cases/{id}/acknowledge`、`/resolve`：接手或解决协作单。

患者端接口通过现有 `auth_token` 与 `patient_id` 进行一致性校验。协调员队列在生产环境要求设置 `CARE_COORDINATOR_API_KEY`，并使用 `X-Care-Coordinator-Key` 请求头；此密钥应替换为正式医院人员身份系统后再大规模上线。

## 数据和迁移

新增表：`care_plans`、`care_plan_items`、`care_plan_item_events`、`care_cases`。部署 PostgreSQL 前必须依次执行：

```powershell
psql -U postgres -d patient_agent -f migration/20260723_care_plans.sql
psql -U postgres -d patient_agent -f migration/20260728_care_cases_and_snooze.sql
```

旧版知识审核元数据迁移也仍需先执行：`migration/20260723_knowledge_review_metadata.sql`。

## 智能随访任务引擎

计划发布后，每个待办先进入 `awaiting_acknowledgement`：患者可确认“已知晓”，但该动作不会被记作任务完成。患者完成或跳过任务时，系统仅记录为患者自报，并以 `execution_evidence_type` 区分于未来可接入的预约、检查或院内系统核验。

开启 `SCHEDULER_ENABLED=true` 后，定时任务会生成可审计的站内提醒事件：临近到期时提示患者更新状态；逾期且在设定次数的提醒后仍未确认，不把患者直接判定为未执行，而是创建 `unconfirmed_follow_up` 协调员工单。症状异常、用药调整等医疗风险仍应通过独立安全规则和人工流程升级。

当前交付的是站内提醒与状态流转；短信、微信或院内消息仅作为后续可替换的通知通道，不能在未接入时宣称已送达。

部署时在既有照护迁移后执行：

```powershell
psql -U postgres -d patient_agent -f migration/20260801_care_follow_up_engine.sql
```

## 当前边界

- 已实现计划草案、患者确认、完成/跳过/延后/求助、患者归属校验、逾期计算、协作单和来源追溯。
- 设置 `SCHEDULER_ENABLED=true` 后，`SCHEDULER_CARE_PLAN_CHECK_INTERVAL`（默认 30 分钟）控制延后待办的到期恢复检查。
- 尚未接入短信、微信或院内消息通知；后续可在任务到期、逾期和协作单变化时对接这些通道。
- 医疗记录文本解析使用确定性规则，不能抽取的内容宁可不创建任务，避免把推测当作医嘱。
