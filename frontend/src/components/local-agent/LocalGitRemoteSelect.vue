<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import BaseSelect from '@/components/BaseSelect.vue'
import { chooseGitRemote, getLocalGitRemotes, type GitFetchRemote } from '@/composables/local-agent/localGitRemotes'

const props = defineProps<{
  id?: string
  testId?: string
  modelValue: string
  repoPath: string
  preferredUrl?: string
  required?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
}>()

const remotes = shallowRef<GitFetchRemote[]>([])
const loading = shallowRef(false)
const hasRemotes = computed(() => remotes.value.length > 0)
const remoteOptions = computed(() => remotes.value.map(remote => ({
  label: `${remote.name} · ${remote.fetchUrl}`,
  value: remote.fetchUrl,
})))
let generation = 0

watch(() => props.repoPath, async repoPath => {
  const current = ++generation
  if (!repoPath) {
    remotes.value = []
    loading.value = false
    return
  }

  loading.value = true
  try {
    const available = await getLocalGitRemotes(repoPath)
    if (current !== generation) return
    remotes.value = available
    const selected = chooseGitRemote(available, {
      currentUrl: props.modelValue,
      preferredUrl: props.preferredUrl,
    })
    if (selected && selected.fetchUrl !== props.modelValue) {
      emit('update:modelValue', selected.fetchUrl)
    }
  } finally {
    if (current === generation) loading.value = false
  }
}, { immediate: true })
</script>

<template>
  <BaseSelect
    v-if="hasRemotes"
    :model-value="modelValue"
    :options="remoteOptions"
    :disabled="disabled || loading"
    :id="id"
    :data-testid="testId"
    @update:model-value="emit('update:modelValue', String($event))"
  />
  <input
    v-else
    class="git-remote-control"
    :id="id"
    :data-testid="testId"
    :value="modelValue"
    type="text"
    :required="required"
    :disabled="disabled"
    placeholder="git@github.com:my-account/repo.git"
    @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
  />
</template>

<style scoped>
.git-remote-control {
  width: 100%;
  min-width: 0;
  padding: 0.65rem 0.75rem;
  border: 1px solid #cbd5e1;
  border-radius: 0.5rem;
  background: #fff;
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.82rem;
}

.git-remote-control:focus {
  outline: none;
  border-color: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
}
</style>
