import { computed, ref } from 'vue'
import type { Ref } from 'vue'
import type { OpenSpecDrawerLevel, SpecDrawerLevel, SpecDrawerTab } from '../types'

/**
 * Spec 文档抽屉（三段式容器）：层级/标签页状态、入口按钮可见性与点击策略。
 * 问题定位任务（DIAGNOSIS）复用同一容器承载诊断文档/代码路径抽屉。
 */
export function useSpecDrawer(options: {
  currentTask: Ref<any>
  isTaskPreStart: Ref<boolean>
  isDiagnosisTask: Ref<boolean>
  openSpecWorkspace: () => void
}) {
  const specDrawerLevel = ref<SpecDrawerLevel>(0)
  const lastOpenSpecDrawerLevel = ref<OpenSpecDrawerLevel>(1)
  const specDrawerTab = ref<SpecDrawerTab>('spec_doc')
  const preferredSpecAssetId = ref('')
  const preferredSpecTaskId = ref('')

  const hasTaskSpecDoc = (task: any): boolean => {
    return Boolean(String(task?.spec_doc_path || '').trim())
  }

  /** 任务是否具备规格文档（显式 spec_doc_path，或刚创建时本会话内登记的偏好资产）。 */
  const hasTaskSpecification = (task: any): boolean => {
    if (!task) return false
    if (hasTaskSpecDoc(task)) return true
    return String(task?.id || '') === preferredSpecTaskId.value && Boolean(preferredSpecAssetId.value)
  }

  const currentTaskHasSpec = computed(() => hasTaskSpecification(options.currentTask.value))
  const isSuperpowersDocsAvailable = computed(() => Boolean(options.currentTask.value) && !options.isTaskPreStart.value)
  const showSpecEntryButton = computed(() => (currentTaskHasSpec.value || isSuperpowersDocsAvailable.value) && !options.isDiagnosisTask.value)
  const isSpecDrawerAvailable = computed(() => (
    (currentTaskHasSpec.value || isSuperpowersDocsAvailable.value) && !options.isTaskPreStart.value && !options.isDiagnosisTask.value
  ))
  const isSpecPanelOpen = computed(() => specDrawerLevel.value > 0)
  const activeInitialSpecAssetId = computed(() => (
    options.currentTask.value?.id && options.currentTask.value.id === preferredSpecTaskId.value
      ? preferredSpecAssetId.value
      : ''
  ))

  const setTab = (tab: SpecDrawerTab) => {
    specDrawerTab.value = tab
  }

  const closeSpecDrawer = () => {
    specDrawerLevel.value = 0
  }

  const applySpecDrawerLevel = (level: OpenSpecDrawerLevel) => {
    specDrawerLevel.value = level
    lastOpenSpecDrawerLevel.value = level
  }

  const requestSpecDrawerLevel = (level: OpenSpecDrawerLevel) => {
    if (!options.currentTask.value) return
    applySpecDrawerLevel(level)
  }

  const handleExpandDrawer = () => {
    if (specDrawerLevel.value === 0) {
      specDrawerLevel.value = 1
      return
    }
    if (specDrawerLevel.value < 3) {
      specDrawerLevel.value++
    }
  }

  const handleCollapseDrawer = () => {
    if (specDrawerLevel.value > 1) {
      specDrawerLevel.value--
    } else {
      specDrawerLevel.value = 0
    }
  }

  const handleSpecEntryClick = () => {
    if (!options.currentTask.value || !showSpecEntryButton.value) return
    if (options.isTaskPreStart.value) {
      options.openSpecWorkspace()
      return
    }
    if (!currentTaskHasSpec.value) {
      specDrawerTab.value = 'superpowers_docs'
    }
    if (isSpecPanelOpen.value) {
      closeSpecDrawer()
      return
    }
    requestSpecDrawerLevel(lastOpenSpecDrawerLevel.value)
  }

  /** 问题定位任务：诊断文档/代码路径抽屉（复用 spec 抽屉三段式容器） */
  const toggleDiagnosisDocsDrawer = () => {
    if (!options.isDiagnosisTask.value || !options.currentTask.value) return
    if (isSpecPanelOpen.value) {
      specDrawerLevel.value = 0
      return
    }
    specDrawerTab.value = 'diag_docs'
    specDrawerLevel.value = 1
    lastOpenSpecDrawerLevel.value = 1
  }

  /** 会话切换：复位层级，按任务形态决定默认标签页，偏好资产不匹配则清除。 */
  const resetForTask = (task: any) => {
    if (task.id !== preferredSpecTaskId.value) {
      preferredSpecAssetId.value = ''
    }
    specDrawerLevel.value = 0
    specDrawerTab.value = task.task_type === 'DIAGNOSIS'
      ? 'diag_docs'
      : (hasTaskSpecification(task) ? 'spec_doc' : 'superpowers_docs')
  }

  return {
    specDrawerLevel,
    lastOpenSpecDrawerLevel,
    specDrawerTab,
    preferredSpecAssetId,
    preferredSpecTaskId,
    hasTaskSpecDoc,
    hasTaskSpecification,
    currentTaskHasSpec,
    isSuperpowersDocsAvailable,
    showSpecEntryButton,
    isSpecDrawerAvailable,
    isSpecPanelOpen,
    activeInitialSpecAssetId,
    setTab,
    closeSpecDrawer,
    applySpecDrawerLevel,
    requestSpecDrawerLevel,
    handleExpandDrawer,
    handleCollapseDrawer,
    handleSpecEntryClick,
    toggleDiagnosisDocsDrawer,
    resetForTask,
  }
}
