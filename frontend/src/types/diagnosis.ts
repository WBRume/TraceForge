/**
 * 问题定位任务：结构化问题案例协议
 *
 * 与 backend/app/domains/task/schemas/diagnosis.py 对齐。
 * evidence / fix_steps 为逐条字符串数组，直接对应行动板行与步骤。
 */

export interface DiagnosisCodeContextItem {
  file_path: string
  start_line?: number | null
  end_line?: number | null
  snippet?: string | null
  note?: string | null
}

export interface DiagnosisSimilarCaseItem {
  title: string
  similarity?: string | null
  summary?: string | null
  reference?: string | null
}

export interface DiagnosisCallChainNode {
  seq?: number | null
  module?: string | null
  function?: string | null
  file_path?: string | null
  description?: string | null
}

export interface DiagnosisResultPayload {
  summary?: string | null
  root_cause?: string | null
  evidence: string[]
  fix_steps: string[]
  fix_code?: string | null
  code_context: DiagnosisCodeContextItem[]
  similar_cases: DiagnosisSimilarCaseItem[]
  call_chain: DiagnosisCallChainNode[]
  confidence: number
}

export interface DiagnosisResultResponse extends DiagnosisResultPayload {
  id: string
  task_id: string
  workspace_id: string
  created_by_id: string
  status: 'DRAFT' | 'CONFIRMED'
  extracted_from_ai: boolean
  extracted_at?: string | null
  source_chat_message_id?: string | null
  created_at: string
  updated_at?: string | null
}

export const EMPTY_DIAGNOSIS_PAYLOAD = (): DiagnosisResultPayload => ({
  summary: '',
  root_cause: '',
  evidence: [],
  fix_steps: [],
  fix_code: '',
  code_context: [],
  similar_cases: [],
  call_chain: [],
  confidence: 0,
})

/** 从聊天消息解析问题案例载荷（metadata 优先，content 兜底）。 */
export function diagnosisPayloadFromMessage(msg: Record<string, any>): DiagnosisResultPayload {
  const metadata = msg?.metadata
  if (metadata && typeof metadata === 'object') {
    return normalizeDiagnosisPayload(metadata)
  }
  const empty = EMPTY_DIAGNOSIS_PAYLOAD()
  empty.summary = String(msg?.content || '')
  return empty
}

/** 规范化松散载荷：保证列表字段为数组、confidence 在 0-100。 */
export function normalizeDiagnosisPayload(raw: Record<string, any> | null | undefined): DiagnosisResultPayload {
  const base = EMPTY_DIAGNOSIS_PAYLOAD()
  if (!raw || typeof raw !== 'object') return base
  const list = (value: unknown): any[] => (Array.isArray(value) ? value : [])
  const stringList = (value: unknown): string[] =>
    list(value)
      .map((item) => (typeof item === 'string' ? item.trim() : ''))
      .filter(Boolean)
  const confidence = Number(raw.confidence ?? 0)
  return {
    summary: typeof raw.summary === 'string' ? raw.summary : '',
    root_cause: typeof raw.root_cause === 'string' ? raw.root_cause : '',
    evidence: stringList(raw.evidence),
    fix_steps: stringList(raw.fix_steps),
    fix_code: typeof raw.fix_code === 'string' ? raw.fix_code : '',
    code_context: list(raw.code_context),
    similar_cases: list(raw.similar_cases),
    call_chain: list(raw.call_chain),
    confidence: Number.isFinite(confidence) ? Math.max(0, Math.min(100, Math.round(confidence))) : 0,
  }
}
