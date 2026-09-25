<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import BaseSelect from '@/components/BaseSelect.vue'
import api from '@/utils/api'
import { formatApiError } from '@/utils/error'
import { useLocalResources } from '@/composables/useLocalResources'
const props = defineProps<{ workspaceId: string; proposalId: string }>()
const { items, enabled, load } = useLocalResources(() => props.workspaceId)
const resourceOptions = computed(() => [
  { label: '选择个人资源', value: '' },
  ...items.value.map(item => ({ label: item.name, value: item.id })),
])
const resourceId = ref('')
const busy = ref(false)
const error = ref('')
const results = ref<{ path: string; status: string; message: string }[]>([])
watch(() => props.workspaceId, () => { resourceId.value = ''; void load() }, { immediate: true })
watch(() => props.proposalId, () => { results.value = []; error.value = '' })
async function apply() {
  if (!resourceId.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const { data } = await api.post(`/workspaces/${props.workspaceId}/local-resources/${resourceId.value}/apply-proposal`, { proposal_id: props.proposalId })
    results.value = data.repositories
  } catch (e) { error.value = formatApiError(e, '应用到个人资源失败') }
  finally { busy.value = false }
}
</script>
<template>
  <section v-if="enabled && items.length" class="own-resource-apply">
    <label>应用到我的资源<BaseSelect v-model="resourceId" :options="resourceOptions" size="sm" class="resource-select" /></label>
    <button type="button" class="btn-secondary" :disabled="busy || !resourceId" @click="apply">{{ busy ? '正在应用…' : '在独立 worktree 应用' }}</button>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-for="result in results" :key="result.path">{{ result.status === 'applied' ? '已应用' : '需要处理冲突' }} · {{ result.path }}</p>
  </section>
</template>
<style scoped>.own-resource-apply { display: flex; flex-wrap: wrap; gap: .6rem; align-items: center; } label { display: flex; gap: .5rem; align-items: center; } .resource-select { width: 220px; } p { width: 100%; overflow-wrap: anywhere; } [role=alert] { color: #b91c1c; }</style>
