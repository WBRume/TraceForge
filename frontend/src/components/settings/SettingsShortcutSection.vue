<script setup lang="ts">
import { onMounted, shallowRef, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { ExternalLink, PencilLine } from '@/components/icons'
import { DEFAULT_DIAGRAM_SHORTCUT, diagramShortcutFromKey } from '@/desktop/diagramShortcut'
import type { DiagramShortcutState } from '@/types/diagramDesktop'

const launcher = window.sddDesktop?.diagram
const { t } = useI18n()
const state = shallowRef<DiagramShortcutState>()
const recording = shallowRef(false)
const busy = shallowRef(false)
const error = shallowRef('')
const updated = shallowRef(false)
const capture = useTemplateRef<HTMLButtonElement>('capture')

onMounted(async () => {
  try { state.value = await launcher?.shortcut() }
  catch { error.value = t('diagram.shortcuts.failed') }
})

async function save(shortcut: string) {
  if (!launcher || busy.value) return
  busy.value = true
  recording.value = false
  error.value = ''
  updated.value = false
  try {
    state.value = await launcher.setShortcut(shortcut)
    updated.value = true
  } catch (cause) {
    const message = String(cause)
    error.value = t(message.includes('DIAGRAM_SHORTCUT_CONFLICT') ? 'diagram.shortcuts.conflict'
      : message.includes('DIAGRAM_SHORTCUT_UNAVAILABLE') ? 'diagram.shortcuts.unavailable' : 'diagram.shortcuts.failed')
  } finally {
    busy.value = false
  }
}

function record(event: KeyboardEvent) {
  if (!recording.value || event.isComposing || event.key === 'Tab') return
  event.preventDefault()
  if (event.key === 'Escape') { recording.value = false; return }
  if (['Control', 'Shift', 'Alt', 'Meta'].includes(event.key) || event.repeat) return
  const shortcut = diagramShortcutFromKey(event)
  if (shortcut) void save(shortcut)
  else error.value = t('diagram.shortcuts.invalid')
}

async function openDiagram() {
  try { await launcher?.open() }
  catch { error.value = t('diagram.shortcuts.launchError') }
}
</script>

<template>
  <section v-if="launcher" class="settings-section" data-testid="desktop-shortcut-settings">
    <div class="section-header">
      <div class="icon-circle"><PencilLine class="w-6 h-6" /></div>
      <div class="section-title-group">
        <h2>{{ t('diagram.shortcuts.title') }}</h2>
        <p>{{ t('diagram.shortcuts.description') }}</p>
      </div>
    </div>
    <div class="shortcut-row">
      <div class="shortcut-name">
        <strong>{{ t('diagram.title') }}</strong>
        <span v-if="state && !state.registered" role="status">{{ t('diagram.shortcuts.inactive') }}</span>
      </div>
      <kbd v-if="state" class="accelerator">{{ state.accelerator }}</kbd>
      <button ref="capture" type="button" class="btn-secondary" :aria-pressed="recording" :disabled="busy"
        @click="recording = true; error = ''; updated = false; capture?.focus()" @keydown="record" @blur="recording = false">
        {{ t(recording ? 'diagram.shortcuts.capture' : 'diagram.shortcuts.change') }}
      </button>
      <button type="button" class="btn-secondary" :disabled="busy || (state?.registered && state.accelerator === DEFAULT_DIAGRAM_SHORTCUT)"
        @click="save(DEFAULT_DIAGRAM_SHORTCUT)">{{ t('diagram.shortcuts.reset') }}</button>
    </div>
    <p v-if="error" class="error-banner mt-sm" role="alert">{{ error }}</p>
    <p v-else-if="updated" class="success-banner mt-sm" role="status">{{ t('diagram.shortcuts.saved') }}</p>
    <button type="button" class="btn-primary launch-diagram" @click="openDiagram">
      <ExternalLink :size="16" />{{ t('diagram.shortcuts.diagram') }}
    </button>
  </section>
</template>

<style scoped src="@/styles/settings/general.css"></style>
<style scoped>
.shortcut-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 16px 0; border-bottom: 1px solid var(--color-border-light, #e2e8f0); }
.shortcut-name { flex: 1; min-width: 110px; display: grid; gap: 4px; }
.shortcut-name span { color: #64748b; font-size: 12px; }
.accelerator { border: 1px solid #dbe4ef; border-radius: 6px; padding: 6px 9px; background: #f8fafc; color: #334155; white-space: nowrap; }
.launch-diagram { margin-top: 20px; }
</style>
