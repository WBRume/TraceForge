<script setup lang="ts">
import { shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Settings2 } from '@/components/icons'
import api from '@/utils/api'
import CanvasCalendarSettingsDialog from './CanvasCalendarSettingsDialog.vue'
import { canvasUrl, type CanvasCalendar, type FiscalQuarter } from './model'

const props = defineProps<{ workspaceId: string; quarter: FiscalQuarter; busy: boolean; canEdit: boolean; revision: number }>()
const emit = defineEmits<{ select: [id: string]; calendarSaved: [current: string] }>()
const { t } = useI18n()
const calendar = shallowRef<CanvasCalendar>()
const opened = shallowRef(false)
const settingsOpen = shallowRef(false)
const year = shallowRef(props.quarter.year)
const reading = shallowRef(false)
const failed = shallowRef(false)
const calendarYear = shallowRef<number>()
let loadedRevision = -1

watch(() => props.quarter.year, value => { year.value = value })
watch([year, opened, settingsOpen, () => props.revision], async ([selected, menu, settings, revision], _, cleanup) => {
  reading.value = false
  failed.value = false
  if ((!menu && !settings) || !Number.isInteger(selected) || selected < 1000 || selected > 9997) return
  if (calendarYear.value === selected && loadedRevision === revision) return
  const request = new AbortController()
  cleanup(() => request.abort())
  reading.value = true
  failed.value = false
  try {
    const { data } = await api.get<CanvasCalendar>(`${canvasUrl(props.workspaceId)}/calendar`, {
      params: { year: selected }, signal: request.signal, timeout: 5000,
    })
    if (!request.signal.aborted) {
      calendar.value = data
      calendarYear.value = selected
      loadedRevision = revision
    }
  } catch {
    if (!request.signal.aborted) {
      failed.value = true
      if (settingsOpen.value) {
        settingsOpen.value = false
        ElMessage.error(t('workspace_canvas.load_failed'))
      }
    }
  } finally {
    if (!request.signal.aborted) reading.value = false
  }
}, { immediate: true })

const name = (quarter: FiscalQuarter) => t('workspace_canvas.quarter.name', { year: quarter.label_year, number: quarter.number })

function choose(id: string) {
  opened.value = false
  emit('select', id)
}

function move(delta: number) {
  const index = props.quarter.number - 1 + delta
  const nextYear = props.quarter.year + Math.floor(index / 4)
  if (nextYear >= 1000 && nextYear <= 9997) choose(`${nextYear}-Q${(index + 4) % 4 + 1}`)
}

function openPicker(value: boolean) {
  if (value) year.value = props.quarter.year
  opened.value = value
}

function openSettings() {
  opened.value = false
  year.value = props.quarter.year
  settingsOpen.value = true
}

function saved(data: CanvasCalendar) {
  calendar.value = data
  year.value = Number(data.current.slice(0, 4))
  calendarYear.value = year.value
  loadedRevision = props.revision
  settingsOpen.value = false
  emit('calendarSaved', data.current)
}
</script>

<template>
  <div class="quarter-picker" data-testid="canvas-quarter-picker">
    <div class="quarter-stepper">
      <button type="button" :disabled="busy || quarter.id === '1000-Q1'" :aria-label="t('workspace_canvas.quarter.previous')"
        :title="t('workspace_canvas.quarter.previous')" @click="move(-1)"><ChevronLeft :size="16" /></button>
      <el-popover :visible="opened" role="dialog" trigger="click" placement="bottom-start" :hide-after="0"
        :width="310" @update:visible="openPicker">
        <template #reference>
          <button type="button" class="quarter-current" :disabled="busy" :aria-label="t('workspace_canvas.quarter.select')"
            aria-haspopup="dialog" :aria-expanded="opened">
            <CalendarDays :size="17" /><strong>{{ name(quarter) }}</strong><ChevronDown :size="14" />
          </button>
        </template>
        <div class="quarter-menu" data-testid="canvas-quarter-menu">
          <label class="quarter-year"><span>{{ t('workspace_canvas.quarter.anchor_year') }}</span>
            <input v-model.number="year" type="number" min="1000" max="9997" />
          </label>
          <span v-if="reading" role="status">{{ t('common.loading') }}</span>
          <span v-else-if="failed" role="alert">{{ t('workspace_canvas.load_failed') }}</span>
          <template v-else-if="calendarYear === year">
            <button v-for="item in calendar?.quarters ?? []" :key="item.id" type="button" :data-quarter-option="item.id"
              :disabled="busy" :aria-current="item.id === quarter.id ? 'true' : undefined" @click="choose(item.id)">
              <strong>{{ name(item) }}</strong><small>{{ item.start }} — {{ item.end }}</small>
            </button>
          </template>
          <button v-if="calendar && calendar.current !== quarter.id" type="button" @click="choose(calendar.current)">
            {{ t('workspace_canvas.quarter.current') }}
          </button>
        </div>
      </el-popover>
      <button type="button" :disabled="busy || quarter.id === '9997-Q4'" :aria-label="t('workspace_canvas.quarter.next')"
        :title="t('workspace_canvas.quarter.next')" @click="move(1)"><ChevronRight :size="16" /></button>
    </div>
    <span class="quarter-dates">{{ quarter.start }} — {{ quarter.end }}</span>
    <button v-if="canEdit" type="button" class="quarter-settings" :aria-label="t('workspace_canvas.quarter.settings')"
      :title="t('workspace_canvas.quarter.settings')" :disabled="busy || (settingsOpen && reading)" @click="openSettings"><Settings2 :size="16" /></button>
    <CanvasCalendarSettingsDialog v-if="settingsOpen && calendar && calendarYear === year" :workspace-id="workspaceId"
      :calendar="calendar" @close="settingsOpen = false" @saved="saved" />
  </div>
</template>

<style scoped>
.quarter-picker, .quarter-stepper { display: inline-flex; align-items: center; gap: 6px; }
.quarter-picker { flex-wrap: wrap; max-width: 100%; }
.quarter-stepper { gap: 0; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; overflow: hidden; }
.quarter-picker button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; min-height: 34px;
  padding: 4px 8px; border: 0; background: #fff; color: #475569; font: inherit; font-size: 13px; cursor: pointer; }
.quarter-stepper button { min-height: 40px; }
.quarter-picker button:is(:hover, :focus-visible):not(:disabled) { background: #f0f9ff; color: #0369a1; }
.quarter-stepper button:focus-visible { outline: 2px solid #0ea5e9; outline-offset: -2px; }
.quarter-picker button:disabled { opacity: .5; cursor: default; }
.quarter-picker .quarter-current { padding: 4px 10px; border-inline: 1px solid #e2e8f0; white-space: nowrap; }
.quarter-dates { padding-inline: 3px; color: #64748b; font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.quarter-picker .quarter-settings { min-width: 42px; min-height: 42px; border: 1px solid #e2e8f0; border-radius: 8px; }
.quarter-menu { display: grid; gap: 5px; }
.quarter-menu button { display: flex; align-items: center; justify-content: space-between; gap: 5px; width: 100%;
  padding: 8px; border: 1px solid #e4edf6; border-radius: 7px; background: #fff; color: #294b67; font: inherit; cursor: pointer; }
.quarter-menu button:hover, .quarter-menu button[aria-current] { background: #eff7ff; }
.quarter-menu small { font-size: 11px; color: #64748b; }
.quarter-year { display: flex; align-items: center; justify-content: space-between; padding: 4px 4px 7px; }
.quarter-year input { width: 85px; padding: 4px 6px; border: 1px solid #d6e5f3; border-radius: 5px; font: inherit; }
</style>
