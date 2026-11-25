import type { CanvasRelationType } from './model'

interface RelationStyle { color: string; dash: string; width: number }

export const relationStyles: Record<CanvasRelationType, RelationStyle> = {
  COVERS: { color: '#1763bd', dash: '', width: 3 },
  RELATES_TO: { color: '#1763bd', dash: '7 5', width: 2.4 },
  DOCUMENT_TASK: { color: '#087b69', dash: '', width: 2.4 },
  DOCUMENT_REQUIREMENT: { color: '#087b69', dash: '10 4 2 4', width: 2.4 },
  CASE_TASK: { color: '#a05219', dash: '2 4', width: 2.8 },
  CASE_PROMOTION: { color: '#7040a4', dash: '', width: 3.2 },
  CASE_PLAYBOOK: { color: '#7040a4', dash: '4 4', width: 2.3 },
  TASK_PLAYBOOK: { color: '#994268', dash: '10 5', width: 2.5 },
  SUB_REQUIREMENT: { color: '#56677c', dash: '', width: 2 },
  PREREQUISITE: { color: '#56677c', dash: '10 5', width: 2.4 },
}
