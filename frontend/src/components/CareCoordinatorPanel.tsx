import { useEffect, useMemo, useState } from 'react';
import { useAppState } from '../context/AppContext';
import { carePlanApi } from '../services/api';
import type { CareCase } from '../types';

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'open', label: '待接手' },
  { value: 'acknowledged', label: '处理中' },
  { value: 'resolved', label: '已解决' },
];

function statusLabel(status: string) {
  if (status === 'open') return '待接手';
  if (status === 'acknowledged') return '处理中';
  if (status === 'resolved') return '已解决';
  return status;
}

function waitingLabel(createdAt: string) {
  const elapsedMinutes = Math.max(0, Math.floor((Date.now() - new Date(createdAt).getTime()) / 60_000));
  if (elapsedMinutes < 60) return `已等待 ${elapsedMinutes} 分钟`;
  const hours = Math.floor(elapsedMinutes / 60);
  if (hours < 24) return `已等待 ${hours} 小时`;
  return `已等待 ${Math.floor(hours / 24)} 天`;
}

export function CareCoordinatorPanel() {
  const { state, dispatch } = useAppState();
  const [cases, setCases] = useState<CareCase[]>([]);
  const [statusFilter, setStatusFilter] = useState('open');
  const [assigneeId, setAssigneeId] = useState('coordinator-demo');
  const [coordinatorKey, setCoordinatorKey] = useState('');
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(false);
  const [submittingCaseId, setSubmittingCaseId] = useState<string | null>(null);

  const summary = useMemo(() => ({
    open: cases.filter((item) => item.status === 'open').length,
    acknowledged: cases.filter((item) => item.status === 'acknowledged').length,
  }), [cases]);

  const load = async () => {
    if (!state.hospitalId) return;
    setLoading(true);
    try {
      setCases(await carePlanApi.listCases(state.hospitalId, statusFilter || undefined, coordinatorKey || undefined));
    } catch (error) {
      dispatch({ type: 'SET_ERROR', payload: (error as Error).message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [state.hospitalId, statusFilter]);

  const updateCase = async (careCase: CareCase, action: 'acknowledge' | 'resolve') => {
    if (!assigneeId.trim()) {
      dispatch({ type: 'SET_ERROR', payload: '请填写处理人员标识后再提交。' });
      return;
    }
    setSubmittingCaseId(careCase.id);
    try {
      if (action === 'acknowledge') {
        await carePlanApi.acknowledgeCase(careCase.id, state.hospitalId, assigneeId.trim(), note || undefined, coordinatorKey || undefined);
        dispatch({ type: 'SET_STATUS', payload: '已接手该照护协作请求。' });
      } else {
        await carePlanApi.resolveCase(careCase.id, state.hospitalId, assigneeId.trim(), note || undefined, coordinatorKey || undefined);
        dispatch({ type: 'SET_STATUS', payload: '已记录该照护协作请求的处理结果。' });
      }
      setNote('');
      await load();
    } catch (error) {
      dispatch({ type: 'SET_ERROR', payload: (error as Error).message });
    } finally {
      setSubmittingCaseId(null);
    }
  };

  return (
    <section className="care-panel">
      <div className="care-panel-inner coordinator-panel-inner">
        <header className="care-panel-header">
          <div>
            <h2>照护协调员工作台</h2>
            <p>处理患者发起的协助请求；仅限已获授权的院内照护人员使用。</p>
          </div>
          <button className="btn btn-sm" onClick={() => void load()} disabled={loading}>刷新队列</button>
        </header>

        <section className="coordinator-access" aria-label="协作队列访问设置">
          <label>
            院区
            <input value={state.hospitalId} readOnly aria-readonly="true" />
          </label>
          <label>
            处理人员标识
            <input value={assigneeId} onChange={(event) => setAssigneeId(event.target.value)} placeholder="如 nurse-001" />
          </label>
          <label>
            协调员访问密钥（生产环境必填）
            <input type="password" value={coordinatorKey} onChange={(event) => setCoordinatorKey(event.target.value)} placeholder="不会被保存" autoComplete="off" />
          </label>
        </section>

        <div className="coordinator-summary" aria-label="队列摘要">
          <span className="care-chip care-chip-danger">待接手 {summary.open}</span>
          <span className="care-chip care-chip-info">处理中 {summary.acknowledged}</span>
          <span className="coordinator-total">当前列表 {cases.length} 条</span>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="按状态筛选协作单">
            {STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </div>

        <label className="coordinator-note">
          本次处理备注（会写入协作单）
          <textarea value={note} onChange={(event) => setNote(event.target.value)} maxLength={2000} placeholder="例如：已联系患者，协助预约复诊。" />
        </label>

        {loading && <div className="care-loading">正在加载协作队列…</div>}
        {!loading && cases.length === 0 && <div className="care-empty"><p>当前筛选条件下没有照护协作请求。</p></div>}

        <div className="coordinator-case-list">
          {cases.map((careCase) => {
            const busy = submittingCaseId === careCase.id;
            return (
              <article key={careCase.id} className="coordinator-case-card">
                <div className="coordinator-case-head">
                  <div>
                    <strong>{careCase.care_plan_item_title || '患者照护待办'}</strong>
                    <div className="coordinator-case-meta">
                      <span>{waitingLabel(careCase.created_at)}</span>
                      {careCase.care_plan_item_due_at && <span>待办截止：{new Date(careCase.care_plan_item_due_at).toLocaleString()}</span>}
                      {careCase.assignee_id && <span>当前负责人：{careCase.assignee_id}</span>}
                    </div>
                  </div>
                  <div className="coordinator-case-chips">
                    <span className={`care-chip ${careCase.priority === 'high' ? 'care-chip-danger' : 'care-chip-warn'}`}>{careCase.priority === 'high' ? '高优先级' : '常规'}</span>
                    <span className={`care-chip ${careCase.status === 'resolved' ? 'care-chip-success' : careCase.status === 'acknowledged' ? 'care-chip-info' : 'care-chip-warn'}`}>{statusLabel(careCase.status)}</span>
                  </div>
                </div>
                <div className="coordinator-case-detail"><b>请求原因：</b>{careCase.reason}</div>
                {careCase.patient_note && <div className="coordinator-case-detail"><b>患者说明：</b>{careCase.patient_note}</div>}
                {careCase.coordinator_note && <div className="coordinator-case-detail"><b>既有处理记录：</b>{careCase.coordinator_note}</div>}
                {careCase.status !== 'resolved' && (
                  <div className="care-item-actions">
                    {careCase.status === 'open' && <button className="btn btn-sm" disabled={busy} onClick={() => void updateCase(careCase, 'acknowledge')}>接手处理</button>}
                    <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => void updateCase(careCase, 'resolve')}>记录解决</button>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
