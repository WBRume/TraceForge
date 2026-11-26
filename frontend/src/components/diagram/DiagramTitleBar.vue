<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import DesktopCaptionButtons from '@/components/desktop/DesktopCaptionButtons.vue'
import type { DiagramWindowApi } from '@/types/diagramDesktop'

defineProps<{ chrome: NonNullable<DiagramWindowApi['chrome']> }>()
const { t } = useI18n()
const icon = `${import.meta.env.BASE_URL}favicon.svg`

function showWindowError(error: unknown) {
  console.error('Diagram window control failed', error)
  ElMessage.error(t('desktop_tabs.operation_failed'))
}
</script>

<template>
  <header class="desktop-titlebar" data-testid="diagram-titlebar">
    <div class="desktop-brand desktop-drag-region" data-tauri-drag-region>
      <img :src="icon" alt="" draggable="false">
      <span>TraceForge</span>
    </div>
    <span class="tool-title desktop-drag-region" data-tauri-drag-region>{{ t('diagram.title') }}</span>
    <div class="desktop-drag-region empty-titlebar" data-tauri-drag-region aria-hidden="true"></div>
    <DesktopCaptionButtons v-if="chrome !== 'overlay'" :api="chrome" @error="showWindowError" />
    <div v-else class="caption-reserve" aria-hidden="true"></div>
  </header>
</template>

<style scoped src="../desktop/desktopWindowChrome.css"></style>
<style scoped>
.tool-title {
  align-self: stretch;
  display: flex;
  align-items: center;
  gap: 10px;
  padding-inline: 1px 6px;
}
.tool-title::before {
  content: '';
  width: 1px;
  height: 18px;
  background: var(--diagram-border);
}
</style>
