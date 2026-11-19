<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { GitPullRequest } from '@/components/icons'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
import { openCollaborationView, useCollaborationPresentation } from '@/composables/collaboration/useCollaborationPresentation'
const props = defineProps<{ controller: LocalCollaboration }>()
const emit = defineEmits<{ open: [] }>()
const { t } = useI18n()
const ui = useCollaborationPresentation(() => props.controller)
function open() { openCollaborationView(props.controller); emit('open') }
</script>

<template>
  <button class="collaboration-entry" :class="ui?.tone" type="button" @click="open">
    <GitPullRequest :size="14" /><span>{{ t('collaboration.title') }}</span>
    <span v-if="controller.state.value?.repository_configured !== false" class="entry-state"><i />{{ ui?.short }}</span>
  </button>
</template>

<style scoped>
.collaboration-entry {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex-shrink: 0;
  max-width: 100%;
  padding: 5px 9px;
  border: 1px solid #e5eaf0;
  border-radius: 6px;
  background: var(--color-surface-white);
  color: var(--color-text-body);
  font-size: 12px;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0);
  transition:
    transform 0.18s cubic-bezier(0.22, 1, 0.36, 1),
    box-shadow 0.18s ease,
    border-color 0.18s ease,
    background-color 0.18s ease;
}
.collaboration-entry:hover {
  transform: translateY(-1px);
  border-color: #cbd5e1;
  background: var(--color-surface-white, #fff);
  box-shadow: 0 4px 10px -4px rgba(15, 23, 42, 0.28), 0 1px 2px rgba(15, 23, 42, 0.06);
}
.collaboration-entry:active {
  transform: translateY(0);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
}
.collaboration-entry:focus-visible {
  outline: 2px solid var(--color-primary-400, #38bdf8);
  outline-offset: 1px;
}
.entry-state { display: inline-flex; align-items: center; gap: 6px; min-width: 0; padding-left: 8px; border-left: 1px solid #e5eaf0; color: var(--color-text-muted); font-size: 11px; }
.entry-state i { width: 5px; height: 5px; flex-shrink: 0; background: currentColor; border-radius: 50%; }.warning .entry-state { color: #a66a12; }
@media (prefers-reduced-motion: reduce) {
  .collaboration-entry { transition: none; }
  .collaboration-entry:hover,
  .collaboration-entry:active { transform: none; }
}
</style>
