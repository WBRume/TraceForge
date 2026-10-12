<script setup lang="ts">
import { computed, onScopeDispose, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import MonacoDiffViewer from '@/components/diff/MonacoDiffViewer.vue'
import BaseSelect from '@/components/BaseSelect.vue'

const props = defineProps<{
  leftHash?: string; rightHash?: string; leftLabel: string; rightLabel: string
  readText: (hash: string) => Promise<string>; path: string
}>()
const { t } = useI18n()
const media = window.matchMedia('(max-width: 720px)')
const compact = shallowRef(media.matches), preferredLayout = shallowRef<string | null>(null)
const onResize = () => { compact.value = media.matches }
media.addEventListener('change', onResize)
onScopeDispose(() => media.removeEventListener('change', onResize))
const layout = computed({ get: () => preferredLayout.value || (compact.value ? 'unified' : 'split'), set: value => { preferredLayout.value = value } })
const original = shallowRef(''), modified = shallowRef('')
const loading = shallowRef(false), error = shallowRef('')
watch(() => [props.leftHash, props.rightHash, props.path], async (_, __, onCleanup) => {
  let current = true
  onCleanup(() => { current = false })
  loading.value = true; error.value = ''; original.value = ''; modified.value = ''
  try {
    const pair = await Promise.all([props.leftHash ? props.readText(props.leftHash) : '', props.rightHash ? props.readText(props.rightHash) : ''])
    if (current) [original.value, modified.value] = pair
  } catch (reason) { if (current) error.value = reason instanceof Error ? reason.message : String(reason) }
  finally { if (current) loading.value = false }
}, { immediate: true })
</script>

<template>
  <section class="code-comparison">
    <div class="comparison-toolbar"><strong>{{ path }}</strong><div class="comparison-tools"><slot name="tools" /><BaseSelect v-model="layout" size="sm" :aria-label="t('collaboration.ui.diffLayout')" :options="[{ value: 'split', label: t('collaboration.split') }, { value: 'unified', label: t('collaboration.unified') }]" /></div></div>
    <div class="comparison-sources"><span>{{ leftLabel }}{{ !leftHash ? ` · ${t('collaboration.absent')}` : '' }}</span><span>{{ rightLabel }}{{ !rightHash ? ` · ${t('collaboration.absent')}` : '' }}</span></div>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-else-if="loading" role="status">{{ t('common.loading') }}</p>
    <MonacoDiffViewer v-else :original="original" :modified="modified" :render-side-by-side="layout === 'split'" theme="vs" height="100%" />
  </section>
</template>

<style scoped>
.code-comparison { display: flex; flex: 1; flex-direction: column; min-height: 180px; min-width: 0; overflow: hidden; }
.comparison-toolbar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; padding: 10px 14px; }
.comparison-toolbar strong { flex: 1; min-width: 120px; overflow-wrap: anywhere; font-size: 12px; font-weight: 500; }.comparison-tools { display: flex; gap: 6px; flex-wrap: wrap; }.comparison-toolbar :deep(.base-select) { flex: none; width: 130px; min-width: 130px; }
.comparison-sources { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 8px 12px; background: var(--color-bg-base); font-size: 11px; }
small, p { padding: 8px 12px; color: var(--color-text-muted); }small { font-size: 11px; }
@media (max-width: 600px) { .comparison-toolbar { flex-wrap: wrap; }.comparison-toolbar strong { flex-basis: 100%; }.comparison-sources { gap: 8px; overflow-wrap: anywhere; } }
</style>
