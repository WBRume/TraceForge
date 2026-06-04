import type { QueueJobItem, QueueSource } from '@/types/queue'

type TranslateFn = (key: string, values?: Record<string, unknown>) => string

const JOB_TYPE_KEY_MAP: Record<QueueSource, Record<string, string>> = {
  provision: {
    CREATE_WORKSPACE: 'workspaces.queue.job_type.create_workspace',
    CREATE_TASK: 'workspaces.queue.job_type.create_task',
    IMPORT_SKILL: 'workspaces.queue.job_type.import_skill',
  },
  api_mock: {
    SYNC_TASK_SOURCE: 'workspaces.queue.job_type.sync_task_source',
    IMPORT_SWAGGER: 'workspaces.queue.job_type.import_swagger',
    AUTO_GENERATE_MOCK_CASES: 'workspaces.queue.job_type.auto_generate_mock_cases',
  },
  bootstrap: {
    TASK_CLI_BOOTSTRAP: 'workspaces.queue.job_type.task_cli_bootstrap',
  },
  skill_analysis: {
    SKILL_ANALYSIS: 'workspaces.queue.job_type.skill_analysis',
  },
}

const JOB_DESC_KEY_MAP: Record<QueueSource, Record<string, string>> = {
  provision: {
    CREATE_WORKSPACE: 'workspaces.queue.job_desc.create_workspace',
    CREATE_TASK: 'workspaces.queue.job_desc.create_task',
    IMPORT_SKILL: 'workspaces.queue.job_desc.import_skill',
  },
  api_mock: {
    SYNC_TASK_SOURCE: 'workspaces.queue.job_desc.sync_task_source',
    IMPORT_SWAGGER: 'workspaces.queue.job_desc.import_swagger',
    AUTO_GENERATE_MOCK_CASES: 'workspaces.queue.job_desc.auto_generate_mock_cases',
  },
  bootstrap: {
    TASK_CLI_BOOTSTRAP: 'workspaces.queue.job_desc.task_cli_bootstrap',
  },
  skill_analysis: {
    SKILL_ANALYSIS: 'workspaces.queue.job_desc.skill_analysis',
  },
}

const STAGE_KEY_MAP: Record<string, string> = {
  QUEUED: 'workspaces.queue.stage.queued',
  WAITING_EXECUTION_QUEUE: 'workspaces.queue.stage.waiting_execution_queue',
  VALIDATING_INPUT: 'workspaces.queue.stage.validating_input',
  WAITING_REPO_LOCK: 'workspaces.queue.stage.waiting_repo_lock',
  CLONING_REPOSITORY: 'workspaces.queue.stage.cloning_repository',
  CREATING_WORKSPACE: 'workspaces.queue.stage.creating_workspace',
  PREPARING_TASK: 'workspaces.queue.stage.preparing_task',
  WAITING_TASK_QUEUE: 'workspaces.queue.stage.waiting_task_queue',
  PREPARING_WORKTREE: 'workspaces.queue.stage.preparing_worktree',
  PREPARING_LOCAL_WORKSPACE: 'workspaces.queue.stage.preparing_local_workspace',
  RUNNING: 'workspaces.queue.stage.running',
  COMPLETED: 'workspaces.queue.stage.completed',
  SUCCESS: 'workspaces.queue.stage.completed',
  FAILED: 'workspaces.queue.stage.failed',
  READY: 'workspaces.queue.stage.ready',
  STALE: 'workspaces.queue.stage.stale',
  PENDING: 'workspaces.queue.stage.queued',
}

const normalizeCode = (value: unknown): string => String(value || '').trim().toUpperCase()

export const queueSourceLabel = (source: string, t: TranslateFn): string => {
  if (source === 'provision') return t('workspaces.queue.source_provision')
  if (source === 'api_mock') return t('workspaces.queue.source_api_mock')
  if (source === 'bootstrap') return t('workspaces.queue.source_bootstrap')
  if (source === 'skill_analysis') return t('workspaces.queue.source_skill_analysis')
  return source || '-'
}

export const queueStatusLabel = (status: string, t: TranslateFn): string => {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'pending') return t('workspaces.queue.status.pending')
  if (normalized === 'running') return t('workspaces.queue.status.running')
  if (normalized === 'success') return t('workspaces.queue.status.success')
  if (normalized === 'failed') return t('workspaces.queue.status.failed')
  return status || '-'
}

export const queueJobTypeLabel = (item: QueueJobItem, t: TranslateFn): string => {
  const sourceMap = JOB_TYPE_KEY_MAP[item.source] || {}
  const key = sourceMap[normalizeCode(item.job_type)] || 'workspaces.queue.job_type.unknown'
  return t(key)
}

export const queueJobDescription = (item: QueueJobItem, t: TranslateFn): string => {
  const sourceMap = JOB_DESC_KEY_MAP[item.source] || {}
  const key = sourceMap[normalizeCode(item.job_type)] || 'workspaces.queue.job_desc.unknown'
  return t(key)
}

export const queueStageLabel = (item: QueueJobItem, t: TranslateFn): string => {
  if (item.source === 'api_mock') {
    return t('workspaces.queue.stage.api_mock')
  }
  const stageCode = normalizeCode(item.stage || item.status)
  const key = STAGE_KEY_MAP[stageCode]
  if (key) return t(key)

  const rawStage = String(item.stage || '').trim()
  if (rawStage) return rawStage.replace(/[_-]+/g, ' ')
  return t('workspaces.queue.stage.unknown')
}

export const shortQueueId = (value: string, size = 8): string => {
  const normalized = String(value || '').trim()
  if (!normalized) return '-'
  if (normalized.length <= size) return normalized
  return normalized.slice(0, size)
}

export const queueScopeLabel = (
  item: QueueJobItem,
  t: TranslateFn,
  workspaceNameMap?: Record<string, string>,
): string => {
  const workspaceId = String(item.workspace_id || '').trim()
  const taskId = String(item.task_id || '').trim()
  const workspaceName = workspaceId
    ? (workspaceNameMap?.[workspaceId] || `${t('workspaces.queue.scope.workspace')} #${shortQueueId(workspaceId)}`)
    : t('workspaces.queue.scope.global')
  if (!taskId) return workspaceName
  return `${workspaceName} / ${t('workspaces.queue.scope.task')} #${shortQueueId(taskId)}`
}

export const queueOpenActionLabel = (item: QueueJobItem, t: TranslateFn): string => {
  const typeCode = normalizeCode(item.job_type)
  if (item.source === 'provision' && typeCode === 'CREATE_WORKSPACE') {
    return t('workspaces.queue.actions.open_workspace')
  }
  if (item.source === 'provision' && typeCode === 'IMPORT_SKILL') {
    return t('workspaces.queue.actions.open_skill')
  }
  if (item.source === 'api_mock') {
    return t('workspaces.queue.actions.open_api_mock')
  }
  if (item.source === 'skill_analysis') {
    return t('workspaces.queue.actions.open_skill')
  }
  if (
    (item.source === 'provision' && typeCode === 'CREATE_TASK') ||
    item.source === 'bootstrap'
  ) {
    return t('workspaces.queue.actions.open_task')
  }
  return t('workspaces.queue.actions.open_result')
}
