<!-- TaskCreateDialog: 新建任务弹窗的组合根（随弹窗打开挂载、关闭销毁，
     所有状态天然每次打开复位，无需手工 reset）。
     持有任务类型 / 侧栏状态 / 仓库控制器 / 技能勾选集，
     负责草稿校验、payload 组装、任务创建与 provision 浮窗接入。 -->
<script setup lang="ts">
import { onMounted, ref, shallowRef, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Hammer, Plus, Stethoscope, X } from 'lucide-vue-next'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { useProvisioningStore } from '@/stores/provisioning'
import TaskCreateForm from './TaskCreateForm.vue'
import SkillsPickerSidebar from './SkillsPickerSidebar.vue'
import ReposPickerSidebar from './ReposPickerSidebar.vue'
import { useWorkspaceRepos } from './composables/useWorkspaceRepos'
import { buildTaskCreatePayload, validateTaskDraft } from './lib/taskPayload'
import type { TaskCreatedEvent, TaskCreateSidebar, TaskCreateSidebarName, TaskDraftSnapshot, TaskTypeValue } from './types'

const props = defineProps<{ wsId: string }>()

const emit = defineEmits<{
  close: []
  created: [event: TaskCreatedEvent]
}>()

const { t } = useI18n()
const provisioningStore = useProvisioningStore()

// ── 弹窗内状态 ──
const taskType = shallowRef<TaskTypeValue>('DEVELOPMENT')
// 右侧滑出侧栏：同一时刻至多展开一个（Skills / 仓库两类任务均可展开）
const activeSidebar = shallowRef<TaskCreateSidebar>('none')

const creatingTask = shallowRef(false)
const formRef = useTemplateRef<{ reset: () => void }>('taskForm')

// ── 领域状态 ──
const repos = useWorkspaceRepos(() => props.wsId)
const selectedSkillIds = ref<string[]>([])

onMounted(() => {
  void repos.load()
})

const toggleSidebar = (name: TaskCreateSidebarName) => {
  activeSidebar.value = activeSidebar.value === name ? 'none' : name
}

const handleSubmit = async (draft: TaskDraftSnapshot) => {
  if (!draft.name.trim()) return
  const invalid = validateTaskDraft(draft, {
    reposTotal: repos.repos.length,
    selectedRepoCount: repos.selectedIds.length,
  })
  if (invalid) {
    const message = t(invalid.key)
    if (invalid.severity === 'warning') {
      ElMessage.warning(message)
    } else {
      ElMessage.error(message)
    }
    return
  }

  creatingTask.value = true
  try {
    const payload = buildTaskCreatePayload(draft, {
      repos: repos.repos,
      selectedRepoIds: [...repos.selectedIds],
      branchOverrides: { ...repos.branchOverrides },
      skillIds: [...selectedSkillIds.value],
    })
    const res = await api.post(`/workspaces/${props.wsId}/tasks`, payload)

    const jobId = String(res.data?.job_id || '').trim()
    const taskId = String(res.data?.task_id || '').trim()
    if (!jobId || !taskId) {
      throw new Error(t('provisioning.invalid_job_id'))
    }

    // 附件暂存到 provision 浮窗：作业成功后统一上传
    if (draft.specFile) {
      provisioningStore.setPendingTaskSpec(jobId, {
        workspaceId: props.wsId,
        taskId,
        file: draft.specFile,
      })
    }
    if (draft.diagnosisFiles.length > 0) {
      provisioningStore.setPendingTaskDocs(jobId, {
        workspaceId: props.wsId,
        taskId,
        files: [...draft.diagnosisFiles],
      })
    }

    emit('created', {
      jobId,
      taskId,
      workspaceId: props.wsId,
      expectSpecUpload: Boolean(draft.specFile),
      expectDiagnosisDocs: draft.diagnosisFiles.length > 0,
    })
    formRef.value?.reset()
  } catch (e) {
    ElMessage.error(formatApiError(e, t('dashboard.create_task_failed'), t))
    console.error('Failed to create task', e)
  } finally {
    creatingTask.value = false
  }
}
</script>

<template>
  <div class="modal glass-panel" :class="{ 'with-sidebar': activeSidebar !== 'none' }">
    <!-- 顶部 Header（标题 + 任务类型分段控制器 + 关闭按钮） -->
    <header class="modal-top-bar">
      <div class="modal-title-group">
        <div class="modal-title-icon">
          <Plus class="w-4 h-4 text-primary" />
        </div>
        <div class="modal-title-text">
          <h2>{{ $t('dashboard.new_task') }}</h2>
        </div>
      </div>

      <!-- 紧凑型任务类型分段控制器 (Segmented Tab Control) -->
      <div class="task-type-segmented">
        <button
          type="button"
          class="segmented-btn task-type-card"
          :class="{ active: taskType === 'DEVELOPMENT' }"
          @click="taskType = 'DEVELOPMENT'"
        >
          <Hammer class="w-3.5 h-3.5" />
          <span>{{ $t('task_types.development') }}</span>
        </button>
        <button
          type="button"
          class="segmented-btn task-type-card"
          :class="{ active: taskType === 'DIAGNOSIS' }"
          @click="taskType = 'DIAGNOSIS'"
        >
          <Stethoscope class="w-3.5 h-3.5" />
          <span>{{ $t('task_types.diagnosis') }}</span>
        </button>
      </div>

      <button type="button" class="modal-close-btn" :title="$t('common.cancel')" @click="emit('close')">
        <X class="w-4 h-4" />
      </button>
    </header>

    <!-- 弹窗主体布局（主表单 + 可平滑滑出的侧边栏） -->
    <div class="modal-body-layout">
      <TaskCreateForm
        ref="taskForm"
        :ws-id="props.wsId"
        :task-type="taskType"
        :creating="creatingTask"
        :repos-total="repos.repos.length"
        :selected-repo-count="repos.selectedIds.length"
        :selected-skill-count="selectedSkillIds.length"
        :active-sidebar="activeSidebar"
        @submit="handleSubmit"
        @cancel="emit('close')"
        @toggle-sidebar="toggleSidebar"
      />

      <!-- 右侧平滑横向展开的 Skills 侧边栏 -->
      <SkillsPickerSidebar
        v-model:selected-ids="selectedSkillIds"
        :ws-id="props.wsId"
        :open="activeSidebar === 'skills'"
        @close="activeSidebar = 'none'"
      />

      <!-- 右侧平滑横向展开的仓库选择侧边栏 -->
      <ReposPickerSidebar
        :controller="repos"
        :open="activeSidebar === 'repos'"
        @close="activeSidebar = 'none'"
      />
    </div>
  </div>
</template>

<style scoped>
.modal {
  width: 95%;
  max-width: 660px;
  max-height: 88vh;
  background-color: #ffffff;
  border-radius: 16px;
  box-shadow: 0 20px 25px -5px rgba(15, 23, 42, 0.1), 0 10px 10px -5px rgba(15, 23, 42, 0.04), 0 0 0 1px rgba(226, 232, 240, 0.8);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: max-width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.modal.with-sidebar {
  max-width: 1080px;
}

/* 顶部 Header（标题 + 紧凑分段控制器 + 关闭按钮） */
.modal-top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.4rem 0.9rem;
  border-bottom: 1px solid #f1f5f9;
  background: #ffffff;
  flex-shrink: 0;
  gap: 12px;
}

.modal-title-group {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.modal-title-icon {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: #f0f9ff;
  border: 1px solid #e0f2fe;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-title-text h2 {
  margin: 0;
  font-size: 1.08rem;
  font-weight: 700;
  color: #0f172a;
}

/* 紧凑分段控制器 */
.task-type-segmented {
  display: flex;
  background: #f1f5f9;
  padding: 3px;
  border-radius: 8px;
  gap: 2px;
}

.segmented-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 6px;
  border: none;
  background: transparent;
  font-size: 0.78rem;
  font-weight: 600;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.segmented-btn:hover {
  color: #0f172a;
}

.segmented-btn.active {
  background: #ffffff;
  color: #0ea5e9;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.modal-close-btn {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
}

.modal-close-btn:hover {
  background: #f1f5f9;
  color: #334155;
}

/* 弹窗主体分栏布局 */
.modal-body-layout {
  display: flex;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
</style>
