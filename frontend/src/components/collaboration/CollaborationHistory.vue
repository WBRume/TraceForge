<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import CodeComparison from './CodeComparison.vue'
import { collaborationApi } from '@/services/collaborationApi'
import { formatApiError } from '@/utils/error'
import type { CollaborationHumanChangePage, CollaborationHumanChangeDetail } from '@/types/collaboration'

const props = defineProps<{ workspaceId: string; taskId: string; handoffId?: string }>()
const { t } = useI18n()
const page = ref(1), selected = ref(''), fileKey = ref('')
const list = shallowRef<CollaborationHumanChangePage | null>(null), detail = shallowRef<CollaborationHumanChangeDetail | null>(null)
const loading = ref(false), detailLoading = ref(false), error = ref(''), retry = ref(0)
const api = computed(() => collaborationApi(props.workspaceId, props.taskId))
const key = (file: CollaborationHumanChangeDetail['files'][number]) => JSON.stringify([file.task_repository_id, file.path])
const active = computed(() => detail.value?.files.find(file => key(file) === fileKey.value))
const groups = computed(() => [...new Set(detail.value?.files.map(file => file.task_repository_id))].map(id => ({
  id, files: detail.value!.files.filter(file => file.task_repository_id === id),
})))
const time = (value: string) => value.replace('T', ' ').replace(/\.\d+$/, '')
const options = computed(() => (list.value?.items || []).map(row => ({ value: row.id,
  label: `${time(row.created_at)} · ${row.actor_name || t('collaboration.humanHistory.localUser')} · ${t('collaboration.humanHistory.fileCount', { count: row.changed_files_count })}`,
})))
watch(() => [props.workspaceId, props.taskId], () => { page.value = 1 })
watch(() => [props.workspaceId, props.taskId, props.handoffId, page.value, retry.value], async (_, __, onCleanup) => {
  let current = true; onCleanup(() => { current = false })
  error.value = ''; selected.value = ''; list.value = null
  if (props.handoffId) { selected.value = props.handoffId; loading.value = false; return }
  loading.value = true
  try {
    const result = await api.value.humanChanges(page.value)
    if (current) { list.value = result; selected.value = result.items[0]?.id || '' }
  } catch (reason) { if (current) error.value = formatApiError(reason, t('collaboration.failed')) }
  finally { if (current) loading.value = false }
}, { immediate: true })
watch(() => [selected.value, retry.value], async (_, __, onCleanup) => {
  let current = true; onCleanup(() => { current = false })
  detail.value = null; fileKey.value = ''; detailLoading.value = false
  if (!selected.value) return
  detailLoading.value = true; error.value = ''
  try {
    const result = await api.value.humanChange(selected.value)
    if (current) { detail.value = result; fileKey.value = result.files[0] ? key(result.files[0]) : '' }
  } catch (reason) { if (current) error.value = formatApiError(reason, t('collaboration.failed')) }
  finally { if (current) detailLoading.value = false }
}, { immediate: true })
async function readText(hash: string) {
  const file = active.value
  if ([file?.before, file?.after].some(entry => entry?.sha256 === hash && entry.size > 2 * 1024 * 1024)) throw new Error(t('collaboration.humanHistory.largeFile'))
  const bytes = new Uint8Array(await api.value.object(hash))
  if (bytes.includes(0)) throw new Error(t('collaboration.humanHistory.binaryFile'))
  try { return new TextDecoder('utf-8', { fatal: true }).decode(bytes) }
  catch { throw new Error(t('collaboration.humanHistory.binaryFile')) }
}
</script>

<template>
  <section class="human-history">
    <header><h2>{{ t('collaboration.history') }}</h2><p>{{ t('collaboration.humanHistory.hint') }}</p><p v-if="handoffId && detail"><time :datetime="detail.created_at">{{ time(detail.created_at) }}</time></p></header>
    <div v-if="list?.items.length && !handoffId" class="history-selector">
      <BaseSelect v-model="selected" :options="options" :aria-label="t('collaboration.history')" />
      <div v-if="list.total > list.page_size" class="pages"><button type="button" :disabled="page === 1 || loading" @click="page--">{{ t('collaboration.humanHistory.previous') }}</button><span>{{ page }} / {{ Math.ceil(list.total / list.page_size) }}</span><button type="button" :disabled="page * list.page_size >= list.total || loading" @click="page++">{{ t('collaboration.humanHistory.next') }}</button></div>
    </div>
    <p v-if="error" role="alert" class="history-message">{{ error }} <button type="button" @click="retry++">{{ t('common.retry') }}</button></p>
    <p v-else-if="loading || detailLoading" role="status" class="history-message">{{ t('common.loading') }}</p>
    <div v-else-if="active" class="history-body">
      <nav :aria-label="t('collaboration.ui.changedFiles')">
        <section v-for="group in groups" :key="group.id"><h3>{{ group.files[0]?.repo_slug }} <small>{{ group.files[0]?.branch_name }}</small></h3>
          <button v-for="file in group.files" :key="key(file)" type="button" :class="{ selected: fileKey === key(file) }" :aria-pressed="fileKey === key(file)" @click="fileKey = key(file)"><span>{{ file.path }}</span><small>{{ !file.before ? 'A' : !file.after ? 'D' : 'M' }}</small></button>
        </section>
      </nav>
      <div class="history-diff"><CodeComparison :path="`${active.repo_slug}/${active.path}`" :left-hash="active.before?.sha256" :right-hash="active.after?.sha256" :left-label="t('collaboration.humanHistory.before')" :right-label="t('collaboration.humanHistory.after')" :read-text="readText" word-wrap />
        <p v-if="active.before?.mode !== active.after?.mode" class="mode-change">{{ t('collaboration.ui.fileMode') }} {{ active.before?.mode || '—' }} → {{ active.after?.mode || '—' }}</p>
      </div>
    </div>
    <p v-else class="history-message">{{ t('collaboration.humanHistory.empty') }}</p>
  </section>
</template>

<style scoped>
.human-history { display:flex; flex:1; flex-direction:column; min-height:0; min-width:0; overflow:hidden; }
header { padding:20px 24px 12px; }h2 { margin:0; font-size:17px; }header p { margin:8px 0 0; color:var(--color-text-muted); font-size:12px; line-height:1.7; }
.history-selector { padding:0 24px 16px; display:flex; gap:12px; align-items:center; }.history-selector :deep(.base-select) { flex:1; min-width:0; }.pages { display:flex; align-items:center; gap:8px; flex-shrink:0; font-size:12px; }button { cursor:pointer; }button:disabled { cursor:default; opacity:.45; }.pages button,.history-message button { border:0; color:var(--color-primary-600); background:transparent; }
.history-body { display:flex; flex:1; min-height:0; border-top:1px solid #e5eaf0; }nav { width:240px; flex-shrink:0; overflow:auto; border-right:1px solid #e5eaf0; }nav h3 { padding:12px 14px 4px; margin:0; font-size:12px; }nav h3 small { font-weight:400; color:var(--color-text-muted); margin-left:6px; }nav button { display:flex; gap:8px; width:100%; text-align:left; border:0; background:transparent; padding:12px 14px; color:var(--color-text-body); font-size:12px; }nav button span { flex:1; min-width:0; overflow-wrap:anywhere; }nav button small { color:var(--color-text-muted); }nav button.selected { background:var(--color-primary-50); color:var(--color-primary-600); }.history-diff { display:flex; flex:1; min-width:0; min-height:0; flex-direction:column; }.history-message { padding:24px; font-size:13px; color:var(--color-text-muted); }.mode-change { padding:8px 14px; margin:0; font-size:11px; color:var(--color-text-muted); }
@media(max-width:720px) { .history-body { flex-direction:column; }nav { width:100%; max-height:170px; border-right:0; border-bottom:1px solid #e5eaf0; }.history-selector { flex-wrap:wrap; padding:0 16px 12px; }header { padding:16px; } }
</style>
