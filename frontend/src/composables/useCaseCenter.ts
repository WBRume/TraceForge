/**
 * 案例知识中心视图模型：列表检索过滤、案例详情、CRUD 与评审状态机动作。
 */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'

export type CaseFilterValue = 'ALL' | string

const PAGE_SIZE = 20

interface UseCaseCenterOptions {
  workspaceId?: () => string
}

export function useCaseCenter(options: UseCaseCenterOptions = {}) {
  const route = useRoute()
  const router = useRouter()
  const { t } = useI18n()

  const routeWorkspaceId = computed(() => String(route.params.wsId || ''))
  const workspaceId = computed(() => {
    if (options.workspaceId) return String(options.workspaceId())
    return routeWorkspaceId.value
  })

  // ─── 列表 ───
  const items = ref<any[]>([])
  const total = ref(0)
  const page = ref(1)
  const loading = ref(false)
  const keyword = ref('')
  const status = ref<CaseFilterValue>('ALL')
  const priority = ref<CaseFilterValue>('ALL')
  const hasMore = computed(() => items.value.length < total.value)

  const buildParams = (pageNo: number, pageSize: number) => {
    const params: Record<string, string | number> = { page: pageNo, page_size: pageSize }
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    if (status.value !== 'ALL') params.status = status.value
    if (priority.value !== 'ALL') params.priority = priority.value
    return params
  }

  const loadCases = async (options?: { reset?: boolean }) => {
    const reset = options?.reset ?? true
    if (loading.value) return
    if (!reset && !hasMore.value) return
    loading.value = true
    const pageNo = reset ? 1 : page.value + 1
    try {
      const wsId = workspaceId.value
      const endpoint = wsId ? `/workspaces/${wsId}/cases` : '/cases'
      const res = await api.get(endpoint, { params: buildParams(pageNo, PAGE_SIZE) })
      const nextItems = Array.isArray(res.data?.items) ? res.data.items : []
      total.value = Number(res.data?.total || 0)
      items.value = reset ? nextItems : [...items.value, ...nextItems]
      page.value = pageNo
    } catch (e) {
      console.error('Failed to load cases', e)
      ElMessage.error(formatApiError(e, t('case_center.load_failed'), t))
    } finally {
      loading.value = false
    }
  }

  const loadMore = () => void loadCases({ reset: false })

  const applyFilters = () => void loadCases({ reset: true })

  const resetFilters = () => {
    keyword.value = ''
    status.value = 'ALL'
    priority.value = 'ALL'
  }

  // ─── 详情抽屉 ───
  const drawerOpen = ref(false)
  const detailLoading = ref(false)
  const currentCase = ref<any>(null)
  const actionLoading = ref(false)

  const myCanManage = computed(() => Boolean(currentCase.value?.my_can_manage))
  const myCanReview = computed(() => Boolean(currentCase.value?.my_can_review))

  const openCase = async (caseId: string) => {
    drawerOpen.value = true
    detailLoading.value = true
    currentCase.value = null
    try {
      const wsId = workspaceId.value
      const res = await api.get(`/workspaces/${wsId}/cases/${caseId}`)
      currentCase.value = res.data
      if (route.query.case !== caseId) {
        router.replace({ query: { ...route.query, case: caseId } })
      }
    } catch (e) {
      ElMessage.error(formatApiError(e, t('case_center.detail_load_failed'), t))
      drawerOpen.value = false
    } finally {
      detailLoading.value = false
    }
  }

  /**
   * 独立报告页加载案例详情（不依赖抽屉状态，也不回写 ?case= 查询参数）。
   */
  const loadCaseById = async (caseId: string) => {
    detailLoading.value = true
    currentCase.value = null
    try {
      const wsId = workspaceId.value
      const res = await api.get(`/workspaces/${wsId}/cases/${caseId}`)
      currentCase.value = res.data
    } catch (e) {
      ElMessage.error(formatApiError(e, t('case_center.detail_load_failed'), t))
    } finally {
      detailLoading.value = false
    }
  }

  const closeDrawer = () => {
    drawerOpen.value = false
    currentCase.value = null
    if (route.query.case) {
      const query = { ...route.query }
      delete query.case
      router.replace({ query })
    }
  }

  const refreshCurrentCase = async () => {
    if (!currentCase.value?.id) return
    const wsId = workspaceId.value || currentCase.value?.workspace_id || ''
    if (!wsId) return
    try {
      const res = await api.get(`/workspaces/${wsId}/cases/${currentCase.value.id}`)
      currentCase.value = res.data
      // 同步列表行数据
      const index = items.value.findIndex((item) => item.id === currentCase.value.id)
      if (index >= 0) items.value[index] = { ...items.value[index], ...res.data }
    } catch (e) {
      console.warn('Failed to refresh case', e)
    }
  }

  // ─── 新建 / 编辑 ───
  const formVisible = ref(false)
  const formSaving = ref(false)
  const editingId = ref('')
  const formModel = ref({
    title: '',
    problem_description: '',
    product_name: '',
    product_version: '',
    site_name: '',
    code_context: '',
    analysis_process: '',
    root_cause: '',
    solution: '',
    category: 'PUBLIC',
    priority: 'P2',
  })

  const openCreateForm = () => {
    editingId.value = ''
    formModel.value = {
      title: '',
      problem_description: '',
      product_name: '',
      product_version: '',
      site_name: '',
      code_context: '',
      analysis_process: '',
      root_cause: '',
      solution: '',
      category: 'PUBLIC',
      priority: 'P2',
    }
    formVisible.value = true
  }

  const openEditForm = () => {
    const c = currentCase.value
    if (!c) return
    editingId.value = c.id
    formModel.value = {
      title: c.title || '',
      problem_description: c.problem_description || '',
      product_name: c.product_name || '',
      product_version: c.product_version || '',
      site_name: c.site_name || '',
      code_context: c.code_context || '',
      analysis_process: c.analysis_process || '',
      root_cause: c.root_cause || '',
      solution: c.solution || '',
      category: c.category || 'PUBLIC',
      priority: c.priority || 'P2',
    }
    formVisible.value = true
  }

  const closeForm = () => {
    if (formSaving.value) return
    formVisible.value = false
  }

  const saveForm = async () => {
    if (!formModel.value.title.trim()) {
      ElMessage.warning(t('case_center.title_required'))
      return
    }
    const wsId = workspaceId.value || currentCase.value?.workspace_id || ''
    if (!wsId) {
      ElMessage.warning(t('case_center.workspace_required'))
      return
    }
    formSaving.value = true
    try {
      const payload = { ...formModel.value }
      if (editingId.value) {
        const res = await api.put(`/workspaces/${wsId}/cases/${editingId.value}`, payload)
        currentCase.value = res.data
      } else {
        const res = await api.post(`/workspaces/${wsId}/cases`, payload)
        currentCase.value = res.data
      }
      ElMessage.success(t('case_center.save_success'))
      formVisible.value = false
      drawerOpen.value = true
      await loadCases({ reset: true })
    } catch (e) {
      ElMessage.error(formatApiError(e, t('case_center.save_failed'), t))
    } finally {
      formSaving.value = false
    }
  }

  // ─── 状态机动作 ───
  const runAction = async (action: () => Promise<any>, successKey: string) => {
    actionLoading.value = true
    try {
      await action()
      ElMessage.success(t(successKey))
      await refreshCurrentCase()
      await loadCases({ reset: true })
    } catch (e: any) {
      ElMessage.error(formatApiError(e, t('case_center.action_failed'), t))
    } finally {
      actionLoading.value = false
    }
  }

  const requireWorkspace = () => {
    const wsId = workspaceId.value || currentCase.value?.workspace_id || ''
    if (!wsId) ElMessage.warning(t('case_center.workspace_required'))
    return wsId
  }

  const submitCase = () => {
    const wsId = requireWorkspace()
    if (!wsId) return
    return runAction(async () => {
      await api.post(`/workspaces/${wsId}/cases/${currentCase.value.id}/submit`)
    }, 'case_center.submit_success')
  }

  const startReview = () => {
    const wsId = requireWorkspace()
    if (!wsId) return
    return runAction(async () => {
      await api.post(`/workspaces/${wsId}/cases/${currentCase.value.id}/start-review`)
    }, 'case_center.start_review_success')
  }

  const resubmitCase = () => {
    const wsId = requireWorkspace()
    if (!wsId) return
    return runAction(async () => {
      await api.post(`/workspaces/${wsId}/cases/${currentCase.value.id}/resubmit`)
    }, 'case_center.resubmit_success')
  }

  // 评审裁决对话框
  const reviewDialogVisible = ref(false)
  const reviewConclusion = ref<'approve' | 'reject'>('approve')
  const reviewComment = ref('')

  const openReviewDialog = (conclusion: 'approve' | 'reject') => {
    reviewConclusion.value = conclusion
    reviewComment.value = ''
    reviewDialogVisible.value = true
  }

  const confirmReview = () => {
    const wsId = requireWorkspace()
    if (!wsId) return
    return runAction(async () => {
      await api.post(`/workspaces/${wsId}/cases/${currentCase.value.id}/review`, {
        conclusion: reviewConclusion.value,
        comment: reviewComment.value,
      })
    }, reviewConclusion.value === 'approve' ? 'case_center.approve_success' : 'case_center.reject_success')
  }

  const deleteCase = () => {
    const wsId = requireWorkspace()
    if (!wsId) return
    return runAction(async () => {
      await api.delete(`/workspaces/${wsId}/cases/${currentCase.value.id}`)
      drawerOpen.value = false
      currentCase.value = null
    }, 'case_center.delete_success')
  }

  return {
    items,
    total,
    loading,
    hasMore,
    keyword,
    status,
    priority,
    loadCases,
    loadMore,
    applyFilters,
    resetFilters,
    drawerOpen,
    detailLoading,
    currentCase,
    actionLoading,
    myCanManage,
    myCanReview,
    openCase,
    loadCaseById,
    closeDrawer,
    refreshCurrentCase,
    formVisible,
    formSaving,
    formModel,
    editingId,
    openCreateForm,
    openEditForm,
    closeForm,
    saveForm,
    submitCase,
    startReview,
    resubmitCase,
    reviewDialogVisible,
    reviewConclusion,
    reviewComment,
    openReviewDialog,
    confirmReview,
    deleteCase,
  }
}
