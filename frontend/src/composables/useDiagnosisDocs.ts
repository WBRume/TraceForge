/**
 * 问题定位任务：诊断文档与代码路径抽屉数据
 *
 * 文档资产：任务上传的需求/日志等辅助文档（asset_type=DIAGNOSIS_DOC）
 * 代码路径：任务 project_path + 工作区关联仓库
 */
import { readonly, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { useI18n } from 'vue-i18n'

export interface DiagnosisDocItem {
  id: string
  name: string
  asset_type: string
  source_ext?: string | null
  source_file_name?: string | null
  created_at?: string | null
  content_text?: string | null
}

export interface WorkspaceRepoInfo {
  id?: string
  repo_name: string
  branch_name?: string
  repo_url?: string
  state?: string
}

export function useDiagnosisDocs(options: { wsId: () => string; taskId: () => string }) {
  const { t } = useI18n()

  const docs = ref<DiagnosisDocItem[]>([])
  const docsLoading = ref(false)
  const docsLoaded = ref(false)
  const activeDoc = ref<DiagnosisDocItem | null>(null)
  const activeDocLoading = ref(false)
  const uploading = ref(false)

  const codePath = ref('')
  const repos = ref<WorkspaceRepoInfo[]>([])
  const reposLoading = ref(false)

  const loadDocs = async (force = false) => {
    const wsId = options.wsId()
    const taskId = options.taskId()
    if (!wsId || !taskId) return
    if (docsLoaded.value && !force) return
    docsLoading.value = true
    try {
      const res = await api.get(`/workspaces/${wsId}/assets`, {
        params: { task_id: taskId, asset_type: 'DIAGNOSIS_DOC', page: 1, page_size: 50 },
      })
      docs.value = (res.data?.items || []).map((item: Record<string, any>) => ({
        id: String(item.id || ''),
        name: String(item.name || item.source_file_name || ''),
        asset_type: String(item.asset_type || ''),
        source_ext: item.source_ext || null,
        source_file_name: item.source_file_name || null,
        created_at: item.created_at || null,
      }))
      docsLoaded.value = true
    } catch (e) {
      console.error('Failed to load diagnosis docs', e)
    } finally {
      docsLoading.value = false
    }
  }

  const selectDoc = async (doc: DiagnosisDocItem) => {
    const wsId = options.wsId()
    if (!wsId || !doc.id) return
    activeDocLoading.value = true
    try {
      const res = await api.get(`/workspaces/${wsId}/assets/${doc.id}`)
      activeDoc.value = {
        ...doc,
        content_text: res.data?.content_text || '',
      }
    } catch (e) {
      console.error('Failed to load diagnosis doc content', e)
      activeDoc.value = null
    } finally {
      activeDocLoading.value = false
    }
  }

  const uploadDoc = async (file: File) => {
    const wsId = options.wsId()
    const taskId = options.taskId()
    if (!wsId || !taskId) return
    uploading.value = true
    const formData = new FormData()
    formData.append('file', file)
    try {
      await api.post(`/workspaces/${wsId}/tasks/${taskId}/upload-diagnosis-doc`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      ElMessage.success(t('diagnosis.docs_upload_success'))
      await loadDocs(true)
    } catch (e) {
      ElMessage.error(formatApiError(e, t('diagnosis.docs_upload_failed'), t))
    } finally {
      uploading.value = false
    }
  }

  const loadCodePath = async () => {
    const wsId = options.wsId()
    const taskId = options.taskId()
    if (!wsId || !taskId) return
    reposLoading.value = true
    try {
      const taskRes = await api.get(`/workspaces/${wsId}/tasks/${taskId}`)
      codePath.value = String(taskRes.data?.project_path || '')
      const wsRes = await api.get(`/workspaces/${wsId}`)
      repos.value = (wsRes.data?.repositories || []).map((item: Record<string, any>) => ({
        id: item.id ? String(item.id) : undefined,
        repo_name: String(item.repo_name || item.name || ''),
        branch_name: item.branch_name ? String(item.branch_name) : undefined,
        repo_url: item.repo_url ? String(item.repo_url) : undefined,
        state: item.state ? String(item.state) : undefined,
      }))
    } catch (e) {
      console.error('Failed to load diagnosis code path', e)
    } finally {
      reposLoading.value = false
    }
  }

  const refresh = () => {
    docsLoaded.value = false
    void loadDocs(true)
  }

  watch(
    () => options.taskId(),
    () => {
      docsLoaded.value = false
      docs.value = []
      activeDoc.value = null
      codePath.value = ''
      repos.value = []
    },
  )

  return {
    docs: readonly(docs),
    docsLoading,
    activeDoc,
    activeDocLoading,
    uploading,
    codePath,
    repos,
    reposLoading,
    loadDocs,
    selectDoc,
    uploadDoc,
    loadCodePath,
    refresh,
  }
}
