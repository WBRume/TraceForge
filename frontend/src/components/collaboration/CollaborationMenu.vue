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
      </template>
    </div>
  </details>
</template>

<style scoped>
.toolbar-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 30px;
  width: 30px;
  padding: 0;
  border: 0;
  border-radius: 6px;
  color: var(--color-text-muted, #64748b);
  background: transparent;
  cursor: pointer;
  transition: all 0.15s ease;
}
.toolbar-button:hover {
  background: var(--color-bg-base, #f1f5f9);
  color: var(--color-text-title, #0f172a);
}
.collaboration-menu { position: relative; }
.collaboration-menu summary { list-style: none; }
.collaboration-menu summary::-webkit-details-marker { display: none; }
.menu-items {
  position: absolute;
  top: 36px;
  right: 0;
  z-index: 20;
  width: 190px;
  padding: 6px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.12), 0 8px 10px -6px rgba(15, 23, 42, 0.08);
}
.menu-items button {
  display: block;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: 6px;
  background: none;
  color: var(--color-text-body, #334155);
  text-align: left;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.12s;
}
.menu-items button:hover {
  background: var(--color-bg-base, #f8fafc);
  color: var(--color-text-title, #0f172a);
}
.menu-items button:disabled { opacity: .45; cursor: default; }
.menu-items hr { border: 0; border-top: 1px solid #e2e8f0; margin: 4px 0; }
</style>
