import { useEffect, useState } from 'react';
import { useAppState } from '../context/appStateContext';
import { memoryApi, patientApi } from '../services/api';

interface DashboardStats {
  medicalRecords: number;
  visitRecords: number;
  sessions: number;
}

function greeting() {
  const hour = new Date().getHours();
  if (hour < 6) return '夜深了';
  if (hour < 12) return '早上好';
  if (hour < 14) return '中午好';
  if (hour < 18) return '下午好';
  return '晚上好';
}

export function DashboardPanel() {
  const { state, dispatch } = useAppState();
  const [statsSnapshot, setStatsSnapshot] = useState<{
    patientId: string;
    stats: DashboardStats;
  } | null>(null);
  const stats = statsSnapshot?.patientId === state.patientId ? statsSnapshot.stats : null;

  const goChat = (mode: 'general' | 'memory') => {
    dispatch({ type: 'SET_CHAT_MODE', payload: mode });
    dispatch({ type: 'SET_VIEW', payload: 'chat' });
  };

  useEffect(() => {
    if (!state.patientId) return;
    const patientId = state.patientId;
    let cancelled = false;
    Promise.all([
      patientApi.getMedicalRecords(patientId),
      patientApi.getVisitRecords(patientId),
      memoryApi.getSessions(patientId),
    ])
      .then(([medicalRecords, visitRecords, sessions]) => {
        if (!cancelled) {
          setStatsSnapshot({
            patientId,
            stats: {
              medicalRecords: medicalRecords.length,
              visitRecords: visitRecords.length,
              sessions: sessions.length,
            },
          });
        }
      })
      .catch((error) => {
        if (!cancelled) dispatch({ type: 'SET_ERROR', payload: (error as Error).message });
      });
    return () => { cancelled = true; };
  }, [state.patientId, dispatch]);

  if (!state.patientId) {
    return (
      <section className="dash-panel">
        <div className="dash-inner">
          <div className="dash-hero">
            <div className="dash-hero-icon">✦</div>
            <span className="dash-eyebrow">患者医疗信息 Agent</span>
            <h1>{greeting()}，先把医疗信息弄明白</h1>
            <p>它可以解释已授权的病历、检查和既有医嘱，帮助准备就诊问题；不代替医生诊断或开药。</p>
          </div>
          <div className="dash-actions-grid">
            <button className="dash-action-card" onClick={() => goChat('general')}>
              <div className="dash-action-icon">?</div>
              <strong>咨询医疗信息</strong>
              <span>获得通用健康知识、风险提醒和下一步就医建议。</span>
            </button>
            <button className="dash-action-card" onClick={() => goChat('memory')}>
              <div className="dash-action-icon">⌕</div>
              <strong>绑定健康档案</strong>
              <span>在左侧搜索并选择患者后，可结合病历和就诊记录回答。</span>
            </button>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="dash-panel">
      <div className="dash-inner">
        <header className="dash-header">
          <div>
            <h1>{greeting()}{state.profileName ? `，${state.profileName}` : ''}</h1>
            <p>已绑定健康档案。可以询问病历含义、既往就诊情况，或准备下一次就医沟通。</p>
          </div>
          <button className="btn btn-primary" onClick={() => goChat('memory')}>向 Agent 提问</button>
        </header>

        <section className="dash-priority-card" aria-label="Agent 使用边界">
          <div className="dash-priority-icon">i</div>
          <div>
            <span>使用边界</span>
            <strong>回答以已授权档案和已审核知识为依据；出现紧急危险信号时会提示立即线下就医。</strong>
          </div>
        </section>

        <div className="dash-stats-grid">
          <button className="dash-stat-card" onClick={() => goChat('memory')}>
            <span className="dash-stat-value">{stats ? stats.medicalRecords : '…'}</span>
            <span className="dash-stat-label">病历记录</span>
          </button>
          <button className="dash-stat-card" onClick={() => goChat('memory')}>
            <span className="dash-stat-value">{stats ? stats.visitRecords : '…'}</span>
            <span className="dash-stat-label">就诊记录</span>
          </button>
          <button className="dash-stat-card" onClick={() => goChat('memory')}>
            <span className="dash-stat-value">{stats ? stats.sessions : '…'}</span>
            <span className="dash-stat-label">历史对话</span>
          </button>
        </div>

        <div className="dash-columns">
          <div className="dash-card">
            <div className="dash-card-header"><h3>可以这样问</h3></div>
            <div className="dash-quick-list">
              <button className="dash-quick-item" onClick={() => goChat('memory')}><div><strong>我的病历写了什么？</strong><span>汇总已授权档案中的诊断、既往用药或过敏信息。</span></div></button>
              <button className="dash-quick-item" onClick={() => goChat('memory')}><div><strong>上次就诊后要注意什么？</strong><span>基于既有记录梳理医嘱，并提示需要向医生确认的部分。</span></div></button>
              <button className="dash-quick-item" onClick={() => goChat('memory')}><div><strong>下次就诊我该问什么？</strong><span>将当前困扰整理成适合与医生沟通的问题清单。</span></div></button>
            </div>
          </div>
          <div className="dash-card">
            <div className="dash-card-header"><h3>回答如何产生</h3></div>
            <p className="dash-card-empty">Agent 会先核验身份与上下文，再查询患者档案或检索已审核知识；无法确定时会明确说明边界，而不是虚构结论。</p>
            <button className="btn btn-ghost btn-sm" onClick={() => goChat('general')}>查看通用医疗知识 →</button>
          </div>
        </div>
      </div>
    </section>
  );
}
