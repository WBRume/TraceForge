<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CollaborationBackup } from '@/types/collaboration'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
import { groupCollaborationBackups } from '@/composables/collaboration/backups'
const props = defineProps<{ controller: LocalCollaboration }>()
const emit = defineEmits<{ select: [backup: CollaborationBackup] }>()
const { t, locale } = useI18n()
const entries = shallowRef<CollaborationBackup[]>([]), error = shallowRef(''), busy = shallowRef(false)
watch(() => [props.controller, props.controller.state.value?.binding_id, props.controller.local.value?.task_id], async (_, __, onCleanup) => {
  let current = true
  onCleanup(() => { current = false })
  entries.value = []
  busy.value = true; error.value = ''
  try { const result = await props.controller.listBackups(); if (current) entries.value = result.backups }
  catch (reason) { if (current) error.value = String(reason) }
  finally { if (current) busy.value = false }
}, { immediate: true })
const repositoryName = (id: string) => props.controller.state.value?.repositories.find(repo => repo.task_repository_id === id)?.repo_slug || id
const rounds = computed(() => groupCollaborationBackups(entries.value, repositoryName))
const formatTime = (value?: string) => value && Number.isFinite(Date.parse(value))
  ? new Date(value).toLocaleString(locale.value, { hour12: false }) : t('collaboration.backupGroups.unknownTime')
async function exportFile(backup: CollaborationBackup) {
  try { await props.controller.exportBackup(backup) } catch (reason) { error.value = String(reason) }
}
</script>
<template>
  <section class="backups">
    <h2>{{ t('collaboration.backups') }}</h2>
    <p class="intro">{{ t('collaboration.ui.backupsHint') }}</p>
    <p v-if="error" role="alert" class="state-msg error">{{ error }}</p>
    <p v-if="busy" class="state-msg">{{ t('common.loading') }}</p>
    <p v-else-if="!entries.length" class="state-msg">{{ t('collaboration.noBackups') }}</p>
    <div v-else class="backup-list">
      <section v-for="round in rounds" :key="round.id" class="backup-round">
        <header class="round-header">
          <h3>{{ round.context?.turn_title || (round.context?.turn_index != null ? t('collaboration.backupGroups.round', { count: round.context.turn_index }) : t('collaboration.backupGroups.unknownRound')) }}</h3>
          <time :datetime="round.context?.turn_created_at || round.createdAt">{{ formatTime(round.context?.turn_created_at || round.createdAt) }}</time>
        </header>
        <section v-for="repo in round.repositories" :key="repo.id" class="backup-repository">
          <h4>{{ repo.name }}</h4>
          <div v-for="entry in repo.entries" :key="`${entry.operation_id}:${entry.path}`" class="backup-card">
            <div class="backup-meta">
              <strong>{{ entry.path }}</strong>
              <small v-if="!entry.sha256" class="absent-pill">{{ t('collaboration.absent') }}</small>
              <time v-if="repo.repeatedPaths.has(entry.path)" class="file-time" :datetime="entry.created_at">{{ formatTime(entry.created_at) }}</time>
            </div>
            <div class="backup-actions">
              <button class="btn-secondary btn-sm" type="button" :disabled="!entry.sha256" @click="emit('select', entry)">{{ t('collaboration.viewBackup') }}</button>
              <button class="btn-secondary btn-sm" type="button" :disabled="!entry.sha256" @click="exportFile(entry)">{{ t('collaboration.exportBackup') }}</button>
            </div>
          </div>
        </section>
      </section>
    </div>
  </section>
</template>

<style scoped>
.backups { padding: 20px 24px; font-size: 12px; overflow-y: auto; background: var(--color-bg-base, #f8fafc); flex: 1; }
.backups h2 { font-size: 15px; font-weight: 600; margin: 0; color: var(--color-text-title, #0f172a); }
.intro { color: var(--color-text-muted, #64748b); margin: 4px 0 16px; font-size: 12px; line-height: 1.6; }

.backup-list { display: flex; flex-direction: column; gap: 10px; }
.backup-round { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; flex-shrink: 0; }
.round-header { display: flex; flex-direction: column; gap: 4px; padding: 12px 16px; background: #f1f5f9; }
.round-header h3 { margin: 0; font-size: 13px; font-weight: 600; line-height: 1.6; overflow-wrap: anywhere; color: var(--color-text-title, #0f172a); }
.round-header time, .file-time { font-size: 11px; color: var(--color-text-muted, #64748b); }
.file-time { display: block; margin-top: 3px; }
.backup-repository { padding: 12px 16px; }
.backup-repository + .backup-repository { padding-top: 0; }
.backup-repository h4 { margin: 0 0 6px; font-size: 12px; overflow-wrap: anywhere; }
.backup-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  margin-top: 6px;
}
.backup-meta { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.backup-meta strong { display: block; font-size: 12.5px; font-weight: 600; color: var(--color-text-title, #0f172a); font-family: var(--font-mono, monospace); }
.absent-pill { color: #dc2626; font-size: 11px; margin-top: 3px; }

.backup-actions { display: flex; gap: 8px; flex-shrink: 0; }
.btn-sm { padding: 4px 10px; font-size: 11px; }

.state-msg { color: var(--color-text-muted, #64748b); padding: 24px 0; text-align: center; font-size: 12.5px; }
.state-msg.error { color: #dc2626; }

@media(max-width:600px) {
  .backup-card { flex-wrap: wrap; }
  .backup-meta { flex-basis: 100%; }
}
</style>
