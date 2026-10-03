import type { RequirementImportBatch, RequirementImportConfirmItem, RequirementSplitDraft } from '@/types/workspaceAssets'

export type EditableSplitItem = {
  item_id: string
  include: boolean
  title: string
  body: string
  acceptance_criteria: string[]
  priority: string
  task_prompt: string
}

export const priorityOptions = [
  { label: 'P0 High', value: 'High' },
  { label: 'P1 Medium', value: 'Medium' },
  { label: 'P2 Low', value: 'Low' },
]

export function getPriorityBadgeClass(priority: string) {
  const normalized = priority.toLowerCase()
  if (normalized.includes('high') || normalized === 'p0') return 'priority-high'
  if (normalized.includes('low') || normalized === 'p2') return 'priority-low'
  return 'priority-medium'
}

export function restoreSplitItems(batch: RequirementImportBatch, draft?: RequirementSplitDraft | null): EditableSplitItem[] {
  const rawById = new Map(batch.items.map(item => [item.id, item]))
  // A saved draft is the complete editing state; omitted AI suggestions were deliberately deleted.
  const entries = draft ? draft.items : batch.items.map(item => ({ ...item, item_id: item.id, include: item.status !== 'SKIPPED' }))
  return entries.map(item => {
    const raw = rawById.get(item.item_id)
    return {
      item_id: item.item_id,
      include: item.include,
      title: item.title ?? raw?.title ?? '',
      body: item.body ?? raw?.body ?? '',
      acceptance_criteria: [...(item.acceptance_criteria ?? raw?.acceptance_criteria ?? [])],
      priority: item.priority ?? raw?.priority ?? 'Medium',
      task_prompt: item.task_prompt ?? raw?.task_prompt ?? '',
    }
  })
}

export function createSplitItem(): EditableSplitItem {
  return { item_id: `custom-${crypto.randomUUID()}`, include: true, title: '', body: '', acceptance_criteria: [], priority: 'Medium', task_prompt: '' }
}

export function buildDraft(items: EditableSplitItem[], reason: string): RequirementSplitDraft {
  return {
    change_reason: reason.trim() || null,
    items: items.map(item => ({ ...item, body: item.body || null, acceptance_criteria: [...item.acceptance_criteria], priority: item.priority || null, task_prompt: item.task_prompt || null })),
  }
}

export function buildConfirmItems(items: EditableSplitItem[]): RequirementImportConfirmItem[] {
  return items.map(item => ({ ...item, title: item.title.trim(), body: item.body.trim() || null, acceptance_criteria: [...item.acceptance_criteria], priority: item.priority || null, task_prompt: item.task_prompt.trim() || null, status: 'DRAFT' }))
}
