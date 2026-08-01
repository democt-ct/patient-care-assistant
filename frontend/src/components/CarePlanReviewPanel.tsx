import { useEffect, useState } from 'react';
import { useAppState } from '../context/AppContext';
import { carePlanApi } from '../services/api';
import type { CarePlan } from '../types';

export function CarePlanReviewPanel() {
  const { state, dispatch } = useAppState();
  const [plans, setPlans] = useState<CarePlan[]>([]);
  const [clinicianId, setClinicianId] = useState('doctor-demo');
  const [clinicianKey, setClinicianKey] = useState('');
  const [note, setNote] = useState('已核对原始随访计划，允许向患者发布。');
  const [loading, setLoading] = useState(false);
  const [publishingId, setPublishingId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      setPlans(await carePlanApi.listReviewQueue(state.hospitalId, clinicianKey || undefined));
    } catch (error) {
      dispatch({ type: 'SET_ERROR', payload: (error as Error).message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [state.hospitalId]);

  const publish = async (plan: CarePlan) => {
    if (!clinicianId.trim()) {
      dispatch({ type: 'SET_ERROR', payload: '请填写审核医生标识。' });
      return;
    }
    setPublishingId(plan.id);
    try {
      await carePlanApi.publishPlan(plan.id, state.hospitalId, clinicianId.trim(), note || undefined, clinicianKey || undefined);
      dispatch({ type: 'SET_STATUS', payload: '照护计划已发布给患者。' });
      await load();
    } catch (error) {
      dispatch({ type: 'SET_ERROR', payload: (error as Error).message });
    } finally {
      setPublishingId(null);
    }
  };

  return (
    <section className="care-panel">
      <div className="care-panel-inner coordinator-panel-inner">
        <header className="care-panel-header">
          <div>
            <h2>医生照护计划审核</h2>
            <p>仅审核可追溯到就诊记录的候选待办；发布后患者才能看到。</p>
          </div>
          <button className="btn btn-sm" onClick={() => void load()} disabled={loading}>刷新队列</button>
        </header>
        <section className="coordinator-access">
          <label>院区<input value={state.hospitalId} readOnly /></label>
          <label>审核医生标识<input value={clinicianId} onChange={(event) => setClinicianId(event.target.value)} /></label>
          <label>医生访问密钥（生产环境必填）<input type="password" value={clinicianKey} onChange={(event) => setClinicianKey(event.target.value)} placeholder="不会被保存" /></label>
        </section>
        <label className="coordinator-note">审核备注<textarea value={note} onChange={(event) => setNote(event.target.value)} maxLength={2000} /></label>
        {loading && <div className="care-loading">正在加载待审核计划…</div>}
        {!loading && plans.length === 0 && <div className="care-empty"><p>当前没有待审核的照护计划。</p></div>}
        {plans.map((plan) => (
          <article key={plan.id} className="care-plan-card">
            <header className="care-plan-header">
              <div className="care-plan-title"><span className="care-chip care-chip-warn">待审核</span><strong>{plan.title}</strong></div>
              <button className="btn btn-primary btn-sm" disabled={publishingId === plan.id} onClick={() => void publish(plan)}>审核并发布</button>
            </header>
            <ul className="care-item-list">
              {plan.items.map((item) => (
                <li className="care-item" key={item.id}>
                  <div className="care-item-head"><span className="care-item-title">{item.title}</span><span className="care-chip">{item.task_type}</span></div>
                  {item.instructions && <p className="care-item-instructions">{item.instructions}</p>}
                  <div className="care-item-evidence"><b>来源依据：</b>{item.evidence_excerpt}</div>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  );
}
