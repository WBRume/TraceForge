import { shallowRef } from 'vue'
import { getRepoGroupTree } from '@/services/managementApi'
import type { RepoGroupTreeNode } from '@/types/management'

/**
 * 仓库管理分组树（仓库侧栏首次展开时懒加载）。
 * 拉取失败不阻塞选择：本次全部仓库归入“未分组”，下次展开重试。
 */
export function useRepoGroups() {
  const groups = shallowRef<RepoGroupTreeNode[]>([])
  const loading = shallowRef(false)
  const loaded = shallowRef(false)

  const load = async () => {
    if (loaded.value || loading.value) return
    loading.value = true
    try {
      const res = await getRepoGroupTree()
      groups.value = res.items || []
      loaded.value = true
    } catch {
      groups.value = []
    } finally {
      loading.value = false
    }
  }

  return { groups, loading, load }
}
