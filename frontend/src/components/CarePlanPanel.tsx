import { useEffect, useState } from 'react';
import { useAppState } from '../context/AppContext';
import { carePlanApi, patientApi } from '../services/api';
import type { CarePlan, MedicalRecord, VisitRecord } from '../types';

function planStatusLabel(status: string) {
  if (status === 'draft') return '待确认';
  if (status === 'confirmed') return '进行中';
  return status;
}

function itemStatusChip(status: string) {
  switch (status) {
    case 'completed':
      return <span className="care-chip care-chip-success">已完成</span>;
    case 'snoozed':
      return <span className="care-chip care-chip-warn">已延后</span>;
    case 'needs_help':
      return <span className="care-chip care-chip-info">已请求协助</span>;
    default:
      return <span className="care-chip">待处理</span>;
  }
}

export function CarePlanPanel() {
  const { state, dispatch } = useAppState();
  const [plans, setPlans] = useState<CarePlan[]>([]);
  const [visits, setVisits] = useState<VisitRecord[]>([]);
  const [records, setRecords] = useState<MedicalRecord[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    if (!state.patientId) return;
    setLoading(true);
    try {
      const [nextPlans, nextVisits, nextRecords] = await Promise.all([
        carePlanApi.list(state.patientId, state.authToken),
        patientApi.getVisitRecords(state.patientId),
        patientApi.getMedicalRecords(state.patientId),
      ]);
      setPlans(nextPlans);
      setVisits(nextVisits);
      setRecords(nextRecords);
    } catch (error) {
      dispatch({ type: 'SET_ERROR', payload: (error as Error).message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [state.patientId]);

  const generate = async (sourceType: 'visit_record' | 'medical_record', sourceId: string) => {
    try {
      await carePlanApi.generate(state.patientId, sourceType, sourceId, state.authToken);
      await load();
    } catch (error) { dispatch({ type: 'SET_ERROR', payload: (error as Error).message }); }
  };
  const confirm = async (planId: string) => { await carePlanApi.confirm(planId, state.patientId, state.authToken); await load(); };
  const acknowledge = async (itemId: string) => { await carePlanApi.acknowledgeItem(itemId, state.patientId, state.authToken); await load(); };
  const complete = async (itemId: string) => { await carePlanApi.updateItem(itemId, state.patientId, 'completed', undefined, undefined, state.authToken); await load(); };
  const snooze = async (itemId: string) => {
    const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
    await carePlanApi.updateItem(itemId, state.patientId, 'snoozed', '患者延后 1 天', tomorrow, state.authToken);
    await load();
  };
  const requestHelp = async (itemId: string) => {
    await carePlanApi.updateItem(itemId, state.patientId, 'needs_help', '患者请求医院协助', undefined, state.authToken);
    await load();
  };

  if (!state.patientId) {
    return (
      <section className="care-panel">
        <div className="care-empty">
          <div className="care-empty-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
              <line x1="16" y1="2" x2="16" y2="6"/>
              <line x1="8" y1="2" x2="8" y2="6"/>
              <line x1="3" y1="10" x2="21" y2="10"/>
            </svg>
          </div>
          <h2>照护计划</h2>
          <p>请先打开左上角面板绑定患者，再生成就诊后的待办清单。</p>
        </div>
      </section>
    );
  }

  if (!loading && plans.length === 0) {
    return (
      <section className="care-panel">
        <div className="care-empty">
          <div className="care-empty-icon">✓</div>
          <h2>我的照护计划</h2>
          <p>当前没有医院已发布的照护计划。医生审核并发布后，待办会出现在这里。</p>
        </div>
      </section>
    );
  }

  return (
    <section className="care-panel">
      <div className="care-panel-inner">
        <header className="care-panel-header">
          <div>
            <h2>就诊后照护计划</h2>
            <p>每项待办均来自已记录的病历或就诊信息。</p>
          </div>
        </header>

        {loading && (
          <div className="care-loading">
            <div className="typing-indicator"><span /><span /><span /></div>
            正在加载…
          </div>
        )}

        {!plans.length && !loading && (
          <div className="care-empty">
            <p>还没有照护计划。选择一次就诊或病历记录，生成待确认的待办。</p>
            {(visits.length > 0 || records.length > 0) ? (
              <div className="care-generate-groups">
                {visits.length > 0 && (
                  <div className="care-generate-group">
                    <div className="care-generate-label">就诊记录</div>
                    <div className="care-generate-list">
                      {visits.map((visit) => (
                        <button className="care-generate-btn" key={visit.id} onClick={() => void generate('visit_record', visit.id)}>
                          <span className="care-generate-date">{new Date(visit.visit_date).toLocaleDateString()}</span>
                          <span className="care-generate-name">{visit.department || '就诊'}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {records.length > 0 && (
                  <div className="care-generate-group">
                    <div className="care-generate-label">病历记录</div>
                    <div className="care-generate-list">
                      {records.map((record) => (
                        <button className="care-generate-btn" key={record.id} onClick={() => void generate('medical_record', record.id)}>
                          <span className="care-generate-date">{new Date(record.record_date).toLocaleDateString()}</span>
                          <span className="care-generate-name">{record.record_type || '病历'}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <p className="care-empty-hint">该患者暂无就诊或病历记录。</p>
            )}
          </div>
        )}

        {plans.map((plan) => (
          <article key={plan.id} className="care-plan-card">
            <header className="care-plan-header">
              <div className="care-plan-title">
                <span className={`care-chip ${plan.status === 'draft' ? 'care-chip-warn' : 'care-chip-success'}`}>
                  {planStatusLabel(plan.status)}
                </span>
                <strong>{plan.pending_count} 项待办</strong>
                {plan.overdue_count > 0 && (
                  <span className="care-chip care-chip-danger">{plan.overdue_count} 项逾期</span>
                )}
              </div>
              {plan.status === 'draft' && (
                <button className="btn btn-primary btn-sm" onClick={() => void confirm(plan.id)}>确认计划</button>
              )}
            </header>

            {plan.items.length === 0 && (
              <p className="care-plan-note">原始记录中未提取到可确认的待办，请查看原始医嘱。</p>
            )}

            <ul className="care-item-list">
              {plan.items.map((item) => (
                <li key={item.id} className={`care-item ${item.status === 'completed' ? 'care-item-done' : ''}`}>
                  <div className="care-item-head">
                    <span className={`care-item-check ${item.status === 'completed' ? 'checked' : ''}`}>
                      {item.status === 'completed' && (
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                          <polyline points="20 6 9 17 4 12"/>
                        </svg>
                      )}
                    </span>
                    <span className="care-item-title">{item.title}</span>
                    {itemStatusChip(item.status)}
                  </div>

                  {item.instructions && <p className="care-item-instructions">{item.instructions}</p>}

                  <div className="care-item-meta">
                    {item.needs_patient_confirmation && (
                      <span className="care-item-follow-up">请先确认已知晓这项安排；确认不代表已经完成。</span>
                    )}
                    {item.follow_up_status === 'reminder_due' && (
                      <span className="care-item-follow-up">系统提醒：请确认当前执行情况，或选择延期、求助。</span>
                    )}
                    {item.follow_up_status === 'follow_up_needed' && (
                      <span className="care-item-follow-up overdue">该任务已逾期且尚未确认完成，请更新执行情况。</span>
                    )}
                    {item.follow_up_status === 'escalated' && (
                      <span className="care-item-follow-up">已转入医院协调跟进，不代表系统判断为未执行。</span>
                    )}
                    {item.due_at && (
                      <span className={`care-item-due ${item.is_overdue ? 'overdue' : ''}`}>
                        建议时间：{new Date(item.due_at).toLocaleDateString()}{item.is_overdue ? '（已逾期）' : ''}
                      </span>
                    )}
                    {item.is_snoozed && item.snoozed_until && (
                      <span>已延后至 {new Date(item.snoozed_until).toLocaleString()}</span>
                    )}
                    {item.status === 'needs_help' && (
                      <span>已提交医院协助请求，等待处理。</span>
                    )}
                  </div>

                  {item.evidence_excerpt && (
                    <blockquote className="care-item-evidence">依据：{item.evidence_excerpt}</blockquote>
                  )}

                  {item.status === 'pending' && (
                    <div className="care-item-actions">
                      {item.needs_patient_confirmation && (
                        <button className="btn btn-primary btn-sm" onClick={() => void acknowledge(item.id)}>我已知晓</button>
                      )}
                      <button className="btn btn-sm" onClick={() => void complete(item.id)}>标记完成</button>
                      <button className="btn btn-sm" onClick={() => void snooze(item.id)}>延后 1 天</button>
                      <button className="btn btn-sm btn-ghost" onClick={() => void requestHelp(item.id)}>需要帮助</button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  );
}
