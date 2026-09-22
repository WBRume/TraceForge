import type { GuideHypothesis } from '@/types/diagnosisPlaybook'

export const isSupportedHypothesis = (hypothesis: GuideHypothesis) =>
  hypothesis.verdict === 'SUPPORTED' && hypothesis.evidence.length > 0 && !!hypothesis.verdict_reason?.trim()

export const hypothesisLabel = (hypothesis: { state: string; verdict?: string; evidence?: unknown[] }) => {
  if (hypothesis.verdict === 'REFUTED') return '已证伪'
  if (hypothesis.state === 'EXCLUDED') return '已排除'
  if (hypothesis.state === 'APPROVED' && hypothesis.verdict === 'SUPPORTED') return '已确认根因'
  if (hypothesis.verdict === 'SUPPORTED') return '支持／候选根因'
  if (hypothesis.verdict === 'INCONCLUSIVE') return '尚无定论'
  return '待验证'
}
