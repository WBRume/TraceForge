<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { Link2, Loader2, X } from '@/components/icons'
import BaseSelect from '@/components/BaseSelect.vue'
import type { RequirementLinkedTask, RequirementSummary, TaskSummary } from '@/types/workspaceAssets'

const props = defineProps<{
  workspaceId: string
  requirement: RequirementSummary
  linkedTasks: readonly RequirementLinkedTask[]
  tasks: readonly TaskSummary[]
  loading?: boolean
}>()

const emit = defineEmits<{
  link: [payload: { taskId: string; relationType: 'RELATES_TO' | 'COVERS'; reason?: string | null }]
  unlink: [taskId: string]
}>()

const { t } = useI18n()

const dialogVisible = ref(false)
const form = reactive({
  taskId: '',
  relationType: 'COVERS' as 'RELATES_TO' | 'COVERS',
  reason: '',
})

const linkedIds = computed(() => new Set(props.linkedTasks.map((item) => item.task_id)))
const taskOptions = computed(() => props.tasks.filter((task) => !linkedIds.value.has(task.id)))
const taskSelectOptions = computed(() =>
  taskOptions.value.map((task) => ({
    label: `${task.name}${task.current_phase ? ` (${task.current_phase})` : ''}`,
    value: task.id,
  })),
)

function openLinkDialog() {
  if (!props.requirement.can_link_task) return
  form.taskId = ''
  form.relationType = 'COVERS'
  form.reason = ''
  dialogVisible.value = true
}

function closeLinkDialog() {
  dialogVisible.value = false
  form.taskId = ''
  form.reason = ''
}

function submit() {
  if (!form.taskId || !props.requirement.can_link_task) return
  emit('link', {
    taskId: form.taskId,
    relationType: form.relationType,
    reason: form.reason.trim() || null,
  })
  closeLinkDialog()
}

async function confirmUnlink(task: RequirementLinkedTask) {
  try {
    if (typeof ElMessageBox !== 'undefined' && ElMessageBox.confirm) {
      await ElMessageBox.confirm(
        t('workspace_assets.requirements.link_task_modal.unlink_confirm_message', { name: task.task_name }),
        t('workspace_assets.requirements.link_task_modal.unlink_confirm_title'),
        {
          confirmButtonText: t('common.confirm') || '确定',
          cancelButtonText: t('common.cancel') || '取消',
          type: 'warning',
        },
      )
    }
    emit('unlink', task.task_id)
  } catch {
    // 用户取消操作
  }
}

function getStatusLabel(status: string) {
  switch (status) {
    case 'COMPLETED':
    case 'SUCCESS':
    case 'DONE':
      return '已完成'
    case 'RUNNING':
    case 'IN_PROGRESS':
      return '运行中'
    case 'PROVISIONING':
      return '准备中'
    case 'FAILED':
      return '失败'
    case 'PLANNING':
      return '规划中'
    case 'PENDING':
      return '待处理'
    default:
      return status
  }
}

function getStatusBadgeClass(status: string) {
  switch (status) {
    case 'COMPLETED':
    case 'SUCCESS':
    case 'DONE':
      return 'status-badge-success'
    case 'RUNNING':
    case 'IN_PROGRESS':
      return 'status-badge-running'
    case 'PROVISIONING':
      return 'status-badge-warning'
    case 'FAILED':
      return 'status-badge-danger'
    default:
      return 'status-badge-default'
  }
}
</script>

<template>
  <section class="requirement-task-links-section">
    <!-- 头部：标题、计数徽标与关联动作 -->
    <header class="section-head">
      <div class="head-title">
        <h4>{{ t('workspace_assets.requirements.related_tasks_title') }}</h4>
        <span class="count-badge">{{ linkedTasks.length }}</span>
      </div>

      <div class="head-actions">
        <el-tooltip
          v-if="!requirement.can_link_task"
          :content="t('workspace_assets.requirements.drawer.parent_link_blocked')"
          placement="top"
        >
          <span>
            <el-button size="small" disabled class="btn-link-action">
              + {{ t('workspace_assets.requirements.actions.link_task') }}
            </el-button>
          </span>
        </el-tooltip>
        <el-button
          v-else
          size="small"
          type="primary"
          plain
          :disabled="loading"
          class="btn-link-action"
          @click="openLinkDialog"
        >
          + {{ t('workspace_assets.requirements.actions.link_task') }}
        </el-button>
      </div>
    </header>

    <!-- 任务卡片列表 -->
    <div v-if="linkedTasks.length" class="task-compact-list">
      <article v-for="task in linkedTasks" :key="task.link_id" class="task-compact-card">
        <!-- 顶部标签行：关系类型 + 运行状态 -->
        <div class="card-meta-top">
          <!-- 关系类型标签（解决英文 RELATES_TO / COVERS 晦涩问题） -->
          <el-tooltip
            :content="task.relation_type === 'COVERS'
              ? t('workspace_assets.requirements.relation_types.covers_desc')
              : t('workspace_assets.requirements.relation_types.relates_to_desc')"
            placement="top"
          >
            <span :class="['relation-badge', task.relation_type === 'COVERS' ? 'relation-covers' : 'relation-relates']">
              {{ task.relation_type === 'COVERS'
                ? `🎯 ${t('workspace_assets.requirements.relation_types.covers_short')}`
                : `🔗 ${t('workspace_assets.requirements.relation_types.relates_to_short')}` }}
            </span>
          </el-tooltip>

          <!-- 汉化状态指示与当前阶段 -->
          <span :class="['status-badge', getStatusBadgeClass(task.task_status)]">
            <span class="status-dot"></span>
            {{ getStatusLabel(task.task_status) }}
            <template v-if="task.current_phase"> · {{ task.current_phase }}</template>
          </span>
        </div>

        <!-- 中部任务名称与链接 -->
        <div class="card-title-row">
          <RouterLink
            class="task-title-link"
            :to="`/workspaces/${workspaceId}/chat/${task.task_id}`"
            :title="task.task_name"
            :aria-disabled="task.task_status === 'PROVISIONING' || undefined"
            @click="task.task_status === 'PROVISIONING' && $event.preventDefault()"
          >
            <strong>{{ task.task_name }}</strong>
          </RouterLink>
        </div>

        <!-- 底部信息行：创建人、耗时与解除关联按钮 -->
        <div class="card-footer-row">
          <span class="meta-info">
            {{ task.creator_name || t('task_rail.owner_unknown') }} · {{ ((task.total_duration_ms || 0) / 60000).toFixed(1) }} min
          </span>
          <el-button
            size="small"
            type="danger"
            text
            class="btn-unlink"
            :disabled="loading"
            @click="confirmUnlink(task)"
          >
            {{ t('workspace_assets.requirements.actions.unlink_task') }}
          </el-button>
        </div>
      </article>
    </div>

    <!-- 空状态 -->
    <div v-else class="task-compact-empty">
      <p class="empty-text">{{ t('workspace_assets.requirements.related_tasks_empty') }}</p>
      <el-button
        v-if="requirement.can_link_task"
        type="primary"
        text
        size="small"
        class="empty-action"
        @click="openLinkDialog"
      >
        + {{ t('workspace_assets.requirements.actions.link_task') }}
      </el-button>
      <p v-else class="empty-blocked">
        {{ t('workspace_assets.requirements.drawer.parent_link_blocked') }}
      </p>
    </div>

    <!-- 关联任务全局标准对话框 (修复圆角裁剪、关系卡片选择与 BaseSelect 搜索支持) -->
    <Teleport to="body">
      <div v-if="dialogVisible" class="modal-overlay" @pointerdown.self="closeLinkDialog">
        <section class="modal glass-panel link-task-modal" role="dialog" aria-modal="true">
          <header class="modal-header">
            <div class="header-icon">
              <Link2 :size="22" />
            </div>
            <div class="header-text">
              <h2>{{ t('workspace_assets.requirements.link_task_modal.title') }}</h2>
              <p class="description">{{ t('workspace_assets.requirements.link_task_modal.subtitle') }}</p>
            </div>
            <button
              type="button"
              class="close-btn"
              :title="t('common.close')"
              :disabled="loading"
              @click="closeLinkDialog"
            >
              <X :size="20" />
            </button>
          </header>

          <div class="modal-content">
            <form class="link-modal-form" @submit.prevent="submit">
              <!-- 1. 选择任务 (采用支持搜索的项目全局 BaseSelect 组件) -->
              <div class="form-field">
                <label class="required">{{ t('workspace_assets.requirements.link_task_modal.select_task_label') }}</label>
                <BaseSelect
                  v-model="form.taskId"
                  :options="taskSelectOptions"
                  :placeholder="t('workspace_assets.requirements.link_task_modal.select_task_placeholder')"
                  searchable
                  :search-placeholder="t('workspace_assets.requirements.link_task_modal.search_task_placeholder')"
                  size="md"
                />
                <span class="field-hint">{{ t('workspace_assets.requirements.link_task_modal.select_task_tip') }}</span>
              </div>

              <!-- 2. 关系类型 (恢复为高质感双列卡片选择器) -->
              <div class="form-field">
                <label class="required">{{ t('workspace_assets.requirements.link_task_modal.relation_type_label') }}</label>
                <div class="relation-selection-grid">
                  <!-- 核心覆盖卡片 -->
                  <div
                    :class="['relation-choice-card', form.relationType === 'COVERS' && 'selected-choice']"
                    @click="form.relationType = 'COVERS'"
                  >
                    <div class="choice-head">
                      <span class="choice-title">🎯 {{ t('workspace_assets.requirements.relation_types.covers') }}</span>
                      <span class="radio-indicator"></span>
                    </div>
                    <p class="choice-desc">
                      {{ t('workspace_assets.requirements.relation_types.covers_desc') }}
                    </p>
                  </div>

                  <!-- 协同参考卡片 -->
                  <div
                    :class="['relation-choice-card', form.relationType === 'RELATES_TO' && 'selected-choice']"
                    @click="form.relationType = 'RELATES_TO'"
                  >
                    <div class="choice-head">
                      <span class="choice-title">🔗 {{ t('workspace_assets.requirements.relation_types.relates_to') }}</span>
                      <span class="radio-indicator"></span>
                    </div>
                    <p class="choice-desc">
                      {{ t('workspace_assets.requirements.relation_types.relates_to_desc') }}
                    </p>
                  </div>
                </div>
              </div>

              <!-- 3. 关联说明 / 变更原因 -->
              <div class="form-field">
                <label>{{ t('workspace_assets.requirements.link_task_modal.reason_label') }}</label>
                <textarea
                  v-model="form.reason"
                  rows="2"
                  class="field-input"
                  :placeholder="t('workspace_assets.requirements.link_task_modal.reason_placeholder')"
                />
              </div>
            </form>
          </div>

          <footer class="modal-footer">
            <button
              type="button"
              class="btn-secondary"
              :disabled="loading"
              @click="closeLinkDialog"
            >
              {{ t('common.cancel') }}
            </button>
            <button
              type="button"
              class="btn-primary"
              :disabled="!form.taskId || loading"
              @click="submit"
            >
              <Loader2 v-if="loading" :size="16" class="spin" />
              {{ t('workspace_assets.requirements.link_task_modal.submit') }}
            </button>
          </footer>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.requirement-task-links-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 头部样式 */
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 2px;
}

.head-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.head-title h4 {
  margin: 0;
  font-family: 'Poppins', sans-serif;
  font-size: 0.95rem;
  font-weight: 700;
  color: #1e3a8a;
}

.count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 700;
  background: #e0f2fe;
  color: #0369a1;
  padding: 1px 7px;
  border-radius: 9999px;
  line-height: 1.3;
}

.btn-link-action {
  font-size: 0.75rem;
  border-radius: 8px;
  font-weight: 600;
}

/* 紧凑微卡片列表 */
.task-compact-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-compact-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.85);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.task-compact-card:hover {
  border-color: #38bdf8;
  background: #ffffff;
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.08);
  transform: translateY(-1px);
}

/* 顶部标签行 */
.card-meta-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: 0.6875rem;
}

.relation-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  border-radius: 6px;
  font-weight: 700;
  letter-spacing: 0.2px;
  cursor: default;
}

.relation-covers {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.relation-relates {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  border-radius: 5px;
  font-size: 0.6875rem;
  font-weight: 600;
}

.status-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.status-badge-success {
  background: #f0fdf4;
  color: #16a34a;
}

.status-badge-running {
  background: #eff6ff;
  color: #2563eb;
}

.status-badge-running .status-dot {
  animation: pulse 1.5s infinite;
}

.status-badge-warning {
  background: #fffbeb;
  color: #d97706;
}

.status-badge-danger {
  background: #fef2f2;
  color: #dc2626;
}

.status-badge-default {
  background: #f1f5f9;
  color: #64748b;
}

/* 标题行 */
.card-title-row {
  min-width: 0;
}

.task-title-link {
  display: block;
  font-size: 0.8125rem;
  color: #0f172a;
  text-decoration: none;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color 0.15s;
}

.task-title-link:hover {
  color: #0284c7;
}

/* 底部行 */
.card-footer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: 0.6875rem;
  color: #94a3b8;
}

.meta-info {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.btn-unlink {
  padding: 0 4px;
  font-size: 0.6875rem;
  height: auto;
}

/* 空状态 */
.task-compact-empty {
  padding: 16px 12px;
  text-align: center;
  border: 1px dashed #cbd5e1;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.7);
}

.empty-text {
  margin: 0 0 4px;
  font-size: 0.75rem;
  color: #64748b;
}

.empty-action {
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0;
}

.empty-blocked {
  margin: 4px 0 0;
  font-size: 0.6875rem;
  color: #94a3b8;
  line-height: 1.4;
}

/* ============================================================ */
/* 全局标准弹窗样式 (精确修复圆角效果与子元素裁剪) */
/* ============================================================ */
.modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  animation: fade-in 0.25s ease-out;
  overflow-y: auto;
  box-sizing: border-box;
}

@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal {
  width: min(560px, 100%);
  min-height: 520px;
  max-height: min(820px, 92vh);
  background: #ffffff;
  border-radius: 1.25rem;
  box-shadow:
    0 10px 15px -3px rgba(0, 0, 0, 0.1),
    0 25px 50px -12px rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden; /* 保证子元素背景色不溢出圆角之外 */
  animation: modal-enter 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  border: 1px solid rgba(226, 232, 240, 0.8);
}

@keyframes modal-enter {
  from {
    opacity: 0;
    transform: scale(0.95) translateY(12px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

.modal-header {
  position: relative;
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.25rem 1.75rem;
  border-bottom: 1px solid #f1f5f9;
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
  border-top-left-radius: 1.25rem;
  border-top-right-radius: 1.25rem;
  flex-shrink: 0;
}

.header-icon {
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 0.875rem;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: #f0f9ff;
  border: 1px solid #e0f2fe;
  color: #0284c7;
}

.header-text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.header-text h2 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.15rem;
  font-weight: 700;
  margin: 0;
  color: #0f172a;
}

.description {
  margin: 0;
  color: #64748b;
  font-size: 0.8125rem;
  line-height: 1.4;
}

.close-btn {
  width: 2.25rem;
  height: 2.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.75rem;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.close-btn:hover {
  background: #f8fafc;
  color: #0f172a;
  border-color: #cbd5e1;
  transform: translateY(-1px);
}

.modal-content {
  flex: 1;
  padding: 1.5rem 1.75rem;
  overflow: visible; /* 保持 visible，避免绝对定位下拉框触发表单容器纵向滚动条导致内容宽度跳变 */
  position: relative;
  z-index: 10;
}

.link-modal-form {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-field label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #334155;
}

.required::after {
  content: '*';
  color: #ef4444;
  margin-left: 4px;
  font-weight: 800;
}

.field-hint {
  font-size: 0.6875rem;
  color: #94a3b8;
}

/* 关系选择双列卡片 */
.relation-selection-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  width: 100%;
}

.relation-choice-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border: 2px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.relation-choice-card:hover {
  border-color: #93c5fd;
  background: #f8fafc;
}

.relation-choice-card.selected-choice {
  border-color: #0ea5e9;
  background: #f0f9ff;
  box-shadow: 0 0 0 1px #0ea5e9;
}

.choice-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.choice-title {
  font-size: 0.8125rem;
  font-weight: 700;
  color: #1e293b;
}

.selected-choice .choice-title {
  color: #0369a1;
}

.radio-indicator {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid #cbd5e1;
  background: #ffffff;
  position: relative;
  flex-shrink: 0;
}

.selected-choice .radio-indicator {
  border-color: #0ea5e9;
  background: #0ea5e9;
}

.selected-choice .radio-indicator::after {
  content: '';
  position: absolute;
  top: 3px;
  left: 3px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #ffffff;
}

.choice-desc {
  margin: 0;
  font-size: 0.6875rem;
  line-height: 1.45;
  color: #64748b;
}

.field-input {
  width: 100%;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 0.625rem 0.875rem;
  font-size: 0.875rem;
  color: #0f172a;
  background: #ffffff;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
  box-sizing: border-box;
  resize: vertical;
}

.field-input:focus {
  outline: none;
  border-color: #38bdf8;
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.15);
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 0.75rem;
  padding: 1.25rem 1.75rem;
  border-top: 1px solid #f1f5f9;
  background: #f8fafc;
  border-bottom-left-radius: 1.25rem;
  border-bottom-right-radius: 1.25rem;
  flex-shrink: 0;
  position: relative;
  z-index: 1;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
