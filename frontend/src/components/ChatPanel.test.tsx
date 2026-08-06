import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { ACTION_LABELS, ContractCard, RISK_LABELS, TASK_LABELS } from './ChatPanel';


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
