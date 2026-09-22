/**
 * 新建任务弹窗（task-create）领域类型。
 * 弹窗内容随 show 挂载/销毁，类型只描述单次打开内的数据契约。
 */

/** 任务类型：研发 / 问题定位（诊断） */
export type TaskTypeValue = 'DEVELOPMENT' | 'DIAGNOSIS'

/** 右侧滑出侧栏；同一时刻至多展开一个，none = 全部收起 */
export type TaskCreateSidebar = 'none' | 'skills' | 'repos' | 'playbooks'

/** 可展开的侧栏名称（入口条 / 内部切换用） */
export type TaskCreateSidebarName = Exclude<TaskCreateSidebar, 'none'>

/** 工作区绑定的仓库环境（GET /workspaces/:id → repositories） */
export interface WorkspaceRepo {
  repository_id?: string | number
  id?: string | number
  repo_name: string
  repo_url: string
  /** 工作区为该仓库绑定的默认分支 */
  branch_name?: string
  state?: string
}

/** 技能列表条目（GET /skills → items） */
export interface SkillSummary {
  id: string
  name: string
  description?: string
  dimension?: string
  publish_state?: string
  has_pending_changes?: boolean
}

/** 表单提交时的草稿快照（含 File 对象，保持普通对象不代理） */
export interface TaskDraftSnapshot {
  diagnosisPlaybookSpecId?: string
  taskType: TaskTypeValue
  name: string
  description: string
  /** 诊断态：问题现象 */
  phenomenon: string
  priority: string
  /** 诊断态主开关：自动执行全流程（SOP 阶段自动推进） */
  sopAutoRun: boolean
  /** 研发态：需求工时（小时） */
  requirementDurationHours: number
  /** 研发态：规范文档（任务创建成功后由浮窗上传） */
  specFile: File | null
  /** 诊断态：需求/日志文档（任务创建成功后由浮窗上传） */
  diagnosisFiles: File[]
}

/** 草稿校验失败：key 为 i18n 文案 */
export interface DraftValidationError {
  key: string
  severity: 'error' | 'warning'
}

/** 创建成功后向页面（ChatView / DashboardView）发出的事件负载 */
export interface TaskCreatedEvent {
  jobId: string
  taskId: string
  workspaceId: string
  expectSpecUpload: boolean
  expectDiagnosisDocs: boolean
}
