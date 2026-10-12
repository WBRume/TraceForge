<script setup lang="ts">
import { shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CollaborationBackup } from '@/types/collaboration'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
const props = defineProps<{ controller: LocalCollaboration }>()
const emit = defineEmits<{ select: [backup: CollaborationBackup] }>()
const { t } = useI18n()
const entries = shallowRef<CollaborationBackup[]>([]), error = shallowRef(''), busy = shallowRef(false)
async function load() {
  busy.value = true; error.value = ''
  try { entries.value = (await props.controller.listBackups()).backups }
  catch (reason) { error.value = String(reason) }
  finally { busy.value = false }
}
watch(() => props.controller.state.value?.binding_id, load, { immediate: true })
const repositoryName = (id: string) => props.controller.state.value?.repositories.find(repo => repo.task_repository_id === id)?.repo_slug || id
async function exportFile(backup: CollaborationBackup) {
  try { await props.controller.exportBackup(backup) } catch (reason) { error.value = String(reason) }
}
</script>
<template>
  <section class="backups"><h2>{{ t('collaboration.backups') }}</h2><p class="intro">{{ t('collaboration.ui.backupsHint') }}</p><p v-if="error" role="alert">{{ error }}</p><p v-if="busy">{{ t('common.loading') }}</p><p v-else-if="!entries.length">{{ t('collaboration.noBackups') }}</p><div v-for="entry in entries" :key="`${entry.operation_id}:${entry.task_repository_id}:${entry.path}`" class="backup-row"><span><strong>{{ repositoryName(entry.task_repository_id) }}</strong><small>{{ entry.path }}</small></span><span v-if="!entry.sha256">{{ t('collaboration.absent') }}</span><button class="btn-micro" type="button" :disabled="!entry.sha256" @click="emit('select', entry)">{{ t('collaboration.viewBackup') }}</button><button class="btn-micro" type="button" :disabled="!entry.sha256" @click="exportFile(entry)">{{ t('collaboration.exportBackup') }}</button></div></section>
</template>
<style scoped>.backups { padding: 28px 24px; font-size: 12px; overflow: auto; }.backups h2 { font-size: 19px; margin: 0; }.intro { color: var(--color-text-muted); margin: 8px 0 24px; }.backup-row { display: flex; align-items: center; gap: 8px; padding: 16px 0; border-bottom: 1px solid #e5eaf0; }.backup-row span { flex: 1; min-width: 0; overflow-wrap: anywhere; }.backup-row small { display: block; color: var(--color-text-muted); }.backup-row button { flex-shrink: 0; }@media(max-width:600px) { .backup-row { flex-wrap: wrap; }.backup-row>span:first-child { flex-basis: 100%; } }</style>
