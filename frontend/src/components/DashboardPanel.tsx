import { useEffect, useState } from 'react';
import { useAppState } from '../context/AppContext';
import { carePlanApi, memoryApi, patientApi } from '../services/api';
import type { CarePlanItem } from '../types';

interface DashboardStats {
  pending: number;
  overdue: number;
  medicalRecords: number;
  visitRecords: number;
  sessions: number;
}

interface PendingItem extends CarePlanItem {
  planId: string;
}

function greeting() {
  const h = new Date().getHours();
  if (h < 6) return '夜深了';
  if (h < 12) return '早上好';
  if (h < 14) return '中午好';
  if (h < 18) return '下午好';
  return '晚上好';
}

export function DashboardPanel() {
  const { state, dispatch } = useAppState();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [pendingItems, setPendingItems] = useState<PendingItem[]>([]);

  const goChat = (mode: 'general' | 'memory') => {
    dispatch({ type: 'SET_CHAT_MODE', payload: mode });
    dispatch({ type: 'SET_VIEW', payload: 'chat' });
  };

  useEffect(() => {
    if (!state.patientId) return;
    let cancelled = false;
    Promise.all([
      carePlanApi.list(state.patientId, state.authToken),
      patientApi.getMedicalRecords(state.patientId),
      patientApi.getVisitRecords(state.patientId),
      memoryApi.getSessions(state.patientId),
    ])
      .then(([plans, records, visits, sessions]) => {
        if (cancelled) return;
        const pending = plans.reduce((n, p) => n + p.pending_count, 0);
        const overdue = plans.reduce((n, p) => n + p.overdue_count, 0);
        setStats({
          pending,
          overdue,
          medicalRecords: records.length,
          visitRecords: visits.length,
          sessions: sessions.length,
        });
        const items: PendingItem[] = plans
          .flatMap((p) => p.items.filter((i) => i.status === 'pending').map((i) => ({ ...i, planId: p.id })))
          .sort((a, b) => Number(b.is_overdue) - Number(a.is_overdue))
          .slice(0, 4);
        setPendingItems(items);
      })
      .catch((err) => {
        if (!cancelled) dispatch({ type: 'SET_ERROR', payload: (err as Error).message });
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.patientId]);

  /* ---------- 未绑定患者：欢迎 + 入口 ---------- */
  if (!state.patientId) {
    return (
      <section className="dash-panel">
        <div className="dash-inner">
          <div className="dash-hero">
            <div className="dash-hero-icon">
              <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
              </svg>
            </div>
            <span className="dash-eyebrow">你的个人健康工作台</span>
            <h1>{greeting()}，从今天的健康事项开始</h1>
            <p>绑定患者后，可集中查看病历、待办与复诊安排；也可以先进行健康咨询。</p>
          </div>

          <div className="dash-actions-grid">
            <button className="dash-action-card" onClick={() => goChat('general')}>
              <div className="dash-action-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
                </svg>
              </div>
              <strong>开始健康咨询</strong>
              <span>无需绑定身份，先获得通用的健康知识与建议</span>
            </button>
            <button className="dash-action-card" onClick={() => goChat('memory')}>
              <div className="dash-action-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/>
                  <circle cx="12" cy="7" r="4"/>
                </svg>
              </div>
              <strong>绑定健康档案</strong>
              <span>在左侧搜索并选择患者，解锁病历、计划与个性化问诊</span>
            </button>
          </div>
        </div>
      </section>
    );
  }

  /* ---------- 已绑定患者：仪表盘 ---------- */
  return (
    <section className="dash-panel">
      <div className="dash-inner">
        <header className="dash-header">
          <div>
            <h1>{greeting()}{state.profileName ? `，${state.profileName}` : ''}</h1>
            <p>优先处理今天的事项；需要帮助时，随时向智能助手提问。</p>
          </div>
          <button className="btn btn-primary" onClick={() => goChat('memory')}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
            </svg>
            向助手提问
          </button>
        </header>

        <section className={`dash-priority-card ${stats && stats.overdue > 0 ? 'attention' : ''}`} aria-label="今日健康重点">
          <div className="dash-priority-icon">{stats && stats.overdue > 0 ? '!' : '✓'}</div>
          <div>
            <span>今日健康重点</span>
            <strong>{stats && stats.overdue > 0 ? `有 ${stats.overdue} 项事项已逾期，建议优先处理` : stats && stats.pending > 0 ? `有 ${stats.pending} 项待办等待完成` : '当前没有需要立即处理的事项'}</strong>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={() => dispatch({ type: 'SET_VIEW', payload: 'care' })}>查看计划 →</button>
        </section>

        {/* 统计卡片 */}
        <div className="dash-stats-grid">
          <button className="dash-stat-card" onClick={() => dispatch({ type: 'SET_VIEW', payload: 'care' })}>
            <span className="dash-stat-value">{stats ? stats.pending : '…'}</span>
            <span className="dash-stat-label">待办事项</span>
          </button>
          <button
            className={`dash-stat-card ${stats && stats.overdue > 0 ? 'dash-stat-danger' : ''}`}
            onClick={() => dispatch({ type: 'SET_VIEW', payload: 'care' })}
          >
            <span className="dash-stat-value">{stats ? stats.overdue : '…'}</span>
            <span className="dash-stat-label">逾期未做</span>
          </button>
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
            <span className="dash-stat-label">历史会话</span>
          </button>
        </div>

        <div className="dash-columns">
          {/* 待办预览 */}
          <div className="dash-card">
            <div className="dash-card-header">
              <h3>最近待办</h3>
              <button className="btn btn-ghost btn-sm" onClick={() => dispatch({ type: 'SET_VIEW', payload: 'care' })}>
                全部 →
              </button>
            </div>
            {pendingItems.length === 0 ? (
              <p className="dash-card-empty">{stats === null ? '正在加载…' : '暂无待办事项，可在照护计划中从就诊记录生成。'}</p>
            ) : (
              <ul className="dash-todo-list">
                {pendingItems.map((item) => (
                  <li key={item.id} className="dash-todo-item" onClick={() => dispatch({ type: 'SET_VIEW', payload: 'care' })}>
                    <span className={`dash-todo-dot ${item.is_overdue ? 'overdue' : ''}`} />
                    <span className="dash-todo-title">{item.title}</span>
                    {item.due_at && (
                      <span className={`dash-todo-due ${item.is_overdue ? 'overdue' : ''}`}>
                        {new Date(item.due_at).toLocaleDateString()}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* 快捷入口 */}
          <div className="dash-card">
            <div className="dash-card-header"><h3>快捷入口</h3></div>
            <div className="dash-quick-list">
              <button className="dash-quick-item" onClick={() => goChat('memory')}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
                </svg>
                <div><strong>记忆聊天</strong><span>结合病历历史连续对话</span></div>
              </button>
              <button className="dash-quick-item" onClick={() => goChat('general')}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
                </svg>
                <div><strong>通用聊天</strong><span>自由提问通用医疗问题</span></div>
              </button>
              <button className="dash-quick-item" onClick={() => dispatch({ type: 'SET_VIEW', payload: 'care' })}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
                  <line x1="16" y1="2" x2="16" y2="6"/>
                  <line x1="8" y1="2" x2="8" y2="6"/>
                  <line x1="3" y1="10" x2="21" y2="10"/>
                </svg>
                <div><strong>照护计划</strong><span>查看就诊后待办与复诊安排</span></div>
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
