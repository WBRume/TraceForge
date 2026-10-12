<script setup lang="ts">
import { shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CollaborationBackup } from '@/types/collaboration'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
const props = defineProps<{ controller: LocalCollaboration }>()
const emit = defineEmits<{ select: [backup: CollaborationBackup] }>()
const { t } = useI18n()
const entries = shallowRef<CollaborationBackup[]>([]), error = shallowRef(''), busy = shallowRef(false)
async function load(event: Event) {
  if (!(event.target as HTMLDetailsElement).open) return
  busy.value = true; error.value = ''
  try { entries.value = (await props.controller.listBackups()).backups }
  catch (reason) { error.value = String(reason) }
  finally { busy.value = false }
}
async function exportFile(backup: CollaborationBackup) {
  try { await props.controller.exportBackup(backup) } catch (reason) { error.value = String(reason) }
}
</script>
<template>
  <details class="backups" @toggle="load"><summary>{{ t('collaboration.backups') }}</summary><p v-if="error" role="alert">{{ error }}</p><p v-if="busy">{{ t('common.loading') }}</p><p v-else-if="!entries.length">{{ t('collaboration.noBackups') }}</p><div v-for="entry in entries" :key="`${entry.operation_id}:${entry.task_repository_id}:${entry.path}`" class="backup-row"><span>{{ entry.task_repository_id }}/{{ entry.path }}<small>{{ entry.operation_id }}</small></span><span v-if="!entry.sha256">{{ t('collaboration.absent') }}</span><button class="btn-micro" :disabled="!entry.sha256" @click="emit('select', entry)">{{ t('collaboration.viewBackup') }}</button><button class="btn-micro" :disabled="!entry.sha256" @click="exportFile(entry)">{{ t('collaboration.exportBackup') }}</button></div></details>
</template>
<style scoped>.backups { padding: 12px 18px; border-top: 1px solid var(--border-color,#e2e8f0); font-size: 12px; max-height: 220px; overflow: auto; }.backups summary { cursor: pointer; }.backup-row { display: flex; align-items: center; gap: 8px; padding: 10px 0; }.backup-row span { flex: 1; overflow-wrap: anywhere; }.backup-row small { display: block; color: var(--text-secondary); }</style>
