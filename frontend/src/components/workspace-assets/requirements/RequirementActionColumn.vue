<script setup lang="ts">
/**
 * 需求表格操作列 · 方案 B：悬停感应微图标组
 *
 * 平时只保留一枚轻量状态提示（待认领 / 可建任务），鼠标进入行后
 * 浮出玻璃拟态图标工具条，避免多个高饱和按钮同时抢占视觉焦点。
 * 视觉规范与 examples/requirement-actions-redesign 方案 B 原型一致。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import type { RequirementSummary } from '@/types/workspaceAssets'

const props = withDefaults(defineProps<{
  requirement: RequirementSummary
  userId?: string
  canManage?: boolean
  canCreateTask?: boolean
  claiming?: boolean
}>(), {
  canManage: true,
  canCreateTask: true,
})

const emit = defineEmits<{
  open: []
  edit: []
  createTask: []
  createChild: []
  split: []
  claim: [clarify: boolean]
}>()

const { t } = useI18n()
const moreOpen = ref(false)

const isParent = computed(() => !props.requirement.parent_requirement_id)
const isClaimable = computed(() => Boolean(props.userId) && props.canCreateTask
  && !props.requirement.owner_id && !props.requirement.child_count && !props.requirement.work_started
  && !['ARCHIVED', 'VERIFIED', 'PENDING_ACCEPTANCE'].includes(props.requirement.status))
const canCreateTaskForRequirement = computed(() => props.requirement.can_link_task
  && props.requirement.child_count === 0 && props.canCreateTask)

const claimLabel = computed(() => t(props.requirement.clarification_reason
  ? 'workspace_assets.delivery.claim_clarify'
  : 'workspace_assets.delivery.claim'))

type MoreCommand = 'copy-link' | 'copy-id'

async function handleMoreCommand(command: MoreCommand) {
  const requirementUrl = `${window.location.origin}/workspaces/${props.requirement.workspace_id}/assets/requirements/${props.requirement.id}`
  const value = command === 'copy-link' ? requirementUrl : props.requirement.id
  try {
    await navigator.clipboard.writeText(value)
    ElMessage.success(t(command === 'copy-link'
      ? 'workspace_assets.requirements.table.copied_link'
      : 'workspace_assets.requirements.table.copied_id'))
  } catch {
    ElMessage.warning(t('workspace_assets.requirements.table.copy_failed'))
  }
}
</script>

<template>
  <div class="requirement-action-cell" :class="{ 'is-more-open': moreOpen }" @click.stop>
    <div class="requirement-action-idle" aria-hidden="true">
      <span v-if="isClaimable" class="requirement-action-chip is-claimable">
        {{ t('workspace_assets.requirements.table.claim_hint') }}
      </span>
      <span v-else-if="canCreateTaskForRequirement" class="requirement-action-chip is-task">
        {{ t('workspace_assets.requirements.table.task_hint') }}
      </span>
    </div>

    <div class="requirement-action-toolbar">
      <el-tooltip :content="t('workspace_assets.requirements.table.view_detail')" placement="top" :show-after="120" popper-class="requirement-action-tooltip">
        <button
          type="button"
          class="requirement-action-btn"
          :aria-label="t('workspace_assets.requirements.table.view_detail')"
          @click.stop="emit('open')"
        >
          <svg class="requirement-action-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        </button>
      </el-tooltip>

      <el-tooltip v-if="isClaimable" :content="claimLabel" placement="top" :show-after="120" popper-class="requirement-action-tooltip">
        <button
          type="button"
          class="requirement-action-btn"
          :class="{ 'is-busy': claiming }"
          :aria-label="claimLabel"
          :aria-busy="claiming"
          :disabled="claiming"
          @click.stop="emit('claim', Boolean(requirement.clarification_reason))"
        >
          <span v-if="claiming" class="requirement-action-spinner" />
          <svg v-else class="requirement-action-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" />
          </svg>
        </button>
      </el-tooltip>

      <el-tooltip v-if="canCreateTaskForRequirement" :content="t('task_rail.create_for_requirement')" placement="top" :show-after="120" popper-class="requirement-action-tooltip">
        <button
          type="button"
          class="requirement-action-btn"
          :aria-label="t('task_rail.create_for_requirement')"
          @click.stop="emit('createTask')"
        >
          <svg class="requirement-action-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M5 12h14" />
            <path d="M12 5v14" />
          </svg>
        </button>
      </el-tooltip>

      <el-tooltip v-if="canManage" :content="t('workspace_assets.requirements.actions.edit')" placement="top" :show-after="120" popper-class="requirement-action-tooltip">
        <button
          type="button"
          class="requirement-action-btn"
          :aria-label="t('workspace_assets.requirements.actions.edit')"
          @click.stop="emit('edit')"
        >
          <svg class="requirement-action-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
            <path d="m15 5 4 4" />
          </svg>
        </button>
      </el-tooltip>

      <el-tooltip v-if="isParent && canManage" :content="t('workspace_assets.requirements.table.add_child')" placement="top" :show-after="120" popper-class="requirement-action-tooltip">
        <button
          type="button"
          class="requirement-action-btn"
          :aria-label="t('workspace_assets.requirements.table.add_child')"
          @click.stop="emit('createChild')"
        >
          <svg class="requirement-action-icon" viewBox="0 0 24 24" aria-hidden="true">
            <line x1="6" x2="6" y1="3" y2="15" />
            <circle cx="18" cy="6" r="3" />
            <circle cx="6" cy="18" r="3" />
            <path d="M18 9a9 9 0 0 1-9 9" />
          </svg>
        </button>
      </el-tooltip>

      <el-tooltip v-if="isParent && canManage" :content="t('workspace_assets.requirements.actions.split')" placement="top" :show-after="120" popper-class="requirement-action-tooltip">
        <button
          type="button"
          class="requirement-action-btn"
          :aria-label="t('workspace_assets.requirements.actions.split')"
          @click.stop="emit('split')"
        >
          <svg class="requirement-action-icon" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="6" cy="6" r="3" />
            <circle cx="6" cy="18" r="3" />
            <line x1="20" x2="8.12" y1="4" y2="15.88" />
            <line x1="14.47" x2="20" y1="14.48" y2="20" />
            <line x1="8.12" x2="12" y1="8.12" y2="12" />
          </svg>
        </button>
      </el-tooltip>

      <el-dropdown trigger="click" placement="bottom-end" @command="handleMoreCommand" @visible-change="(value: boolean) => moreOpen = value">
        <button
          type="button"
          class="requirement-action-btn"
          :aria-label="t('workspace_assets.requirements.table.more_actions')"
          :title="t('workspace_assets.requirements.table.more_actions')"
          @click.stop
        >
          <svg class="requirement-action-icon" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="1" />
            <circle cx="19" cy="12" r="1" />
            <circle cx="5" cy="12" r="1" />
          </svg>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="copy-link">
              {{ t('workspace_assets.requirements.table.copy_link') }}
            </el-dropdown-item>
            <el-dropdown-item command="copy-id">
              {{ t('workspace_assets.requirements.table.copy_id') }}
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</template>

<style scoped>
.requirement-action-cell {
  position: relative;
  display: flex;
  align-items: center;
  min-height: 32px;
  min-width: 0;
}

.requirement-action-idle {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  transition: opacity 0.2s ease;
}

.requirement-action-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.5;
  white-space: nowrap;
}

.requirement-action-chip.is-claimable {
  background: #fffbeb;
  color: #92400e;
}

.requirement-action-chip.is-task {
  background: #f1f5f9;
  color: #475569;
}

.requirement-action-toolbar {
  position: absolute;
  right: 0;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 3px 4px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
  backdrop-filter: blur(8px);
  opacity: 0;
  pointer-events: none;
  transform: translateX(4px);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 悬停整行时浮出；键盘 Tab 进入工具条时同样保持可见。 */
:global(.el-table__row:hover .requirement-action-toolbar),
.requirement-action-cell:focus-within .requirement-action-toolbar,
.requirement-action-cell.is-more-open .requirement-action-toolbar {
  opacity: 1;
  pointer-events: auto;
  transform: translateX(0);
}

:global(.el-table__row:hover .requirement-action-idle),
.requirement-action-cell:focus-within .requirement-action-idle,
.requirement-action-cell.is-more-open .requirement-action-idle {
  opacity: 0;
}

.requirement-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s ease;
}

.requirement-action-btn:hover:not(:disabled) {
  background: #f1f5f9;
  color: #0ea5e9;
  transform: translateY(-1px);
}

.requirement-action-btn:focus-visible {
  outline: 2px solid #0ea5e9;
  outline-offset: 1px;
}

.requirement-action-btn:disabled {
  cursor: progress;
  opacity: 0.65;
}

.requirement-action-icon {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.requirement-action-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid currentColor;
  border-right-color: transparent;
  border-radius: 50%;
  animation: requirement-action-spin 0.7s linear infinite;
}

@keyframes requirement-action-spin {
  to { transform: rotate(360deg); }
}

:global(.requirement-action-tooltip.el-popper) {
  padding: 3px 7px;
  border-radius: 4px;
  font-size: 11px;
  line-height: 1.4;
  font-weight: 500;
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
}

:global(.requirement-action-tooltip.el-popper.is-dark) {
  background: #0f172a;
  border-color: #0f172a;
  color: #ffffff;
}

:global(.requirement-action-tooltip.el-popper.is-dark > .el-popper__arrow::before) {
  background: #0f172a;
  border-color: #0f172a;
}

@media (hover: none) {
  .requirement-action-toolbar {
    opacity: 1;
    pointer-events: auto;
    transform: translateX(0);
  }

  .requirement-action-idle {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .requirement-action-toolbar,
  .requirement-action-idle,
  .requirement-action-btn {
    transition: none;
  }

  .requirement-action-spinner {
    animation-duration: 1.6s;
  }
}
</style>
