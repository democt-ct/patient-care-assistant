import { useEffect, useState } from 'react';
import { useAppState } from '../context/AppContext';
import { patientApi } from '../services/api';
import type { Patient } from '../types';

const DEMO_HOSPITAL_ID = 'demo-hospital';

export function RoleLanding() {
  const { dispatch } = useAppState();
  const [patient, setPatient] = useState<Patient | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    patientApi.list(DEMO_HOSPITAL_ID)
      .then((patients) => setPatient(patients[0] ?? null))
      .catch((error) => dispatch({ type: 'SET_ERROR', payload: (error as Error).message }))
      .finally(() => setLoading(false));
  }, [dispatch]);

  const enter = (role: 'patient' | 'clinician' | 'coordinator') => {
    dispatch({
      type: 'SET_DEMO_CONTEXT',
      payload: {
        role,
        hospitalId: DEMO_HOSPITAL_ID,
        patientId: role === 'patient' ? patient?.id : undefined,
        profileName: role === 'patient' ? patient?.full_name : undefined,
      },
    });
  };

  return (
    <section className="role-landing">
      <div className="role-landing-inner">
        <span className="role-eyebrow">面试演示模式 · 全部为虚构数据</span>
        <h1>就诊后照护协同</h1>
        <p className="role-intro">从医生审核发布，到患者执行和协调员处理，演示一条可追溯的照护闭环。</p>

        <div className="role-flow" aria-label="照护业务流">
          <span>医生审核</span><i>→</i><span>患者计划</span><i>→</i><span>患者求助</span><i>→</i><span>协调员处理</span>
        </div>

        {loading && <p className="role-hint">正在准备演示病例…</p>}
        {!loading && !patient && <p className="role-error">未发现演示病例。请用 <code>DEMO_MODE=true</code> 启动本项目。</p>}

        <div className="role-card-grid">
          <button className="role-card" disabled={!patient} onClick={() => enter('clinician')}>
            <span className="role-icon">医</span>
            <strong>医生审核</strong>
            <p>核对来自明确随访计划的待办证据，并发布给患者。</p>
            <small>演示角色：doctor-demo</small>
          </button>
          <button className="role-card" disabled={!patient} onClick={() => enter('patient')}>
            <span className="role-icon">患</span>
            <strong>患者端</strong>
            <p>查看医院已发布的照护任务，完成、延期或请求帮助。</p>
            <small>{patient ? `演示患者：${patient.full_name}` : '等待演示数据'}</small>
          </button>
          <button className="role-card" disabled={!patient} onClick={() => enter('coordinator')}>
            <span className="role-icon">护</span>
            <strong>照护协调员</strong>
            <p>接手患者求助，记录处理过程并关闭协作单。</p>
            <small>演示角色：coordinator-demo</small>
          </button>
        </div>

        <p className="role-boundary">系统只将明确医嘱和随访计划转为待审核任务；不进行诊断、处方或剂量调整。</p>
      </div>
    </section>
  );
}
