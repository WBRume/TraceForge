<script setup lang="ts">
import { computed, proxyRefs, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { GitPullRequest } from '@/components/icons'
import { ElPopover } from 'element-plus'
import { useCollaborationPresentation } from '@/composables/collaboration/useCollaborationPresentation'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'

const props = defineProps<{ controller: LocalCollaboration; error?: string }>()
const { t } = useI18n()
const errorOpen = ref(false)
function closeError(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !errorOpen.value) return
  event.preventDefault(); event.stopPropagation(); errorOpen.value = false
}
const c = computed(() => proxyRefs(props.controller))
const errors = computed(() => [...new Set([props.error, c.value.reviewError, c.value.error,
  ...c.value.local?.errors || [], c.value.state?.recovery_message].filter((value): value is string => Boolean(value)))])
const ui = useCollaborationPresentation(() => props.controller)
const repositoryCount = computed(() => proxyRefs(props.controller).state?.repositories.length ?? 0)
const active = computed(() => ['loading', 'connecting', 'preparing', 'running', 'transferring', 'leaving'].includes(ui.value?.key || ''))
const tone = computed(() => errors.value.length || ui.value?.tone === 'warning' ? 'warning' : active.value ? 'working'
  : ['ready', 'received', 'local'].includes(ui.value?.key || '') ? 'success' : 'neutral')
const status = computed(() => c.value.reviewRunning && !c.value.participating ? 'Agent 正在执行，完成后更新变更'
  : ['browse', 'connect'].includes(ui.value?.key || '') ? t('collaboration.phases.OFF') : ui.value?.title)
</script>

<template>
  <div class="collaboration-header" :class="[tone, { 'is-active': active }]" @keydown="closeError">
    <div class="collab-badge-icon" aria-hidden="true"><GitPullRequest :size="16" /></div>
    <div class="collab-header-titles">
      <h2>{{ t('collaboration.title') }}<span v-if="repositoryCount" class="repo-count-pill">{{ t('collaboration.ui.repositoryCount', { count: repositoryCount }) }}</span></h2>
      <div class="collaboration-status" role="status">
        <span class="status-dot" aria-hidden="true" />
        <ElPopover v-if="errors.length" v-model:visible="errorOpen" placement="bottom-start" trigger="click" :hide-after="0" :width="360" popper-class="collaboration-error-popover">
          <template #reference><button class="error-trigger" type="button" :aria-label="t('collaboration.ui.errorDetails')" :title="errors.join('\n')"><span>{{ errors[0] }}</span><span class="error-more">详情</span></button></template>
          <div class="header-errors"><strong>{{ t('collaboration.ui.errorDetails') }}</strong><p v-for="problem in errors" :key="problem">{{ problem }}</p></div>
        </ElPopover>
        <span v-else>{{ status }}</span>
      </div>
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
.error-trigger { display: flex; gap: 6px; align-items: center; min-width: 0; padding: 0; border: 0; background: none; color: #b45309; font: inherit; cursor: pointer; text-align: left; }
.error-trigger > span:first-child { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.error-more { flex: none; text-decoration: underline; text-underline-offset: 2px; }
.error-trigger:focus-visible { outline: 2px solid #0284c7; outline-offset: 2px; }
.header-errors { font-size: 12px; color: #92400e; max-height: 240px; overflow: auto; overflow-wrap: anywhere; }
.header-errors p { margin: 8px 0 0; line-height: 1.6; white-space: pre-wrap; }
:global(.collaboration-error-popover) { max-width: calc(100vw - 32px); }
.status-dot { width: 6px; height: 6px; flex-shrink: 0; border-radius: 50%; background: var(--status-color); }
.is-active .status-dot, .is-active .collab-badge-icon::after { animation: status-pulse 1.8s ease-in-out infinite; }
@keyframes status-pulse { 50% { opacity: .35; } }
@media (prefers-reduced-motion: reduce) { .is-active .status-dot, .is-active .collab-badge-icon::after { animation: none; } }
</style>
