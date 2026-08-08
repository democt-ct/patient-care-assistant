import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { ACTION_LABELS, ContractCard, NODE_LABELS, RISK_LABELS, TASK_LABELS, TrajectoryView } from './ChatPanel';


describe('输出契约标签映射', () => {
  it('任务类型映射完整', () => {
    expect(TASK_LABELS.fact_verification).toBe('病历事实核验');
    expect(TASK_LABELS.medication_allergy_check).toBe('用药过敏核对');
    expect(TASK_LABELS.risk_triage).toBe('风险分流');
    expect(TASK_LABELS.general_health_education).toBe('一般健康教育');
  });

  it('风险与下一步映射完整', () => {
    expect(RISK_LABELS.routine).toBe('常规');
    expect(RISK_LABELS.urgent).toBe('需关注');
    expect(RISK_LABELS.emergency).toBe('紧急');
    expect(ACTION_LABELS.contact_doctor).toBe('联系医生');
    expect(ACTION_LABELS.emergency_care).toBe('紧急就医');
  });
});


describe('ContractCard 渲染', () => {
  it('渲染任务/风险/下一步/依据', () => {
    render(
      <ContractCard
        message={{
          role: 'assistant',
          content: '回答',
          task_route: { task: 'medication_allergy_check' },
          risk_level: 'urgent',
          next_action: 'contact_doctor',
          evidence_summary: '回答依据：结构化病历与审核知识。',
        }}
      />,
    );

    expect(screen.getByText('用药过敏核对')).toBeTruthy();
    expect(screen.getByText('需关注')).toBeTruthy();
    expect(screen.getByText('联系医生')).toBeTruthy();
    expect(screen.getByText('回答依据：结构化病历与审核知识。')).toBeTruthy();
  });

  it('无契约字段时不渲染', () => {
    const { container } = render(<ContractCard message={{ role: 'assistant', content: '回答' }} />);
    expect(container.querySelector('.contract-card')).toBeNull();
  });
});

describe('思考链路（TrajectoryView）', () => {
  it('节点标签映射完整', () => {
    expect(NODE_LABELS.safety).toBe('安全检查');
    expect(NODE_LABELS.task_route).toBe('任务路由');
    expect(NODE_LABELS.evidence_check).toBe('证据判定');
    expect(NODE_LABELS.citation_validate).toBe('引用校验');
  });

  it('无轨迹时不渲染', () => {
    const { container } = render(<TrajectoryView />);
    expect(container.querySelector('.trajectory-view')).toBeNull();
  });

  it('点击按钮展开逐步流程', () => {
    render(
      <TrajectoryView
        trajectory={[
          { node: 'safety', phase: 'safety', status: 'completed', duration_ms: 12, summary: 'allowed' },
          { node: 'task_route', phase: 'classify', status: 'completed', duration_ms: 8, summary: 'task:general_health_education' },
        ]}
      />,
    );
    const button = screen.getByRole('button', { name: /思考链路/ });
    expect(button).toBeTruthy();
    fireEvent.click(button);
    expect(screen.getByText('安全检查')).toBeTruthy();
    expect(screen.getByText('任务路由')).toBeTruthy();
  });
});
