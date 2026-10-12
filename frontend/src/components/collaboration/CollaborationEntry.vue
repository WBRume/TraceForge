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
    <span class="entry-state"><i />{{ ui?.short }}</span>
  </button>
</template>

<style scoped>
.collaboration-entry { display: inline-flex; align-items: center; gap: 7px; flex-shrink: 0; max-width: 100%; padding: 5px 9px; border: 1px solid #e5eaf0; border-radius: 6px; background: var(--color-surface-white); color: var(--color-text-body); font-size: 12px; cursor: pointer; }
.entry-state { display: inline-flex; align-items: center; gap: 6px; min-width: 0; padding-left: 8px; border-left: 1px solid #e5eaf0; color: var(--color-text-muted); font-size: 11px; }
.entry-state i { width: 5px; height: 5px; flex-shrink: 0; background: currentColor; border-radius: 50%; }.warning .entry-state { color: #a66a12; }
</style>
