<script setup lang="ts">
import { computed, proxyRefs, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RefreshCw } from '@/components/icons'
import ToggleSwitch from '@/components/ToggleSwitch.vue'
import ConfirmActionModal from '@/components/ConfirmActionModal.vue'
import type { LocalCollaboration } from '@/composables/collaboration/useLocalCollaboration'
import { useCollaborationPresentation } from '@/composables/collaboration/useCollaborationPresentation'

const props = defineProps<{ controller: LocalCollaboration }>()
const { t } = useI18n()
const c = computed(() => proxyRefs(props.controller))
const ui = useCollaborationPresentation(() => props.controller)
const disabled = computed(() => c.value.busy || c.value.leaving || c.value.loading)
const confirmingDisconnect = shallowRef(false)
watch(() => props.controller, () => { confirmingDisconnect.value = false })
async function toggleCollaboration(value: boolean) {
  if (disabled.value) return
  if (!value) confirmingDisconnect.value = true
  else await connectOrReceive()
}
async function disconnect() {
  if (await c.value.leave()) confirmingDisconnect.value = false
}
async function connectOrReceive(receive = false) {
  if (c.value.state?.repositories.some(repo => !c.value.mappings[repo.task_repository_id])) {
    c.value.view.page = 'settings'; return
  }
  if (receive) await c.value.receiveOnce()
  else if (c.value.participating) await c.value.recover()
  else await c.value.enable()
}
async function recover() {
  if (ui.value?.action === 'device') c.value.view.page = 'settings'
  else if (ui.value?.action === 'reconnect') await c.value.claimDriver()
  else await connectOrReceive()
}
</script>

<template>
  <div class="collaboration-actions">
    <button v-if="!c.participating && c.available" class="session-button" type="button" :disabled="disabled" @click="connectOrReceive(true)">{{ t('collaboration.session.receive') }}</button>
    <div v-if="c.available" class="collaboration-switch" :title="!c.participating && c.enabled && !c.canReconnect ? t('collaboration.ui.activeDeviceHint') : ''">
      <span>{{ t('collaboration.connectionLabel') }}</span>
      <ToggleSwitch :model-value="c.participating" :disabled="disabled || !c.participating && c.enabled && !c.canReconnect" :aria-label="t('collaboration.connectionLabel')" @update:model-value="toggleCollaboration" />
    </div>
    <button v-if="c.participating && ui && ui.action !== 'none' && c.available" class="session-button primary" type="button" :disabled="disabled" @click="recover">{{ ui.actionLabel }}</button>
    <div v-if="c.participating && c.driver && c.available" class="auto-receive" :title="t('collaboration.ui.autoReceiveHint')">
      <span>{{ t('collaboration.ui.autoReceive') }}</span>
      <ToggleSwitch :model-value="c.progressive" :disabled="c.busy || c.leaving" :aria-label="t('collaboration.ui.autoReceive')" @update:model-value="c.setProgressive" />
    </div>
    <button class="icon-btn" type="button" :disabled="c.busy || c.leaving" :title="t('collaboration.refresh')" :aria-label="t('collaboration.refresh')" @click="c.refresh()">
      <RefreshCw class="w-4 h-4" />
    </button>
    <ConfirmActionModal :show="confirmingDisconnect" tone="primary" :title="t('collaboration.session.disconnect')" :message="t('collaboration.session.leaveHint')" :cancel-text="t('common.cancel')" :confirm-text="t('collaboration.session.disconnect')" :loading="c.busy || c.leaving" @cancel="confirmingDisconnect = false" @confirm="disconnect" />
  </div>
</template>

<style scoped>
.collaboration-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.collaboration-switch { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #475569; white-space: nowrap; }
.session-button { flex: none; padding: 6px 10px; border: 1px solid #dbe5ef; border-radius: 6px; color: #0284c7; background: #fff; font-size: 12px; line-height: 18px; cursor: pointer; white-space: nowrap; }
.session-button:hover:not(:disabled) { background: #f0f9ff; border-color: #7dd3fc; }
.session-button.primary { color: #fff; background: #0284c7; border-color: #0284c7; }
.session-button.primary:hover:not(:disabled) { background: #0369a1; }
.session-button:disabled { opacity: .5; cursor: default; }
.session-button:focus-visible { outline: 2px solid #0284c7; outline-offset: 2px; }
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
