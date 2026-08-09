export const NODE_LABELS: Record<string, string> = {
  safety: '安全检查',
  task_route: '任务路由',
  clarify: '症状澄清',
  symptom_assessment: '症状评估与建议',
  retrieval: '证据检索',
  generate: '回答生成',
  evidence_check: '证据判定',
  citation_validate: '引用校验',
  output_assemble: '输出装配',
};

export const TASK_LABELS: Record<string, string> = {
  fact_verification: '病历事实核验',
  medication_allergy_check: '用药过敏核对',
  report_comprehension: '报告理解',
  longitudinal_comparison: '纵向比较',
  risk_triage: '风险分流',
  visit_preparation: '就医准备',
  general_health_education: '一般健康教育',
};

export const RISK_LABELS: Record<string, string> = {
  routine: '常规',
  urgent: '需关注',
  emergency: '紧急',
};

export const ACTION_LABELS: Record<string, string> = {
  continue_supplement: '补充信息',
  monitor_symptoms: '观察症状',
  view_records: '查看记录',
  contact_doctor: '联系医生',
  emergency_care: '紧急就医',
};
