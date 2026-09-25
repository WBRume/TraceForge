<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import BaseSelect from '@/components/BaseSelect.vue'
import api from '@/utils/api'
import { useLocalResources, type TaskExecution } from '@/composables/useLocalResources'
const props = defineProps<{ workspaceId: string }>()
const emit = defineEmits<{ change: [value: TaskExecution] }>()
const { items, enabled, error, load } = useLocalResources(() => props.workspaceId)
const selected = ref('')
const backend = ref('')
const available = computed(() => (items.value ?? []).filter(r => r.backend === backend.value))
const resourceOptions = computed(() => [
  { label: '服务器资源', value: '' },
  ...available.value.map(resource => ({
    label: `本地 · ${resource.name}`,
    value: resource.id,
    disabled: !enabled.value,
  })),
])
watch(() => props.workspaceId, async () => {
  selected.value = ''
  emit('change', { location: 'SERVER' })
  await load()
  try { backend.value = (await api.get(`/workspaces/${props.workspaceId}/agent-backends`)).data.effective_agent_backend }
  catch { backend.value = '' }
}, { immediate: true })
function choose(value: unknown) {
  selected.value = String(value ?? '')
  const item = available.value.find(r => r.id === selected.value)
  emit('change', item ? { location: 'LOCAL', resource_id: item.id, profile_revision: item.profile_revision } : { location: 'SERVER' })
}
</script>
<template>
  <label class="resource-picker">
    <span class="resource-picker-label">执行资源</span>
    <BaseSelect :model-value="selected" :options="resourceOptions" class="input-field" @update:model-value="choose" />
    <small v-if="error" class="resource-picker-error" role="status">{{ error }}</small>
  </label>
</template>
<style scoped>
.resource-picker {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.resource-picker-label {
  color: #334155;
  font-size: 0.8rem;
  font-weight: 600;
}

.resource-picker-error {
  color: #b91c1c;
  font-size: 0.78rem;
}

:global(.dark) .resource-picker-label {
  color: #cbd5e1;
}

</style>
