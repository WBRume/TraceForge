<script setup lang="ts">
import { computed, proxyRefs, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowLeft, MoreHorizontal, Settings } from '@/components/icons'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
const props = defineProps<{ controller: LocalCollaboration }>()
const emit = defineEmits<{ history: [] }>()
const { t } = useI18n()
const c = computed(() => proxyRefs(props.controller)), menu = ref<HTMLDetailsElement>()
function close() { if (menu.value) menu.value.open = false }
function page(name: string) { close(); c.value.view.page = name }
</script>

<template>
  <button v-if="c.view.page !== 'files'" type="button" class="toolbar-button" :title="t('collaboration.back')" :aria-label="t('collaboration.back')" @click="page('files')"><ArrowLeft :size="16" /></button>
  <button v-if="c.enabled && !c.preparationRequired && c.view.page !== 'settings'" type="button" class="toolbar-button" :title="t('collaboration.ui.settings')" :aria-label="t('collaboration.ui.settings')" @click="page('settings')"><Settings :size="16" /></button>
  <details ref="menu" class="collaboration-menu" @keydown.esc.prevent.stop="close" @focusout="event => { if (!menu?.contains(event.relatedTarget as Node)) close() }">
    <summary class="toolbar-button" :aria-label="t('collaboration.ui.more')" :title="t('collaboration.ui.more')"><MoreHorizontal :size="17" /></summary>
    <div class="menu-items">
      <button type="button" :disabled="c.busy" @click="close(); c.refreshComparison()">{{ t('collaboration.refresh') }}</button>
      <button v-if="c.driver && c.local?.baseline" type="button" @click="page('backups')">{{ t('collaboration.backups') }}</button>
      <button type="button" @click="close(); emit('history')">{{ t('collaboration.history') }}</button>
      <button v-if="c.participating" type="button" :disabled="c.busy || c.leaving" @click="page('disconnect')">{{ t('collaboration.session.disconnect') }}…</button>
      <template v-if="c.participating && c.driver && c.phase === 'READY'">
        <button v-if="c.local?.local_changes?.length" type="button" :disabled="c.blocked" @click="close(); c.handoffLocalChanges()">{{ t('collaboration.ui.syncOnly') }}</button>
        <hr /><button type="button" :disabled="c.blocked" @click="page('disable')">{{ t('collaboration.disable') }}…</button>
      </template>
    </div>
  </details>
</template>

<style scoped>
.toolbar-button { display: inline-flex; align-items: center; justify-content: center; height: 28px; width: 28px; padding: 0; border: 0; border-radius: 5px; color: var(--color-text-muted); background: transparent; cursor: pointer; }.toolbar-button:hover { background: var(--color-bg-base); }.collaboration-menu { position: relative; }.collaboration-menu summary { list-style: none; }.collaboration-menu summary::-webkit-details-marker { display: none; }.menu-items { position: absolute; top: 34px; right: 0; z-index: 5; width: 180px; padding: 5px; border: 1px solid #e5eaf0; border-radius: 8px; background: var(--color-surface-white); box-shadow: 0 8px 24px #162d451a; }.menu-items button { display: block; width: 100%; padding: 9px 10px; border: 0; border-radius: 4px; background: none; color: var(--color-text-body); text-align: left; font-size: 12px; cursor: pointer; }.menu-items button:hover { background: var(--color-bg-base); }.menu-items button:disabled { opacity: .45; cursor: default; }.menu-items hr { border: 0; border-top: 1px solid #e5eaf0; margin: 4px 0; }
</style>
