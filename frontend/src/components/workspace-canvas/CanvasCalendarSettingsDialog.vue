<script setup lang="ts">
import { computed, reactive, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, X } from '@/components/icons'
import api from '@/utils/api'
import { canvasUrl, type CanvasCalendar, type CanvasCalendarSettings } from './model'

const props = defineProps<{ workspaceId: string; calendar: CanvasCalendar }>()
const emit = defineEmits<{ close: []; saved: [calendar: CanvasCalendar] }>()
const { t } = useI18n()
const draft = reactive<CanvasCalendarSettings>(structuredClone(props.calendar.settings))
const saving = shallowRef(false)
const error = shallowRef('')
const overrideYear = shallowRef(props.calendar.quarters[0]?.year ?? Number(props.calendar.current.slice(0, 4)))
const formats = ['months', '4-4-5', '4-5-4', '5-4-4'] as const
const weekdays = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
const canAdd = computed(() => Number.isInteger(overrideYear.value) && overrideYear.value >= 1000
  && overrideYear.value <= 9997 && !draft.overrides.some(item => item.year === overrideYear.value))
const dayAfter = (value: string) => new Date(Date.parse(`${value}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10)

function addOverride() {
  if (!canAdd.value) return
  const year = overrideYear.value
  const options = props.calendar.quarters.filter(quarter => quarter.year === year)
  const boundaries = options.length === 4 ? [...options.map(quarter => quarter.start), dayAfter(options[3]!.end)]
    : Array.from({ length: 5 }, (_, index) => new Date(Date.UTC(year, draft.start_month + index * 3 - 1, 1)).toISOString().slice(0, 10))
  draft.overrides.push({ year, boundaries })
  draft.overrides.sort((a, b) => a.year - b.year)
}

async function save() {
  if (saving.value) return
  error.value = ''
  saving.value = true
  try {
    const { data } = await api.put<CanvasCalendar>(`${canvasUrl(props.workspaceId)}/calendar`, draft, { timeout: 6000 })
    emit('saved', data)
  } catch (cause) {
    const detail = (cause as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
    const code = JSON.stringify(detail)?.match(/CANVAS_(INVALID_TIMEZONE|DUPLICATE_FISCAL_YEAR|INVALID_QUARTER_BOUNDARIES|DISCONTINUOUS_FISCAL_YEARS)/)?.[0]
    error.value = t(code ? `workspace_canvas.quarter.errors.${code}` : 'workspace_canvas.quarter.save_failed')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog :model-value="true" :title="t('workspace_canvas.quarter.settings')" width="min(710px, 95vw)"
    :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" append-to-body @close="emit('close')">
    <form class="calendar-form" data-testid="canvas-calendar-settings" @input="error = ''" @submit.prevent="save">
      <div class="calendar-fields">
        <label><span>{{ t('workspace_canvas.quarter.format') }}</span>
          <select v-model="draft.format">
            <option v-for="format in formats" :key="format" :value="format">{{ t(`workspace_canvas.quarter.formats.${format}`) }}</option>
          </select>
        </label>
        <label><span>{{ t('workspace_canvas.quarter.start_month') }}</span>
          <select v-model.number="draft.start_month">
            <option v-for="month in 12" :key="month" :value="month">{{ t('workspace_canvas.quarter.month_number', { month }) }}</option>
          </select>
        </label>
        <label><span>{{ t('workspace_canvas.quarter.timezone') }}</span>
          <input v-model.trim="draft.timezone" type="text" required maxlength="100" list="canvas-timezones" />
          <datalist id="canvas-timezones"><option value="UTC" /><option value="Asia/Shanghai" /><option value="Asia/Hong_Kong" />
            <option value="America/New_York" /><option value="Europe/London" /></datalist>
        </label>
        <label><span>{{ t('workspace_canvas.quarter.year_label') }}</span>
          <select v-model="draft.year_label"><option value="start">{{ t('workspace_canvas.quarter.label_start') }}</option>
            <option value="end">{{ t('workspace_canvas.quarter.label_end') }}</option></select>
        </label>
        <template v-if="draft.format !== 'months'">
          <label><span>{{ t('workspace_canvas.quarter.week_end') }}</span>
            <select v-model.number="draft.week_end"><option v-for="(day, index) in weekdays" :key="day" :value="index">
              {{ t(`workspace_canvas.quarter.weekdays.${day}`) }}</option></select>
          </label>
          <label><span>{{ t('workspace_canvas.quarter.week_end_rule') }}</span>
            <select v-model="draft.week_end_rule"><option value="nearest">{{ t('workspace_canvas.quarter.nearest') }}</option>
              <option value="last">{{ t('workspace_canvas.quarter.last') }}</option></select>
          </label>
          <label><span>{{ t('workspace_canvas.quarter.extra_week') }}</span>
            <select v-model.number="draft.extra_week_quarter"><option v-for="number in 4" :key="number" :value="number">Q{{ number }}</option></select>
          </label>
        </template>
      </div>
      <section class="calendar-overrides">
        <div class="override-heading">
          <strong>{{ t('workspace_canvas.quarter.custom_boundaries') }}</strong>
          <label class="override-add"><input v-model.number="overrideYear" type="number" min="1000" max="9997"
            :aria-label="t('workspace_canvas.quarter.anchor_year')" />
            <el-button :disabled="!canAdd || saving" @click="addOverride"><Plus :size="14" />{{ t('workspace_canvas.quarter.add_year') }}</el-button>
          </label>
        </div>
        <div v-for="(override, index) in draft.overrides" :key="override.year" class="override-card" :data-testid="`fiscal-override-${override.year}`">
          <header><strong>{{ t('workspace_canvas.quarter.anchor_year_value', { year: override.year }) }}</strong>
            <button type="button" :aria-label="t('workspace_canvas.quarter.remove_override')" :disabled="saving"
              @click="draft.overrides.splice(index, 1)"><X :size="17" /></button></header>
          <div class="boundary-fields">
            <label v-for="(_, boundary) in override.boundaries" :key="boundary">
              <span>{{ boundary === 4 ? t('workspace_canvas.quarter.next_year_start') : t('workspace_canvas.quarter.boundary', { number: boundary + 1 }) }}</span>
              <input v-model="override.boundaries[boundary]" type="date" required />
            </label>
          </div>
        </div>
      </section>
      <p v-if="error" role="alert" class="calendar-error">{{ error }}</p>
      <footer>
        <el-button :disabled="saving" @click="emit('close')">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" native-type="submit" :loading="saving">{{ t('common.save') }}</el-button>
      </footer>
    </form>
  </el-dialog>
</template>

<style scoped>
.calendar-form, .calendar-overrides { display: grid; gap: 14px; }
.calendar-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(215px, 1fr)); gap: 12px; }
.calendar-form label { display: grid; gap: 5px; min-width: 0; color: #475569; font-size: 12px; }
.calendar-form :is(input, select) { box-sizing: border-box; min-height: 34px; min-width: 0; width: 100%;
  padding: 4px 8px; border: 1px solid #d9e4f0; border-radius: 7px; color: #183955; background: #fff; font: inherit; }
.override-heading, .override-card header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.override-heading .override-add { display: flex; align-items: center; }
.override-add input { width: 85px; }
.override-card { padding: 10px; border: 1px solid #e1ebf4; border-radius: 9px; background: #f8fbfe; }
.override-card header { margin-bottom: 8px; }
.override-card header button { display: inline-flex; border: 0; background: transparent; color: #64748b; cursor: pointer; }
.boundary-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 6px; }
.calendar-error { margin: 0; color: #a23a42; }
.calendar-form footer { display: flex; justify-content: flex-end; }
</style>
