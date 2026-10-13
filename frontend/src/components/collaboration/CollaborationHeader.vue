<script setup lang="ts">
import { computed, proxyRefs } from 'vue'
import { useI18n } from 'vue-i18n'
import { GitPullRequest } from '@/components/icons'
import { useCollaborationPresentation } from '@/composables/collaboration/useCollaborationPresentation'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'

const props = defineProps<{ controller: LocalCollaboration }>()
const { t } = useI18n()
const ui = useCollaborationPresentation(() => props.controller)
const repositoryCount = computed(() => proxyRefs(props.controller).state?.repositories.length ?? 0)
const active = computed(() => ['loading', 'connecting', 'preparing', 'running', 'transferring', 'leaving'].includes(ui.value?.key || ''))
const tone = computed(() => ui.value?.tone === 'warning' ? 'warning' : active.value ? 'working'
  : ['ready', 'received', 'local'].includes(ui.value?.key || '') ? 'success' : 'neutral')
const status = computed(() => ['browse', 'connect'].includes(ui.value?.key || '') ? t('collaboration.phases.OFF') : ui.value?.title)
</script>

<template>
  <div class="collaboration-header" :class="[tone, { 'is-active': active }]">
    <div class="collab-badge-icon" aria-hidden="true"><GitPullRequest :size="16" /></div>
    <div class="collab-header-titles">
      <h2>{{ t('collaboration.title') }}<span v-if="repositoryCount" class="repo-count-pill">{{ t('collaboration.ui.repositoryCount', { count: repositoryCount }) }}</span></h2>
      <div class="collaboration-status" role="status"><span class="status-dot" aria-hidden="true" /><span>{{ status }}</span></div>
    </div>
  </div>
</template>

<style scoped>
.collaboration-header { --status-color: #94a3b8; display: flex; align-items: center; gap: 10px; min-width: 0; }
.collaboration-header.working { --status-color: #0ea5e9; }
.collaboration-header.success { --status-color: #10b981; }
.collaboration-header.warning { --status-color: #d97706; }
.collab-badge-icon { width: 32px; height: 32px; border-radius: 8px; background: linear-gradient(135deg, rgba(14, 165, 233, .15), rgba(2, 132, 199, .25)); color: #0284c7; display: grid; place-items: center; flex-shrink: 0; position: relative; }
.collab-badge-icon::after { content: ''; position: absolute; width: 7px; height: 7px; border-radius: 50%; background: var(--status-color); right: -2px; top: -2px; border: 2px solid #fff; }
.collab-header-titles { display: flex; flex-direction: column; min-width: 0; }
h2 { font-size: 14px; font-weight: 600; color: #0f172a; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0; }
.repo-count-pill { font-size: 11px; font-weight: 500; padding: 1px 7px; border-radius: 12px; background: #f1f5f9; color: #64748b; border: 1px solid #e2e8f0; }
.collaboration-status { font-size: 11px; color: #64748b; display: flex; align-items: center; gap: 6px; margin-top: 1px; }
.status-dot { width: 6px; height: 6px; flex-shrink: 0; border-radius: 50%; background: var(--status-color); }
.is-active .status-dot, .is-active .collab-badge-icon::after { animation: status-pulse 1.8s ease-in-out infinite; }
@keyframes status-pulse { 50% { opacity: .35; } }
@media (prefers-reduced-motion: reduce) { .is-active .status-dot, .is-active .collab-badge-icon::after { animation: none; } }
</style>
