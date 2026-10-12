<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
import { openCollaborationView, useCollaborationPresentation } from '@/composables/collaboration/useCollaborationPresentation'
const props = defineProps<{ controller: LocalCollaboration }>()
const emit = defineEmits<{ open: [] }>()
const { t } = useI18n()
const ui = useCollaborationPresentation(() => props.controller)
function open() { openCollaborationView(props.controller, ui.value?.action === 'device'); emit('open') }
</script>

<template>
  <div v-if="ui?.inputText" class="collaboration-input-status" role="status" aria-live="polite">
    <span>{{ ui.inputText }}</span>
    <button v-if="controller.phase.value === 'PREPARING' && controller.driver.value" type="button" @click="controller.cancelPreparation">{{ t('collaboration.cancelPreparation') }}</button>
    <button v-else-if="!['loading', 'connecting', 'running', 'waiting', 'preparing', 'transferring'].includes(ui.key)" type="button" @click="open">{{ t(ui.key === 'conflict' ? 'collaboration.ui.handleFiles' : ui.action !== 'none' ? `collaboration.ui.actions.${ui.action}` : 'collaboration.ui.view') }}</button>
  </div>
</template>

<style scoped>
.collaboration-input-status { display: flex; align-items: center; gap: 10px; padding: 4px 20px 8px; font-size: 12px; color: var(--color-text-muted); }.collaboration-input-status span { flex: 1; min-width: 0; }.collaboration-input-status button { flex-shrink: 0; border: 0; background: none; padding: 0; color: var(--color-primary-600); font: inherit; cursor: pointer; }
</style>
