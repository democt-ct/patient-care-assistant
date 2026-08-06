import { useAppState } from '../context/AppContext';

interface HeaderProps {
  onToggleSidebar: () => void;
  sidebarOpen: boolean;
}

export function Header({ onToggleSidebar, sidebarOpen }: HeaderProps) {
  const { state, dispatch } = useAppState();
  const loggedIn = Boolean(state.patientId);

  const toggleTheme = () => {
    dispatch({ type: 'SET_THEME', payload: state.theme === 'dark' ? 'light' : 'dark' });
  };

  return (
    <header className="header">
      <div className="header-left">
        <button
          className="header-toggle"
          onClick={onToggleSidebar}
          title={sidebarOpen ? '收起工作台导航' : '打开工作台导航'}
          aria-label={sidebarOpen ? '收起工作台导航' : '打开工作台导航'}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            {sidebarOpen ? <><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></> : <><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></>}
          </svg>
        </button>
        <div className="header-brand">
          <div className="header-brand-icon">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
          </div>
          <span className="header-brand-name">医疗信息导航 Agent</span>
        </div>
      </div>

      <div className="header-context" aria-live="polite">
        {state.selectedPatient ? (
          <>
            <span className="header-context-avatar">{state.selectedPatient.full_name?.charAt(0) || '?'}</span>
            <div><strong>{state.selectedPatient.full_name}</strong><span>当前健康档案 · {state.selectedPatient.patient_code}</span></div>
          </>
        ) : (
          <div><strong>医疗信息工作台</strong><span>在左侧绑定患者，核验病历与就诊信息</span></div>
        )}
      </div>

      <div className="header-right">
        <button className="header-role-button" onClick={() => dispatch({ type: 'SET_VIEW', payload: 'role' })}>切换角色</button>
        <button className="header-theme-toggle" onClick={toggleTheme} title={state.theme === 'dark' ? '切换到浅色模式' : '切换到暗色模式'}>
          {state.theme === 'dark' ? <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg> : <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>}
        </button>
        {state.workingMemory && <button className="header-icon-button" onClick={() => dispatch({ type: 'SET_MEMORY_DEBUG', payload: !state.memoryDebugOpen })} title="查看调试信息">Debug</button>}
        <button className={`header-login-button ${loggedIn ? 'active' : ''}`} onClick={() => dispatch({ type: 'SET_LOGIN_MODAL', payload: true })}>
          {loggedIn ? state.profileName || '已绑定' : '登录'}
        </button>
      </div>
    </header>
  );
}
