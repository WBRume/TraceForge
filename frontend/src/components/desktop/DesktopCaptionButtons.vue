<script setup lang="ts">
import { onMounted, onScopeDispose, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { getCurrentWindow } from '@tauri-apps/api/window'
import type { DesktopWorkspaceWindowsApi } from '@/types/workspaceWindows'

const props = defineProps<{ api: DesktopWorkspaceWindowsApi }>()
const emit = defineEmits<{ error: [error: unknown] }>()
const { t } = useI18n()
const maximized = shallowRef(false)

function refresh() {
  void getCurrentWindow().isMaximized().then(value => { maximized.value = value }).catch(console.error)
}

async function control(action: 'minimize' | 'maximize' | 'close') {
  try {
    await props.api.control(action)
    if (action === 'maximize') refresh()
  } catch (error) {
    emit('error', error)
  }
}

onMounted(() => {
  refresh()
  window.addEventListener('resize', refresh)
})
onScopeDispose(() => window.removeEventListener('resize', refresh))
</script>

<template>
  <div class="caption" :aria-label="t('desktop_tabs.caption')" role="group">
    <button type="button" :title="t('desktop_tabs.minimize')" :aria-label="t('desktop_tabs.minimize')" @click="control('minimize')">
      <span class="minimize" aria-hidden="true"></span>
    </button>
    <button type="button" :title="t(maximized ? 'common.restore' : 'desktop_tabs.maximize')"
      :aria-label="t(maximized ? 'common.restore' : 'desktop_tabs.maximize')" @click="control('maximize')">
      <span :class="maximized ? 'restore' : 'maximize'" aria-hidden="true"></span>
    </button>
    <button class="caption-close" type="button" :title="t('desktop_tabs.close_window')" :aria-label="t('desktop_tabs.close_window')" @click="control('close')">
      <span class="close" aria-hidden="true"></span>
    </button>
  </div>
</template>

<style scoped>
.caption { align-self: stretch; display: flex; flex: none; }
.caption button { width: 46px; border: 0; display: grid; place-items: center; background: transparent; color: #334155; }
.caption button:hover { background: #dce6f0; }
.caption button.caption-close:hover { background: #c42b1c; color: white; }
.minimize, .maximize, .restore, .close { position: relative; display: block; }
.minimize { width: 10px; border-bottom: 1px solid currentColor; }
.maximize { width: 10px; height: 10px; border: 1px solid currentColor; }
.restore { width: 11px; height: 11px; border-top: 1px solid currentColor; border-right: 1px solid currentColor; }
.restore::after { content: ''; position: absolute; top: 2px; right: 2px; width: 8px; height: 8px; border: 1px solid currentColor; }
.close::before, .close::after { content: ''; position: absolute; left: -6px; width: 12px; height: 1px; background: currentColor; transform: rotate(45deg); }
.close::after { transform: rotate(-45deg); }
</style>
