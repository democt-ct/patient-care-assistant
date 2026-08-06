// ============================================================
// 患者 & 上下文
// ============================================================

export interface Patient {
  id: string;
  hospital_id: string;
  patient_code: string;
  full_name: string;
  gender: string | null;
  birth_date: string | null;
  phone: string | null;
  id_number_hash: string | null;
  id_number_last4: string | null;
  address: string | null;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
  blood_type: string | null;
  allergy_history: string | null;
  family_history: string | null;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface MedicalRecord {
  id: string;
  patient_id: string;
  record_date: string;
  record_type: string | null;
  diagnosis: string | null;
  icd_code: string | null;
  chief_complaint: string | null;
  prescription: string | null;
  examination_result: string | null;
  created_at: string;
}

export interface VisitRecord {
  id: string;
  patient_id: string;
  visit_date: string;
  visit_type: string | null;
  department: string | null;
  doctor_name: string | null;
  notes: string | null;
  created_at: string;
}

export interface PatientProfile {
  patient: Patient;
  medical_records: MedicalRecord[];
  visit_records: VisitRecord[];
  identity?: Record<string, unknown>;
}

export interface CarePlanItemEvent {
  id: string;
  event_type: string;
  note: string | null;
  actor_type: string;
  created_at: string;
}

export interface CarePlanItem {
  id: string;
  care_plan_id: string;
  patient_id: string;
  task_type: string;
  title: string;
  instructions: string | null;
  priority: string;
  status: string;
  due_at: string | null;
  evidence_source_type: string;
  evidence_source_id: string;
  evidence_excerpt: string;
  needs_patient_confirmation: boolean;
  follow_up_status: string;
  patient_acknowledged_at: string | null;
  last_patient_response_at: string | null;
  last_reminded_at: string | null;
  next_reminder_at: string | null;
  reminder_count: number;
  execution_evidence_type: string | null;
  needs_follow_up: boolean;
  is_overdue: boolean;
  snoozed_until: string | null;
  is_snoozed: boolean;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  events: CarePlanItemEvent[];
}

export interface CarePlan {
  id: string;
  patient_id: string;
  hospital_id: string;
  source_type: string;
  source_id: string;
  title: string;
  status: string;
  confirmed_at: string | null;
  created_at: string;
  updated_at: string;
  pending_count: number;
  overdue_count: number;
  items: CarePlanItem[];
}

export interface CareCase {
  id: string;
  patient_id: string;
  hospital_id: string;
  care_plan_item_id: string;
  care_plan_item_title: string;
  care_plan_item_due_at: string | null;
  reason: string;
  priority: string;
  status: 'open' | 'acknowledged' | 'resolved' | string;
  patient_note: string | null;
  coordinator_note: string | null;
  assignee_id: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export type DemoRole = 'patient' | 'clinician' | 'coordinator';

// ============================================================
// 聊天消息
// ============================================================

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at?: string;
  image_analysis?: string;
  speech_url?: string;
  /** A user-safe summary of the completed agent workflow for this answer. */
  process?: AgentProcessState;
  /** 统一输出契约：依据 / 风险 / 下一步 / 任务类型 */
  risk_level?: string;
  next_action?: string;
  evidence_summary?: string;
  task_route?: Record<string, unknown>;
}

// ============================================================
// 工作记忆 & 会话状态
// ============================================================

export interface SessionState {
  intent: string;
  current_topic: string;
  goal: string;
  working_summary: string;
  next_action: string;
  memory_focus: string;
  confirmed_facts: string[];
  open_questions: string[];
  identity_status: string;
}

export interface ActiveEntities {
  drugs: string[];
  symptoms: string[];
  tests: string[];
  metrics: string[];
}

export interface RiskSignals {
  red_flags: string[];
  medication_flags: string[];
  monitoring_flags: string[];
}

export interface ShortTermMemory {
  recent_messages: ChatMessage[];
  session_state: SessionState;
  active_entities: ActiveEntities;
  risk_signals: RiskSignals;
}

export interface MemoryLayers {
  factual_memory: string;
  long_term_summary_memory: string;
  knowledge_memory: string;
  merged_context: string;
}

export interface MemoryDebugPayload {
  working_memory: ShortTermMemory;
  memory_layers: MemoryLayers;
}

export interface AgentQueryResponse {
  answer: string;
  speech_url?: string;
  image_analysis?: string;
  memory_debug?: MemoryDebugPayload;
  risk_signals?: RiskSignals;
  intent?: string;
  intent_confidence?: number;
  chosen_tool?: string;
  risk_level?: string;
  next_action?: string;
  evidence_summary?: string;
  task_route?: Record<string, unknown>;
  citation_report?: {
    checked?: boolean;
    valid?: boolean;
    supported_count?: number;
    unsupported_count?: number;
  };
}

// ============================================================
// Agent 处理过程（SSE 流式阶段）
// ============================================================

export interface AgentProcessPhase {
  phase: string;
  message: string;
  status: 'done' | 'active' | 'pending';
}

export interface AgentProcessState {
  phases: AgentProcessPhase[];
  intent?: string;
  confidence?: number;
  plan?: Record<string, unknown>;
  tool?: string;
}

// ============================================================
// 会话
// ============================================================

export interface ConversationSession {
  session_id: string;
  patient_id: string;
  message_count: number;
  first_message_at: string;
  last_message_at: string;
}

// ============================================================
// 应用状态
// ============================================================

export type ChatMode = 'general' | 'memory';
export type SpeechMode = 'browser' | 'tts';
export type AppView = 'role' | 'dashboard' | 'chat' | 'patient' | 'care' | 'clinician' | 'coordinator';
export type Theme = 'light' | 'dark';

export interface AppState {
  // 患者上下文
  patientId: string;
  hospitalId: string;
  authToken: string;
  profileName: string;
  profilePhone: string;
  demoRole: DemoRole | null;

  // 会话
  sessionId: string;
  generalSessionId: string;
  chatMode: ChatMode;
  speechMode: SpeechMode;
  theme: Theme;

  // 聊天
  chatMessages: ChatMessage[];
  generalChatMessages: ChatMessage[];
  lastAnswer: string;
  lastSpeechText: string;

  // 记忆调试
  workingMemory: ShortTermMemory | null;
  memoryLayers: MemoryLayers | null;

  // 患者检索
  patients: Patient[];
  selectedPatient: Patient | null;
  patientProfile: PatientProfile | null;

  // UI
  currentView: AppView;
  memoryDebugOpen: boolean;
  isLoading: boolean;
  isPatientPanelOpen: boolean;
  isLoginModalOpen: boolean;
  error: string | null;
  statusMessage: string;
}

export type AppAction =
  | { type: 'SET_PATIENT_CONTEXT'; payload: { patientId: string; hospitalId: string; authToken?: string; profileName?: string; profilePhone?: string } }
  | { type: 'SET_DEMO_CONTEXT'; payload: { role: DemoRole; hospitalId: string; patientId?: string; profileName?: string } }
  | { type: 'CLEAR_PATIENT_CONTEXT' }
  | { type: 'SET_SESSION_ID'; payload: string }
  | { type: 'SET_GENERAL_SESSION_ID'; payload: string }
  | { type: 'SET_CHAT_MODE'; payload: ChatMode }
  | { type: 'SET_THEME'; payload: Theme }
  | { type: 'SET_SPEECH_MODE'; payload: SpeechMode }
  | { type: 'ADD_CHAT_MESSAGE'; payload: ChatMessage }
  | { type: 'ADD_GENERAL_CHAT_MESSAGE'; payload: ChatMessage }
  | { type: 'SET_CHAT_MESSAGES'; payload: ChatMessage[] }
  | { type: 'SET_GENERAL_CHAT_MESSAGES'; payload: ChatMessage[] }
  | { type: 'SET_LAST_ANSWER'; payload: string }
  | { type: 'SET_LAST_SPEECH_TEXT'; payload: string }
  | { type: 'SET_WORKING_MEMORY'; payload: ShortTermMemory | null }
  | { type: 'SET_MEMORY_LAYERS'; payload: MemoryLayers | null }
  | { type: 'SET_PATIENTS'; payload: Patient[] }
  | { type: 'SET_SELECTED_PATIENT'; payload: Patient | null }
  | { type: 'SET_PATIENT_PROFILE'; payload: PatientProfile | null }
  | { type: 'SET_VIEW'; payload: AppView }
  | { type: 'SET_MEMORY_DEBUG'; payload: boolean }
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_PATIENT_PANEL'; payload: boolean }
  | { type: 'SET_LOGIN_MODAL'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string | null }
  | { type: 'SET_STATUS'; payload: string }
  | { type: 'RESET_CHAT' };
