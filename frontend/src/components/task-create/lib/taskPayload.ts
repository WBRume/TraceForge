import type { DraftValidationError, TaskDraftSnapshot, WorkspaceRepo } from '../types'
import { workspaceRepoBindingId } from './repoTree'

export interface TaskPayloadContext {
  /** 工作区绑定的全部仓库环境 */
  repos: WorkspaceRepo[]
  /** 勾选的仓库绑定 id（打开侧栏时默认全选） */
  selectedRepoIds: string[]
  /** 按仓库的会话分支覆盖（留空 = 沿用工作区绑定分支） */
  branchOverrides: Record<string, string>
  /** 勾选的技能 id */
  skillIds: string[]
}

/**
 * 提交前校验草稿（纯函数）：
 * - 问题定位任务必须填写现象
 * - 工作区存在仓库环境时必须至少勾选一个
 * 通过返回 null。
 */
export function validateTaskDraft(
  draft: TaskDraftSnapshot,
  ctx: { reposTotal: number; selectedRepoCount: number },
): DraftValidationError | null {
  if (draft.taskType === 'DIAGNOSIS' && !draft.phenomenon.trim()) {
    return { key: 'diagnosis.phenomenon_required', severity: 'error' }
  }
  if (ctx.reposTotal > 0 && ctx.selectedRepoCount === 0) {
    return { key: 'dashboard.task_repo_required', severity: 'warning' }
  }
  return null
}

/**
 * 组装 POST /workspaces/:id/tasks 的请求体（纯函数）：
 * - 诊断态不带 description，改传 phenomenon + priority
 * - 诊断规程仅问题定位任务可绑定（研发态不下发 diagnosis_playbook_spec_id）
 * - 勾选仓库与全选等价时不下发 repository_ids（沿用后端默认全量 worktree 行为）
 * - 仅对勾选仓库下发非空（trim 后）分支覆盖
 */
export function buildTaskCreatePayload(
  draft: TaskDraftSnapshot,
  ctx: TaskPayloadContext,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    name: draft.name,
    task_type: draft.taskType,
    skill_ids: ctx.skillIds,
  }
  if (draft.taskType === 'DIAGNOSIS') {
    if (draft.diagnosisPlaybookSpecId) payload.diagnosis_playbook_spec_id = draft.diagnosisPlaybookSpecId
    payload.phenomenon = draft.phenomenon
    payload.priority = draft.priority
    if (draft.sopAutoRun) payload.sop_auto_run = true
  } else {
    payload.description = draft.description
    payload.requirement_duration_hours = Number(draft.requirementDurationHours)
  }

  const selectedSet = new Set(ctx.selectedRepoIds)
  const bindingIds = ctx.repos.map(workspaceRepoBindingId).filter(Boolean)
  if (selectedSet.size > 0 && selectedSet.size < bindingIds.length) {
    payload.repository_ids = [...selectedSet]
  }

  const branchOverrides = ctx.repos
    .filter((repo) => selectedSet.has(workspaceRepoBindingId(repo)))
    .map((repo) => ({
      repository_id: workspaceRepoBindingId(repo),
      branch_name: (ctx.branchOverrides[workspaceRepoBindingId(repo)] || '').trim(),
    }))
    .filter((item) => item.repository_id && item.branch_name)
  if (branchOverrides.length > 0) {
    payload.repository_branches = branchOverrides
  }
  return payload
}
