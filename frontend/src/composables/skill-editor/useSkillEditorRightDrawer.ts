import { computed, ref, type ComputedRef, type Ref } from 'vue'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import type { SkillFileNode } from './skillEditorTypes'

type TranslateFn = (key: string, params?: Record<string, unknown>) => string

type UseSkillEditorRightDrawerOptions = {
  t: TranslateFn
  actionError: Ref<string>
  selectedWorkspaceId: Ref<string>
  skillId: ComputedRef<string | undefined>
  viewVersionId: Ref<string>
}

export function useSkillEditorRightDrawer(options: UseSkillEditorRightDrawerOptions) {
  const {
    t,
    actionError,
    selectedWorkspaceId,
    skillId,
    viewVersionId,
  } = options

  const isRightDrawerOpen = ref(false)
  const rightDrawerLevel = ref(1)
  const rightDrawerTab = ref<'history' | 'diff' | null>(null)

  const drawerFileTree = ref<SkillFileNode[]>([])
  const drawerActiveFilePath = ref('')
  const drawerFileContent = ref('')
  const drawerIsBinary = ref(false)
  const drawerTreeLoading = ref(false)
  const drawerFileLoading = ref(false)

  const toggleRightDrawer = () => {
    isRightDrawerOpen.value = !isRightDrawerOpen.value
    if (!isRightDrawerOpen.value) {
      rightDrawerLevel.value = 1
      rightDrawerTab.value = null
    }
  }

  const expandRightDrawer = (tab: 'history' | 'diff') => {
    isRightDrawerOpen.value = true
    rightDrawerLevel.value = 2
    rightDrawerTab.value = tab
  }

  const toggleDrawerFullWidth = () => {
    rightDrawerLevel.value = rightDrawerLevel.value === 3 ? 2 : 3
  }

  const drawerActiveLanguage = computed(() => {
    const path = String(drawerActiveFilePath.value || '').toLowerCase()
    if (path.endsWith('.md') || path.endsWith('.markdown')) return 'markdown'
    if (path.endsWith('.py')) return 'python'
    if (path.endsWith('.sh') || path.endsWith('.bash')) return 'shell'
    if (path.endsWith('.js') || path.endsWith('.mjs') || path.endsWith('.cjs')) return 'javascript'
    if (path.endsWith('.ts') || path.endsWith('.mts') || path.endsWith('.cts')) return 'typescript'
    if (path.endsWith('.json')) return 'json'
    if (path.endsWith('.yaml') || path.endsWith('.yml')) return 'yaml'
    if (path.endsWith('.toml')) return 'ini'
    return 'plaintext'
  })

  const openDrawerFile = async (path: string) => {
    if (!path) return
    if (!skillId.value) return
    drawerFileLoading.value = true
    drawerActiveFilePath.value = path
    try {
      const res = await api.get(`/skills/${skillId.value}/files/content`, {
        params: {
          ...(selectedWorkspaceId.value ? { workspace_id: selectedWorkspaceId.value } : {}),
          path,
          ref: viewVersionId.value,
        },
      })
      drawerIsBinary.value = Boolean(res.data.is_binary)
      drawerFileContent.value = res.data.content || ''
    } catch (error) {
      actionError.value = formatApiError(error, t('skills.editor.load_failed'), t)
    } finally {
      drawerFileLoading.value = false
    }
  }

  return {
    isRightDrawerOpen,
    rightDrawerLevel,
    rightDrawerTab,
    drawerFileTree,
    drawerActiveFilePath,
    drawerFileContent,
    drawerIsBinary,
    drawerTreeLoading,
    drawerFileLoading,
    drawerActiveLanguage,
    toggleRightDrawer,
    expandRightDrawer,
    toggleDrawerFullWidth,
    openDrawerFile,
  }
}
