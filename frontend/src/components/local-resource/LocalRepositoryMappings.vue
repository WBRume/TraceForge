<script setup lang="ts">
import { ref, watch } from 'vue'
import api from '@/utils/api'
import { useAuthStore } from '@/stores/auth'
import { readRepoPreferences, saveRepoPreferences } from '@/composables/localRepoPreferences'
import type { RepositoryMapping } from '@/composables/useLocalResources'
const props = defineProps<{ workspaceId: string }>()
const auth = useAuthStore()
const mappings = ref<RepositoryMapping[]>([])
const error = ref('')
let generation = 0
watch(() => props.workspaceId, async workspaceId => {
  const current = ++generation
  try {
    const { data } = await api.get(`/workspaces/${workspaceId}`)
    if (current !== generation) return
    const saved = readRepoPreferences(workspaceId, String(auth.user?.id || ''))
    mappings.value = (data.repositories || []).map((repo: { id: string; repository_id?: string; repo_url: string }) => {
      const repository_id = repo.repository_id || repo.id
      return saved.find(item => item.repository_id === repository_id) || { repository_id, configured_git_url: repo.repo_url, local_path: '' }
    })
  } catch { error.value = '读取仓库列表失败' }
}, { immediate: true })
function persist() { saveRepoPreferences(props.workspaceId, String(auth.user?.id || ''), mappings.value) }
</script>
<template>
  <section class="mapping-draft">
    <p>填写个人 fork 的 Git 地址和资源机器上的仓库目录。地址与目录会保存在当前账号的本机配置中；配置同机资源服务后统一检测。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <fieldset v-for="mapping in mappings" :key="mapping.repository_id">
      <label>个人仓库 Git 地址<input v-model="mapping.configured_git_url" @change="persist" /></label>
      <label>本机仓库目录<input v-model="mapping.local_path" placeholder="G:/repositories/my-repo" @change="persist" /></label>
    </fieldset>
    <p v-if="!mappings.length && !error">当前工作区没有绑定仓库。</p>
  </section>
</template>
<style scoped>.mapping-draft { display: grid; gap: 1rem; } fieldset, label { display: grid; gap: .5rem; } fieldset { border: 1px solid #cbd5e1; border-radius: .5rem; padding: .8rem; } input { padding: .6rem; border: 1px solid #cbd5e1; border-radius: .4rem; min-width: 0; } p { color: var(--text-secondary, #64748b); line-height: 1.6; }</style>
