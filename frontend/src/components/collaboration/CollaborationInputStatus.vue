<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Loader2 } from '@/components/icons'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
import { openCollaborationView, useCollaborationPresentation } from '@/composables/collaboration/useCollaborationPresentation'
const props = defineProps<{ controller: LocalCollaboration }>()
const emit = defineEmits<{ open: [] }>()
const { t } = useI18n()
const ui = useCollaborationPresentation(() => props.controller)
const pending = computed(() => ['loading', 'connecting', 'preparing', 'transferring', 'leaving'].includes(ui.value?.inputKey || ''))
const needsAttention = computed(() => ['offline', 'device', 'unprepared', 'error', 'conflict', 'unavailable'].includes(ui.value?.inputKey || ''))
const visible = ref(false)
const controllerPreparing = computed(() => props.controller.phase.value === 'PREPARING' && props.controller.driver.value)
const statusText = computed(() => pending.value
  ? t(`collaboration.ui.${controllerPreparing.value ? 'slowPreparation' : 'slowSync'}`)
  : ui.value?.inputText)

// Normal sends stay silent. Count the entire preparation, including consecutive sync stages.
watch([() => props.controller, pending, needsAttention], ([, transient, attention], _, onCleanup) => {
  visible.value = attention
  if (!transient) return
  const timer = setTimeout(() => { visible.value = true }, 8000)
  onCleanup(() => clearTimeout(timer))
}, { immediate: true })

function open() { openCollaborationView(props.controller, ui.value?.action === 'device'); emit('open') }
</script>

<template>
  <Transition name="collaboration-status">
    <div v-if="visible && ui?.inputText" class="collaboration-input-status" :class="{ 'is-warning': pending || ui.tone === 'warning' }">
      <Loader2 v-if="pending" class="status-spinner" aria-hidden="true" />
      <span role="status" aria-live="polite" aria-atomic="true" :title="statusText">{{ statusText }}</span>
      <button v-if="pending && controllerPreparing" type="button" :title="t('collaboration.cancelPreparation')" :aria-label="t('collaboration.cancelPreparation')" @click="controller.cancelPreparation">{{ t('common.cancel') }}</button>
      <button v-else type="button" @click="open">{{ t(ui.key === 'conflict' ? 'collaboration.ui.handleFiles' : ui.action !== 'none' ? `collaboration.ui.actions.${ui.action}` : 'collaboration.ui.view') }}</button>
    </div>
  </Transition>
</template>

<style scoped>
.collaboration-input-status {
  position: absolute;
  bottom: calc(100% + 8px);
  right: 0;
  max-width: 100%;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  border: 1px solid var(--color-warning-200, #fde68a);
  border-radius: 8px;
  background: var(--color-warning-50, #fffbeb);
  box-shadow: 0 2px 8px rgb(15 23 42 / 6%);
  font-size: 12px;
  color: var(--color-text-muted);
}
.collaboration-input-status span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.collaboration-input-status.is-warning { color: var(--color-warning-600, #b45309); }
.collaboration-input-status button {
  flex-shrink: 0;
  border: 0;
  border-radius: 6px;
  background: none;
  padding: 4px;
  min-height: 24px;
  color: var(--color-primary-600);
  font: inherit;
  white-space: nowrap;
  cursor: pointer;
}
.collaboration-input-status button:hover { background: var(--color-primary-50, #f0f9ff); }
.collaboration-input-status button:focus-visible { outline: 2px solid var(--color-primary-500); outline-offset: -2px; }
.status-spinner { width: 14px; height: 14px; flex-shrink: 0; animation: status-spin 1s linear infinite; }
.collaboration-status-enter-active { transition: opacity 180ms ease; }
.collaboration-status-leave-active { transition: opacity 120ms ease; pointer-events: none; }
.collaboration-status-enter-from, .collaboration-status-leave-to { opacity: 0; }
@keyframes status-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .status-spinner { animation: none; }
  .collaboration-status-enter-active, .collaboration-status-leave-active { transition: none; }
}
</style>
