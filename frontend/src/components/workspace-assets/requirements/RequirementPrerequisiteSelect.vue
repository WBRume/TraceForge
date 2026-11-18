<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import { useRequirementSearch } from '@/composables/useRequirementSearch'

const props = defineProps<{ workspaceId: string; requirementId: string; initialTitle?: string | null }>()
const value = defineModel<string | null>({ required: true })
const { t } = useI18n()
const enabled = shallowRef(false)
const remembered = shallowRef(props.initialTitle)
const { query, items, error, search } = useRequirementSearch(() => props.workspaceId, () => enabled.value)
const options = computed(() => {
  const choices = items.value.filter(item => item.id !== props.requirementId).map(item => ({ value: item.id, label: item.title }))
  if (value.value && !choices.some(item => item.value === value.value)) {
    choices.unshift({ value: value.value, label: remembered.value || value.value })
  }
  return [{ value: null, label: t('workspace_assets.delivery.no_predecessor') }, ...choices]
})
function open() {
  enabled.value = true
  if (query.value) query.value = ''
  else void search()
}
function choose(next: string | null) {
  remembered.value = options.value.find(item => item.value === next)?.label
  value.value = next
}
</script>

<template>
  <BaseSelect :model-value="value" :options="options" searchable remote-search
    :aria-label="t('workspace_assets.delivery.predecessor')"
    :search-placeholder="t('workspace_assets.delivery.search_requirements')"
    @open="open" @search="query = $event" @update:model-value="choose" />
  <small v-if="error" role="alert">{{ t('workspace_assets.requirements.repository.empty_body') }}</small>
</template>
