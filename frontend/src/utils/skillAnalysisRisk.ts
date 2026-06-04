import type { SkillAnalysisRiskItem } from '@/types/skillAnalysis'

export const riskLocation = (risk: SkillAnalysisRiskItem) => {
  const filePath = String(risk.file_path || '').trim() || '-'
  const lineStart = Number(risk.line_start || 0)
  const lineEnd = Number(risk.line_end || 0)
  if (lineStart > 0 && lineEnd > 0 && lineEnd !== lineStart) {
    return `${filePath}:${lineStart}-${lineEnd}`
  }
  if (lineStart > 0) {
    return `${filePath}:${lineStart}`
  }
  return filePath
}

export const fallbackRiskKey = (risk: SkillAnalysisRiskItem, index = 0) => {
  const explicitId = String(risk.id || '').trim()
  if (explicitId) return explicitId
  return [
    String(risk.risk_type || 'risk'),
    String(risk.file_path || 'file'),
    String(risk.line_start || 0),
    String(risk.source || 'source'),
    String(index),
  ]
    .join('-')
    .replace(/[^a-zA-Z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 120) || `risk-${index}`
}

export const riskTitle = (risk: SkillAnalysisRiskItem) => {
  const title = String(risk.title || '').trim()
  if (title) return title
  return `${riskLocation(risk)} · ${String(risk.risk_type || '风险项')}`
}

export const riskSummary = (risk: SkillAnalysisRiskItem) => {
  return String(risk.evidence_summary || risk.description || risk.risk_type || '暂无证据摘要').trim()
}

export const riskDetail = (risk: SkillAnalysisRiskItem) => {
  return String(risk.evidence_detail || risk.matched_text || riskSummary(risk)).trim()
}

export const riskRecommendation = (risk: SkillAnalysisRiskItem) => {
  return String(risk.recommendation || '请结合文件上下文人工复核该风险是否符合 Skill 预期。').trim()
}

export const formatConfidence = (value?: number) => {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-'
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`
}
