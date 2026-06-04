<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'

type VersionItem = {
  id: string
  version_no: number
  change_note?: string | null
  created_at: string
}

const props = defineProps<{
  versions: VersionItem[]
  modelValue: string
  loading?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const { t } = useI18n()

const versionOptions = computed(() => (
  props.versions.map(item => ({
    value: item.id,
    label: t('doc_review.version_option', {
      version: item.version_no,
      time: new Date(item.created_at).toLocaleString(),
    }),
  }))
))

const onSelect = (value: string) => {
  emit('update:modelValue', value)
}
</script>

<template>
  <div class="version-switcher glass-panel">
    <label class="switcher-label">{{ t('doc_review.version_label') }}</label>
    <BaseSelect
      class="switcher-select"
      :model-value="modelValue"
      :options="versionOptions"
      :placeholder="t('doc_review.version_select_placeholder')"
      :disabled="loading"
      @update:model-value="onSelect"
    />
  </div>
</template>

<style scoped>
.version-switcher {
  display: inline-flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 10px;
  padding: 8px 12px;
  border-radius: 12px;
  min-width: 0;
  max-width: 100%;
}

.switcher-label {
  font-size: 12px;
  color: var(--color-text-muted);
  letter-spacing: 0.02em;
  white-space: nowrap;
  flex: 0 0 auto;
}

.switcher-select {
  min-width: 180px;
  width: clamp(180px, 32vw, 420px);
  max-width: 100%;
  flex: 1 1 auto;
}
</style>
