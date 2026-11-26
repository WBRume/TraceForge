<script setup lang="ts">
import { computed, shallowRef, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import type { DiagramFormat } from './diagramModel'

const props = defineProps<{ saving: boolean; hasArtwork: boolean }>()
const emit = defineEmits<{ close: []; submit: [format: DiagramFormat] }>()
const { t } = useI18n()
const format = shallowRef<DiagramFormat>('tfdiagram')
const formId = useId()
const types = ['tfdiagram', 'png', 'svg'] as const
const options = computed(() => types.map(value => ({
  value, label: t('diagram.file.formats.' + value), disabled: value !== 'tfdiagram' && !props.hasArtwork,
})))
const canSubmit = computed(() => !props.saving && (format.value === 'tfdiagram' || props.hasArtwork))

function submit() {
  if (canSubmit.value) emit('submit', format.value)
}
</script>

<template>
  <el-dialog :model-value="true" class="canvas-dialog" :title="t('diagram.file.exportTitle')" width="min(440px, 94vw)"
    :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving" append-to-body @close="emit('close')">
    <form :id="formId" class="export-form" @submit.prevent="submit">
      <span>{{ t('diagram.file.format') }}</span>
      <BaseSelect v-model="format" :options="options" :aria-label="t('diagram.file.format')" :disabled="saving" />
    </form>
    <template #footer>
      <el-button :disabled="saving" @click="emit('close')">{{ t('diagram.tool.cancel') }}</el-button>
      <el-button type="primary" native-type="submit" :form="formId" :loading="saving" :disabled="!canSubmit">
        {{ t('diagram.file.export') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.export-form { display: grid; gap: 8px; color: var(--color-text-body); font-weight: 550; }
</style>
