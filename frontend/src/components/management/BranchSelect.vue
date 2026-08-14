<!--
BranchSelect: fetch branch refs of a repository and expose them as a
BaseSelect; shared across product / project / repository groups.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import BaseSelect from '@/components/BaseSelect.vue'
import { listRepositoryRefs } from '@/services/managementApi'
import type { RepoRef } from '@/types/management'

const props = withDefaults(defineProps<{
  modelValue: string
  repositoryId: string | null
  placeholder?: string
}>(), {
  placeholder: '',
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const branches = ref<RepoRef[]>([])
const loading = ref(false)

const options = computed(() => branches.value
  .filter((ref) => ref.ref_type === 'BRANCH')
  .map((ref) => ({ label: ref.ref_name, value: ref.ref_name })))

const load = async () => {
  if (!props.repositoryId) {
    branches.value = []
    return
  }
  loading.value = true
  try {
    const res = await listRepositoryRefs(props.repositoryId, 'branch')
    branches.value = res.items
  } catch {
    branches.value = []
  } finally {
    loading.value = false
  }
}

watch(() => props.repositoryId, () => {
  if (props.repositoryId) {
    load()
  } else {
    branches.value = []
  }
}, { immediate: true })
</script>

<template>
  <div class="mgmt-branch-select">
    <div class="mgmt-branch-select-main">
      <BaseSelect
        :model-value="props.modelValue"
        :options="options"
        :disabled="!props.repositoryId"
        :placeholder="props.repositoryId
          ? (props.placeholder || '')
          : $t('management.product.binding_repo')"
        @update:modelValue="emit('update:modelValue', $event)"
      />
      <button
        class="btn-ghost mgmt-branch-refresh"
        :disabled="!props.repositoryId || loading"
        :title="$t('common.refresh')"
        @click="load"
      >
        <RefreshCw class="w-4 h-4" :class="{ spin: loading }" />
      </button>
    </div>
  </div>
</template>

<style scoped src="@/styles/management/management-shared.css"></style>

<style scoped>
.mgmt-branch-select {
  display: flex;
  align-items: center;
}

.mgmt-branch-select-main {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
}

.mgmt-branch-select-main > :first-child {
  flex: 1;
}

.mgmt-branch-refresh {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
}

.w-4 {
  width: 1rem;
  height: 1rem;
}

.spin {
  animation: spin 1s linear infinite;
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
