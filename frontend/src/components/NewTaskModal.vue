<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Plus,
  Upload,
  Loader2,
  ChevronRight,
  Sparkles,
  Globe,
  FolderOpen,
  GitFork,
  Hammer,
  Stethoscope,
  FileText,
  X,
  Search,
  RefreshCw,
  Clock,
} from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { useProvisioningStore } from '@/stores/provisioning'

const props = defineProps<{
  show: boolean
  wsId: string
}>()
const { t } = useI18n()

const emit = defineEmits<{
  close: []
  created: [{ jobId: string; taskId: string; workspaceId: string; expectSpecUpload: boolean; expectDiagnosisDocs: boolean }]
}>()

type TaskTypeValue = 'DEVELOPMENT' | 'DIAGNOSIS'
const taskType = ref<TaskTypeValue>('DEVELOPMENT')
const isDiagnosisTask = computed(() => taskType.value === 'DIAGNOSIS')
const newTaskName = ref('')
const newTaskDesc = ref('')
const newTaskPhenomenon = ref('')
const newTaskPriority = ref('P2')
const requirementDuration = ref(8)
const creatingTask = ref(false)
const selectedFileName = ref('')
const pendingSpecFile = ref<File | null>(null)
const diagnosisFiles = ref<File[]>([])
const provisioningStore = useProvisioningStore()
const overlayCloseArmed = ref(false)

// Skills 侧边栏展开状态
const showSkillsSidebar = ref(false)

// Worktree 仓库环境列表
const workspaceRepos = ref<any[]>([])
const reposLoading = ref(false)

// Skills 服务端状态
const skills = ref<any[]>([])
const skillsLoading = ref(false)
const skillKeyword = ref('')
const skillScope = ref<'all' | 'workspace' | 'global'>('all')
const skillPage = ref(1)
const skillPageSize = ref(8)
const skillTotal = ref(0)
const selectedSkillIds = ref<string[]>([])
let searchDebounceTimer: ReturnType<typeof setTimeout> | null = null

const totalPages = computed(() => Math.max(1, Math.ceil(skillTotal.value / skillPageSize.value)))
const isDraftSkill = (skill: any) => Boolean(skill?.has_pending_changes || skill?.publish_state === 'DRAFT')
const hasDraftSkills = computed(() => skills.value.some((skill) => isDraftSkill(skill)))

const isCurrentPageAllSelected = computed(() => {
  if (skills.value.length === 0) return false
  return skills.value.every((s) => selectedSkillIds.value.includes(s.id))
})

const selectedSkillCount = computed(() => selectedSkillIds.value.length)

const loadWorkspaceRepos = async () => {
  reposLoading.value = true
  try {
    const res = await api.get('/workspaces/' + props.wsId)
    workspaceRepos.value = res.data?.repositories || []
  } catch (e) {
    workspaceRepos.value = []
  } finally {
    reposLoading.value = false
  }
}

const loadSkills = async (targetPage = skillPage.value) => {
  skillsLoading.value = true
  skillPage.value = targetPage
  try {
    const res = await api.get('/skills', {
      params: {
        workspace_id: props.wsId,
        scope: skillScope.value,
        keyword: skillKeyword.value.trim(),
        page: skillPage.value,
        page_size: skillPageSize.value,
      },
    })
    skills.value = res.data?.items || []
    skillTotal.value = res.data?.total || 0
  } catch (e) {
    console.error('Failed to load skills', e)
    skills.value = []
    skillTotal.value = 0
  } finally {
    skillsLoading.value = false
  }
}

const onSearchInput = () => {
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  searchDebounceTimer = setTimeout(() => {
    skillPage.value = 1
    void loadSkills(1)
  }, 300)
}

const clearSearch = () => {
  skillKeyword.value = ''
  skillPage.value = 1
  void loadSkills(1)
}

const onScopeChange = (scope: 'all' | 'workspace' | 'global') => {
  if (skillScope.value === scope) return
  skillScope.value = scope
  skillPage.value = 1
  void loadSkills(1)
}

const prevSkillPage = () => {
  if (skillPage.value > 1) {
    void loadSkills(skillPage.value - 1)
  }
}

const nextSkillPage = () => {
  if (skillPage.value < totalPages.value) {
    void loadSkills(skillPage.value + 1)
  }
}

const toggleSkill = (skillId: string) => {
  const idx = selectedSkillIds.value.indexOf(skillId)
  if (idx >= 0) {
    selectedSkillIds.value.splice(idx, 1)
  } else {
    selectedSkillIds.value.push(skillId)
  }
}

const toggleCurrentPageAll = () => {
  if (isCurrentPageAllSelected.value) {
    const pageIds = new Set(skills.value.map((s) => s.id))
    selectedSkillIds.value = selectedSkillIds.value.filter((id) => !pageIds.has(id))
  } else {
    for (const s of skills.value) {
      if (!selectedSkillIds.value.includes(s.id)) {
        selectedSkillIds.value.push(s.id)
      }
    }
  }
}

const handleFileUpload = (event: any) => {
  const file = event.target.files[0]
  if (!file) return
  pendingSpecFile.value = file
  selectedFileName.value = file.name
}

const handleDiagnosisFiles = (event: any) => {
  const files = Array.from(event.target.files || []) as File[]
  if (files.length === 0) return
  diagnosisFiles.value = [...diagnosisFiles.value, ...files]
  event.target.value = ''
}

const removeDiagnosisFile = (index: number) => {
  diagnosisFiles.value.splice(index, 1)
}

const toggleSkillsSidebar = () => {
  showSkillsSidebar.value = !showSkillsSidebar.value
}

const handleCreateTask = async () => {
  if (!newTaskName.value) return
  if (isDiagnosisTask.value && !newTaskPhenomenon.value.trim()) {
    ElMessage.error(t('diagnosis.phenomenon_required'))
    return
  }
  creatingTask.value = true
  try {
    const payload: Record<string, unknown> = {
      name: newTaskName.value,
      description: newTaskDesc.value,
      task_type: taskType.value,
      skill_ids: selectedSkillIds.value,
    }
    if (isDiagnosisTask.value) {
      payload.description = undefined
      payload.phenomenon = newTaskPhenomenon.value
      payload.priority = newTaskPriority.value
    } else {
      payload.requirement_duration_hours = Number(requirementDuration.value)
    }
    const res = await api.post(`/workspaces/${props.wsId}/tasks`, payload)

    const jobId = String(res.data?.job_id || '').trim()
    const taskId = String(res.data?.task_id || '').trim()
    if (!jobId || !taskId) {
      throw new Error(t('provisioning.invalid_job_id'))
    }

    if (pendingSpecFile.value) {
      provisioningStore.setPendingTaskSpec(jobId, {
        workspaceId: props.wsId,
        taskId,
        file: pendingSpecFile.value,
      })
    }
    if (diagnosisFiles.value.length > 0) {
      provisioningStore.setPendingTaskDocs(jobId, {
        workspaceId: props.wsId,
        taskId,
        files: [...diagnosisFiles.value],
      })
    }

    emit('created', {
      jobId,
      taskId,
      workspaceId: props.wsId,
      expectSpecUpload: Boolean(pendingSpecFile.value),
      expectDiagnosisDocs: diagnosisFiles.value.length > 0,
    })
    resetForm()
  } catch (e) {
    ElMessage.error(formatApiError(e, t('dashboard.create_task_failed'), t))
    console.error('Failed to create task', e)
  } finally {
    creatingTask.value = false
  }
}

const resetForm = () => {
  taskType.value = 'DEVELOPMENT'
  newTaskName.value = ''
  newTaskDesc.value = ''
  newTaskPhenomenon.value = ''
  newTaskPriority.value = 'P2'
  requirementDuration.value = 8
  pendingSpecFile.value = null
  diagnosisFiles.value = []
  selectedFileName.value = ''
  selectedSkillIds.value = []
  showSkillsSidebar.value = false
  skillKeyword.value = ''
  skillScope.value = 'all'
  skillPage.value = 1
  workspaceRepos.value = []
}

const close = () => {
  resetForm()
  emit('close')
}

const armOverlayClose = (event: PointerEvent) => {
  if (event.button !== 0) return
  overlayCloseArmed.value = true
}

const cancelOverlayClose = () => {
  overlayCloseArmed.value = false
}

const finishOverlayClose = () => {
  if (!overlayCloseArmed.value) return
  overlayCloseArmed.value = false
  close()
}

watch(
  () => props.show,
  async (visible) => {
    if (visible) {
      await Promise.all([loadSkills(1), loadWorkspaceRepos()])
    } else {
      overlayCloseArmed.value = false
      resetForm()
    }
  },
  { immediate: true },
)

onMounted(() => {
  window.addEventListener('blur', cancelOverlayClose)
})

onBeforeUnmount(() => {
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer)
  window.removeEventListener('blur', cancelOverlayClose)
})
</script>

<template>
  <div
    v-if="show"
    class="modal-overlay"
    @pointerdown.self="armOverlayClose"
    @pointerup.self="finishOverlayClose"
    @pointerleave.self="cancelOverlayClose"
    @pointercancel.self="cancelOverlayClose"
  >
    <div class="modal glass-panel" :class="{ 'with-sidebar': showSkillsSidebar && !isDiagnosisTask }">
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

        <button type="button" class="modal-close-btn" :title="$t('common.cancel')" @click="close">
          <X class="w-4 h-4" />
        </button>
      </header>

      <!-- 弹窗主体布局（主表单 + 可平滑滑出的 Skills 侧边栏） -->
      <div class="modal-body-layout">
        <!-- 主表单区域 -->
        <form @submit.prevent="handleCreateTask" class="modal-form-main">
          <!-- 行 1：任务名称 -->
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">
                <span>{{ $t('dashboard.task_name') }}</span>
                <span class="required">*</span>
              </label>
              <input
                v-model="newTaskName"
                type="text"
                class="input-field primary-input"
                required
                :placeholder="$t('dashboard.task_name_placeholder')"
              />
            </div>
          </div>

          <!-- 行 2：双列网格（研发态：工时 + 规范文档上传；诊断态：优先级 + 文档上传） -->
          <div class="form-row form-grid-2">
            <!-- 研发态工时 -->
            <div v-if="!isDiagnosisTask" class="form-group">
              <label class="form-label">
                <Clock class="w-3.5 h-3.5 text-slate-400" />
                <span>{{ $t('dashboard.requirement_duration') }}</span>
              </label>
              <div class="input-with-suffix">
                <input
                  v-model="requirementDuration"
                  type="number"
                  class="input-field"
                  required
                  min="0"
                  step="0.5"
                  :placeholder="$t('dashboard.requirement_placeholder')"
                />
                <span class="input-suffix">h</span>
              </div>
            </div>

            <!-- 诊断态优先级 -->
            <div v-if="isDiagnosisTask" class="form-group">
              <label class="form-label">
                <span>{{ $t('diagnosis.priority') }}</span>
              </label>
              <div class="priority-options">
                <button
                  v-for="p in ['P0', 'P1', 'P2', 'P3']"
                  :key="p"
                  type="button"
                  class="priority-option"
                  :class="{ active: newTaskPriority === p, [`prio-${p.toLowerCase()}`]: true }"
                  @click="newTaskPriority = p"
                >
                  {{ p }}
                </button>
              </div>
            </div>

            <!-- 规范文档上传（研发态，保留已有样式与结构） -->
            <div v-if="!isDiagnosisTask" class="form-group">
              <label class="form-label">
                <FileText class="w-3.5 h-3.5 text-slate-400" />
                <span>{{ $t('dashboard.spec_doc') }}</span>
              </label>
              <div class="file-upload-box glass-panel compact-upload">
                <Upload v-if="!creatingTask" class="w-4 h-4 text-primary flex-shrink-0" />
                <Loader2 v-else class="w-4 h-4 spin text-primary flex-shrink-0" />
                <div class="file-name text-slate-600">
                  {{ selectedFileName || $t('dashboard.spec_placeholder') }}
                </div>
                <input
                  :id="`spec-upload-${props.wsId}`"
                  type="file"
                  class="hidden-input"
                  accept=".pdf,.doc,.docx,.md,.txt"
                  @change="handleFileUpload"
                />
                <label :for="`spec-upload-${props.wsId}`" class="btn-primary file-choose-btn">
                  {{ $t('common.select') }}
                </label>
              </div>
            </div>

            <!-- 诊断态文档上传 -->
            <div v-if="isDiagnosisTask" class="form-group">
              <label class="form-label">
                <FileText class="w-3.5 h-3.5 text-slate-400" />
                <span>{{ $t('diagnosis.docs_upload_label') }}</span>
              </label>
              <div class="file-upload-box glass-panel compact-upload">
                <Upload v-if="!creatingTask" class="w-4 h-4 text-primary flex-shrink-0" />
                <Loader2 v-else class="w-4 h-4 spin text-primary flex-shrink-0" />
                <div class="file-name text-slate-600">
                  {{ $t('diagnosis.docs_upload_placeholder') }}
                </div>
                <input
                  :id="`diag-docs-upload-${props.wsId}`"
                  type="file"
                  class="hidden-input"
                  multiple
                  @change="handleDiagnosisFiles"
                />
                <label :for="`diag-docs-upload-${props.wsId}`" class="btn-primary file-choose-btn">
                  {{ $t('common.select') }}
                </label>
              </div>
            </div>
          </div>

          <!-- 诊断模式已选文件列表 -->
          <div v-if="isDiagnosisTask && diagnosisFiles.length > 0" class="diagnosis-files-list">
            <div v-for="(file, index) in diagnosisFiles" :key="`${file.name}-${index}`" class="diagnosis-file-row">
              <FileText class="w-3.5 h-3.5 diagnosis-file-icon" />
              <span class="diagnosis-file-name">{{ file.name }}</span>
              <button type="button" class="diagnosis-file-remove" :title="$t('common.delete')" @click="removeDiagnosisFile(index)">
                <X class="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          <!-- 行 3：初始化提示词 / 现象描述 -->
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">
                <span>{{ isDiagnosisTask ? $t('diagnosis.phenomenon') : $t('dashboard.description') }}</span>
                <span v-if="isDiagnosisTask" class="required">*</span>
              </label>
              <textarea
                v-if="!isDiagnosisTask"
                v-model="newTaskDesc"
                class="input-field textarea-field"
                rows="3"
                :placeholder="$t('dashboard.desc_placeholder')"
              />
              <textarea
                v-else
                v-model="newTaskPhenomenon"
                class="input-field textarea-field"
                rows="3"
                required
                :placeholder="$t('diagnosis.phenomenon_placeholder')"
              />
            </div>
          </div>

          <!-- 行 4：运行环境与扩展工具组（垂直分层独立展示，彻底解决遮挡与挤压问题） -->
          <div v-if="!isDiagnosisTask" class="form-meta-container">
            <!-- 1. Worktree 关联仓库展示（独占一行，横向充足，各仓库标签清晰，绝不遮挡） -->
            <div v-if="workspaceRepos.length > 0" class="meta-env-card env-card">
              <div class="meta-env-header">
                <div class="meta-env-title">
                  <GitFork class="w-3.5 h-3.5 text-primary" />
                  <span>{{ $t('dashboard.task_repo_preview', { count: workspaceRepos.length }) }}</span>
                </div>
                <div class="meta-repo-chips">
                  <span
                    v-for="repo in workspaceRepos"
                    :key="repo.id"
                    class="repo-chip env-repo-item"
                    :title="`${repo.repo_name} (${repo.branch_name}) · ${repo.repo_url}`"
                  >
                    <span class="repo-chip-dot" :class="{ failed: repo.state === 'FAILED' }"></span>
                    <span class="repo-chip-name">{{ repo.repo_name }}</span>
                    <span class="repo-chip-branch">{{ repo.branch_name }}</span>
                  </span>
                </div>
              </div>
            </div>

            <!-- 2. Skills 载入触发条（独占一行，整行可点击展开/收起右侧侧栏） -->
            <div
              class="meta-skills-bar skills-entry-card"
              :class="{ active: showSkillsSidebar, 'has-selection': selectedSkillCount > 0 }"
              @click="toggleSkillsSidebar"
            >
              <div class="skills-bar-left">
                <div class="skills-bar-icon-box">
                  <Sparkles class="w-3.5 h-3.5 text-primary" />
                </div>
                <span class="skills-bar-title">{{ $t('skills.task_panel.expand_title') }}</span>
                <span class="skills-bar-badge" :class="{ 'has-selected': selectedSkillCount > 0 }">
                  {{ selectedSkillCount > 0
                    ? $t('skills.task_panel.selected_count', { count: selectedSkillCount })
                    : $t('skills.task_panel.none_selected')
                  }}
                </span>
              </div>
              <div class="skills-bar-right">
                <span class="skills-bar-action-text">{{ showSkillsSidebar ? $t('skills.task_panel.close_panel') : $t('skills.task_panel.select_skills') }}</span>
                <ChevronRight class="w-3.5 h-3.5 chevron-icon" :class="{ open: showSkillsSidebar }" />
              </div>
            </div>
          </div>

          <!-- 底部操作区 -->
          <div class="modal-footer">
            <div class="footer-left-hint">
              <span v-if="!isDiagnosisTask && selectedSkillCount > 0" class="footer-skills-hint">
                <Sparkles class="w-3.5 h-3.5 text-primary" />
                {{ $t('skills.task_panel.selected_count', { count: selectedSkillCount }) }}
              </span>
            </div>
            <div class="footer-actions">
              <button type="button" class="btn-secondary modal-btn" @click="close">{{ $t('common.cancel') }}</button>
              <button type="submit" class="btn-primary modal-btn" :disabled="creatingTask">
                <Loader2 v-if="creatingTask" class="w-4 h-4 spin" />
                <span>{{ creatingTask ? $t('common.loading') : $t('chat.initialize') }}</span>
              </button>
            </div>
          </div>
        </form>

        <!-- 右侧平滑滑出的 Skills 侧边栏 -->
        <aside v-if="showSkillsSidebar && !isDiagnosisTask" class="modal-skills-sidebar">
          <!-- 侧栏头部 -->
          <div class="skills-sidebar-header">
            <div class="skills-sidebar-title-row">
              <div class="skills-sidebar-title">
                <Sparkles class="w-4 h-4 text-primary" />
                <h3>{{ $t('skills.task_panel.sidebar_title') }}</h3>
              </div>
              <div class="skills-header-actions">
                <span class="skills-selected-badge" :class="{ 'has-selected': selectedSkillCount > 0 }">
                  {{ $t('skills.task_panel.selected_count', { count: selectedSkillCount }) }}
                </span>
                <button
                  type="button"
                  class="sidebar-close-btn"
                  :title="$t('skills.task_panel.close_panel')"
                  @click="showSkillsSidebar = false"
                >
                  <X class="w-4 h-4" />
                </button>
              </div>
            </div>
            <p class="skills-sidebar-subtitle">{{ $t('skills.task_panel.sidebar_subtitle') }}</p>

            <!-- 搜索与快捷操作（搜索框纯白背景） -->
            <div class="skills-sidebar-tools">
              <!-- 服务端关键字搜索输入框：纯白背景 -->
              <div class="skills-search-wrapper">
                <Search class="w-4 h-4 skills-search-icon" />
                <input
                  v-model="skillKeyword"
                  type="text"
                  class="skills-search-input"
                  :placeholder="$t('skills.task_panel.search_placeholder')"
                  @input="onSearchInput"
                />
                <button
                  v-if="skillKeyword"
                  type="button"
                  class="skills-search-clear"
                  @click="clearSearch"
                >
                  <X class="w-3.5 h-3.5" />
                </button>
              </div>

              <!-- 刷新按钮 -->
              <button
                type="button"
                class="tool-icon-btn"
                :title="$t('skills.task_panel.refresh')"
                :disabled="skillsLoading"
                @click="loadSkills(skillPage)"
              >
                <RefreshCw class="w-3.5 h-3.5" :class="{ spin: skillsLoading }" />
              </button>
            </div>

            <!-- 范围过滤 Pills + 全选当前页 -->
            <div class="skills-filter-row">
              <div class="scope-pills">
                <button
                  type="button"
                  class="scope-pill"
                  :class="{ active: skillScope === 'all' }"
                  @click="onScopeChange('all')"
                >
                  {{ $t('skills.task_panel.scope_all') }}
                </button>
                <button
                  type="button"
                  class="scope-pill"
                  :class="{ active: skillScope === 'workspace' }"
                  @click="onScopeChange('workspace')"
                >
                  <FolderOpen class="w-3.5 h-3.5" />
                  {{ $t('skills.task_panel.scope_workspace') }}
                </button>
                <button
                  type="button"
                  class="scope-pill"
                  :class="{ active: skillScope === 'global' }"
                  @click="onScopeChange('global')"
                >
                  <Globe class="w-3.5 h-3.5" />
                  {{ $t('skills.task_panel.scope_global') }}
                </button>
              </div>

              <button
                type="button"
                class="tool-text-btn"
                :disabled="skills.length === 0"
                @click="toggleCurrentPageAll"
              >
                {{ isCurrentPageAllSelected ? $t('skills.task_panel.clear_all') : $t('skills.task_panel.select_all') }}
              </button>
            </div>
          </div>

          <!-- 草稿技能提示 -->
          <div v-if="hasDraftSkills" class="skills-state-note">
            {{ $t('skills.task_panel.draft_publish_hint') }}
          </div>

          <!-- 技能卡片列表内容区（独立滚动） -->
          <div class="skills-sidebar-body">
            <div v-if="skillsLoading" class="skills-state center">
              <Loader2 class="w-6 h-6 spin text-primary" />
              <span>{{ $t('skills.task_panel.loading') }}</span>
            </div>

            <div v-else-if="skills.length === 0 && skillKeyword" class="skills-state empty center">
              {{ $t('skills.task_panel.search_empty') }}
            </div>

            <div v-else-if="skills.length === 0" class="skills-state empty center">
              {{ $t('skills.task_panel.empty') }}
            </div>

            <div v-else class="skills-list">
              <div
                v-for="skill in skills"
                :key="skill.id"
                class="skill-card-item"
                :class="{ selected: selectedSkillIds.includes(skill.id) }"
                @click="toggleSkill(skill.id)"
              >
                <div class="skill-checkbox-wrapper">
                  <input
                    type="checkbox"
                    :checked="selectedSkillIds.includes(skill.id)"
                    @click.stop
                    @change="toggleSkill(skill.id)"
                  />
                </div>
                <div class="skill-item-body">
                  <div class="skill-title-row">
                    <div class="skill-name-group">
                      <FolderOpen v-if="skill.dimension === 'WORKSPACE'" class="w-3.5 h-3.5 text-primary flex-shrink-0" />
                      <Globe v-else class="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                      <span class="skill-name">{{ skill.name }}</span>
                    </div>
                    <span class="skill-status-tag" :class="{ draft: isDraftSkill(skill) }">
                      {{ isDraftSkill(skill) ? $t('skills.task_panel.status_draft') : $t('skills.task_panel.status_published') }}
                    </span>
                  </div>
                  <div class="skill-desc" :title="skill.description">{{ skill.description || $t('skills.list.no_description') }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 服务端分页底部栏（与 skills 配置页面风格完全一致） -->
          <footer class="skills-pagination">
            <button
              class="btn-secondary mini page-nav-btn"
              :disabled="skillPage <= 1 || skillsLoading"
              @click="prevSkillPage"
            >
              {{ $t('skills.list.prev_page') }}
            </button>
            <div class="pagination-info">
              <span class="skills-page-info">
                {{ $t('skills.list.page_info', { page: skillPage, total: totalPages }) }}
              </span>
              <span class="pagination-badge">
                {{ skillTotal }}
              </span>
            </div>
            <button
              class="btn-secondary mini page-nav-btn"
              :disabled="skillPage >= totalPages || skillsLoading"
              @click="nextSkillPage"
            >
              {{ $t('skills.list.next_page') }}
            </button>
          </footer>
        </aside>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: var(--space-4);
}

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

/* 主表单区 */
.modal-form-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 1.2rem 1.4rem 1.2rem;
  display: flex;
  flex-direction: column;
  gap: 0.95rem;
}

.form-row {
  display: flex;
  flex-direction: column;
}

.form-grid-2 {
  display: grid;
  grid-template-columns: 1fr 1.35fr;
  gap: 12px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.form-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #334155;
  display: flex;
  align-items: center;
  gap: 4px;
}

.required {
  color: #ef4444;
}

.input-field {
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-family: inherit;
  font-size: 0.875rem;
  width: 100%;
  box-sizing: border-box;
  background: #ffffff;
  color: #0f172a;
  transition: all 0.2s;
}

.input-field:focus {
  border-color: #0ea5e9;
  outline: none;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.12);
}

.input-field::placeholder {
  color: #94a3b8;
  font-size: 0.82rem;
}

.primary-input {
  font-weight: 500;
}

.input-with-suffix {
  position: relative;
  display: flex;
  align-items: center;
}

.input-with-suffix input {
  padding-right: 28px;
}

.input-suffix {
  position: absolute;
  right: 10px;
  font-size: 0.78rem;
  font-weight: 600;
  color: #94a3b8;
  pointer-events: none;
}

.textarea-field {
  resize: vertical;
  min-height: 80px;
  line-height: 1.45;
}

/* 优先级选择胶囊 */
.priority-options {
  display: flex;
  gap: 6px;
}

.priority-option {
  flex: 1;
  padding: 6px 0;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #ffffff;
  font-size: 0.78rem;
  font-weight: 700;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s;
  text-align: center;
}

.priority-option:hover {
  border-color: #cbd5e1;
  background: #f8fafc;
}

.priority-option.active.prio-p0 {
  border-color: #ef4444;
  background: #fef2f2;
  color: #b91c1c;
}

.priority-option.active.prio-p1 {
  border-color: #f97316;
  background: #fff7ed;
  color: #c2410c;
}

.priority-option.active.prio-p2 {
  border-color: #0ea5e9;
  background: #f0f9ff;
  color: #0369a1;
}

.priority-option.active.prio-p3 {
  border-color: #94a3b8;
  background: #f1f5f9;
  color: #475569;
}

/* 规范文档上传区域（原有规范文档样式严格保持不变） */
.file-upload-box {
  border: 1px dashed var(--color-primary-100);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3);
  border-radius: var(--radius-md);
}

.compact-upload {
  padding: 6px 10px;
  min-height: 38px;
  box-sizing: border-box;
}

.file-upload-box:hover {
  border-style: solid;
  border-color: var(--color-primary-500);
}

.file-name {
  flex: 1;
  font-size: 0.8rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-choose-btn {
  padding: 3px 10px;
  font-size: 0.72rem;
  cursor: pointer;
  white-space: nowrap;
}

.hidden-input {
  display: none;
}

/* 运行环境与扩展容器（垂直两行排列，彻底避免横向重叠与遮挡） */
.form-meta-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 2px;
}

/* 1. Worktree 仓库环境展示卡片 */
.meta-env-card {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f8fafc;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.meta-env-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px;
}

.meta-env-title {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 0.76rem;
  font-weight: 700;
  color: #334155;
}

.meta-repo-chips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.repo-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 7px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.72rem;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}

.repo-chip-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #10b981;
}

.repo-chip-dot.failed {
  background: #ef4444;
}

.repo-chip-name {
  font-weight: 600;
  color: #0f172a;
}

.repo-chip-branch {
  font-family: var(--font-mono, monospace);
  font-size: 0.68rem;
  color: #0369a1;
  background: #e0f2fe;
  padding: 0 4px;
  border-radius: 3px;
}

/* 2. Skills 载入触发条（整行可点击） */
.meta-skills-bar {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #ffffff;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.meta-skills-bar:hover {
  border-color: #7dd3fc;
  background: #f0f9ff;
  transform: translateY(-1px);
}

.meta-skills-bar.active {
  border-color: #0ea5e9;
  background: #f0f9ff;
  box-shadow: 0 0 0 1px #0ea5e9, 0 2px 6px rgba(14, 165, 233, 0.08);
}

.skills-bar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.skills-bar-icon-box {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: #f0f9ff;
  border: 1px solid #e0f2fe;
  display: flex;
  align-items: center;
  justify-content: center;
}

.skills-bar-title {
  font-size: 0.8rem;
  font-weight: 700;
  color: #0f172a;
}

.skills-bar-badge {
  font-size: 0.7rem;
  padding: 1px 7px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  font-weight: 500;
}

.skills-bar-badge.has-selected {
  background: #0ea5e9;
  color: #ffffff;
  font-weight: 600;
}

.skills-bar-right {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #0ea5e9;
  font-size: 0.76rem;
  font-weight: 600;
}

.skills-bar-action-text {
  font-size: 0.76rem;
}

.chevron-icon {
  transition: transform 0.2s;
}

.chevron-icon.open {
  transform: rotate(90deg);
}

/* 诊断模式文件列表 */
.diagnosis-files-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: -4px;
}

.diagnosis-file-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #f8fafc;
  font-size: 0.76rem;
}

.diagnosis-file-icon {
  flex-shrink: 0;
  color: #0ea5e9;
}

.diagnosis-file-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #1e293b;
  font-weight: 500;
}

.diagnosis-file-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  transition: color 0.2s;
}

.diagnosis-file-remove:hover {
  color: #ef4444;
}

/* 底部操作区 */
.modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
}

.footer-left-hint {
  display: flex;
  align-items: center;
  font-size: 0.74rem;
  color: #64748b;
}

.footer-skills-hint {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-weight: 600;
  color: #0369a1;
  background: #f0f9ff;
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid #e0f2fe;
}

.footer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.modal-btn {
  padding: 7px 16px;
  font-size: 0.84rem;
  border-radius: 8px;
}

.btn-secondary {
  background: #ffffff;
  color: #475569;
  border: 1px solid #cbd5e1;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary:hover {
  background: #f8fafc;
  border-color: #94a3b8;
  color: #0f172a;
}

.btn-secondary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn-primary {
  background: #0ea5e9;
  color: #ffffff !important;
  border: none;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 4px 6px -1px rgba(14, 165, 233, 0.2);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.btn-primary:hover {
  background: #0284c7;
  transform: translateY(-1px);
  box-shadow: 0 8px 12px -2px rgba(14, 165, 233, 0.25);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

/* 右侧平滑滑出的 Skills 侧边栏 */
.modal-skills-sidebar {
  width: 440px;
  flex-shrink: 0;
  border-left: 1px solid #e2e8f0;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  animation: slideInRight 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

@keyframes slideInRight {
  from {
    opacity: 0;
    transform: translateX(16px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.skills-sidebar-header {
  padding: 1rem 1.25rem 0.75rem;
  border-bottom: 1px solid #e2e8f0;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

.skills-sidebar-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.skills-sidebar-title {
  display: flex;
  align-items: center;
  gap: 6px;
}

.skills-sidebar-title h3 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 700;
  color: #0f172a;
}

.skills-header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.skills-selected-badge {
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #64748b;
  font-weight: 500;
}

.skills-selected-badge.has-selected {
  background: #0ea5e9;
  color: #ffffff;
  font-weight: 600;
}

.sidebar-close-btn {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
}

.sidebar-close-btn:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.skills-sidebar-subtitle {
  margin: 0;
  font-size: 0.73rem;
  color: #64748b;
  line-height: 1.35;
}

.skills-sidebar-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
}

.skills-search-wrapper {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
}

.skills-search-icon {
  position: absolute;
  left: 9px;
  color: #94a3b8;
  pointer-events: none;
}

/* 搜索框：纯白背景，非 disabled 灰底 */
.skills-search-input {
  width: 100%;
  padding: 6px 26px 6px 28px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 0.78rem;
  background: #ffffff !important;
  color: #0f172a;
  outline: none;
  transition: all 0.2s;
}

.skills-search-input:focus {
  border-color: #0ea5e9;
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.15);
}

.skills-search-clear {
  position: absolute;
  right: 6px;
  border: none;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  padding: 2px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.skills-filter-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.scope-pills {
  display: flex;
  gap: 4px;
}

.scope-pill {
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #64748b;
  font-size: 0.72rem;
  font-weight: 500;
  padding: 3px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.scope-pill:hover {
  border-color: #cbd5e1;
  background: #f8fafc;
  color: #1e293b;
}

.scope-pill.active {
  background: #0ea5e9;
  color: #ffffff;
  border-color: #0ea5e9;
  font-weight: 600;
}

.tool-text-btn {
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #475569;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.tool-text-btn:hover {
  background: #f1f5f9;
  color: #0ea5e9;
  border-color: #cbd5e1;
}

.tool-text-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.tool-icon-btn {
  width: 28px;
  height: 28px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  color: #475569;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.tool-icon-btn:hover {
  background: #f1f5f9;
  color: #0ea5e9;
}

.tool-icon-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.skills-state-note {
  margin: 8px 12px 0;
  padding: 6px 10px;
  border: 1px solid #fde68a;
  background: #fffbeb;
  color: #92400e;
  border-radius: 8px;
  font-size: 0.72rem;
  line-height: 1.35;
}

/* 列表区 */
.skills-sidebar-body {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.skills-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.skill-card-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  background: #ffffff;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.skill-card-item:hover {
  border-color: #7dd3fc;
  background: #f0f9ff;
  transform: translateY(-1px);
}

.skill-card-item.selected {
  border-color: #0ea5e9;
  background: #f0f9ff;
  box-shadow: 0 0 0 1px #0ea5e9, 0 2px 6px rgba(14, 165, 233, 0.08);
}

.skill-checkbox-wrapper {
  margin-top: 2px;
}

.skill-checkbox-wrapper input[type="checkbox"] {
  cursor: pointer;
  accent-color: #0ea5e9;
  width: 15px;
  height: 15px;
}

.skill-item-body {
  min-width: 0;
  flex: 1;
}

.skill-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.skill-name-group {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.skill-name {
  font-size: 0.82rem;
  font-weight: 700;
  color: #0f172a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-card-item.selected .skill-name {
  color: #0369a1;
}

.skill-status-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 0.65rem;
  font-weight: 600;
  color: #15803d;
  background: #dcfce7;
  border: 1px solid #bbf7d0;
  white-space: nowrap;
  flex-shrink: 0;
}

.skill-status-tag.draft {
  color: #c2410c;
  background: #ffedd5;
  border-color: #fed7aa;
}

.skill-desc {
  margin-top: 3px;
  font-size: 0.72rem;
  color: #64748b;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 分页样式（与 skills 配置页面完全对齐） */
.skills-pagination {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-top: 1px solid #f1f5f9;
  background: #ffffff;
  flex-shrink: 0;
}

.pagination-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.pagination-badge {
  background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
  color: #fff;
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 700;
  box-shadow: 0 2px 4px rgba(14, 165, 233, 0.25);
}

.skills-page-info {
  min-width: 6rem;
  text-align: center;
  font-size: 0.78rem;
  color: #64748b;
  font-weight: 500;
}

.mini {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.3rem 0.65rem;
  font-size: 0.75rem;
  border-radius: 6px;
}

.skills-state {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #64748b;
  font-size: 0.82rem;
  padding: 8px 0;
}

.skills-state.center {
  flex-direction: column;
  justify-content: center;
  padding: 32px 0;
  text-align: center;
}

.skills-state.empty {
  color: #94a3b8;
}

.spin {
  animation: spin 1s linear infinite;
}

.text-primary {
  color: #0ea5e9;
}

.text-slate-400 {
  color: #94a3b8;
}

.text-slate-600 {
  color: #475569;
}

.w-3\.5 {
  width: 0.875rem;
}

.h-3\.5 {
  height: 0.875rem;
}

.w-4 {
  width: 1rem;
}

.h-4 {
  height: 1rem;
}

.w-5 {
  width: 1.25rem;
}

.h-5 {
  height: 1.25rem;
}

.w-6 {
  width: 1.5rem;
}

.h-6 {
  height: 1.5rem;
}

.flex-shrink-0 {
  flex-shrink: 0;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
