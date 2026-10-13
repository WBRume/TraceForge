<script setup lang="ts">
import { computed, proxyRefs } from 'vue'
import { useI18n } from 'vue-i18n'
import { RefreshCw } from '@/components/icons'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'

const props = defineProps<{ controller: LocalCollaboration }>()
const { t } = useI18n()
const c = computed(() => proxyRefs(props.controller))
</script>

<template>
  <div class="collaboration-actions">
    <div v-if="c.participating && c.driver && c.available" class="auto-receive" :title="t('collaboration.ui.autoReceiveHint')">
      <span>{{ t('collaboration.ui.autoReceive') }}</span>
      <ToggleSwitch :model-value="c.progressive" :disabled="c.busy || c.leaving" :aria-label="t('collaboration.ui.autoReceive')" @update:model-value="c.setProgressive" />
    </div>
    <button class="icon-btn" type="button" :disabled="c.busy || c.leaving" :title="t('collaboration.refresh')" :aria-label="t('collaboration.refresh')" @click="c.refresh()">
      <RefreshCw class="w-4 h-4" />
    </button>
  </div>
</template>

<style scoped>
.collaboration-actions { display: flex; align-items: center; gap: 12px; }
.auto-receive { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-secondary, #64748b); }
.auto-receive > span { max-width: 160px; }
.icon-btn { width: 30px; height: 30px; border-radius: 6px; display: grid; place-items: center; color: #64748b; background: transparent; border: 0; cursor: pointer; transition: background .15s, color .15s; }
.icon-btn:hover:not(:disabled) { background: #f1f5f9; color: #0f172a; }
.icon-btn:disabled { opacity: .5; cursor: default; }
.icon-btn:focus-visible { outline: 2px solid #0ea5e9; outline-offset: 2px; }
@media (max-width: 640px) {
  .collaboration-actions { gap: 6px; }
  .auto-receive { gap: 6px; font-size: 11px; }
  .auto-receive > span { max-width: 66px; line-height: 1.4; }
}
</style>
