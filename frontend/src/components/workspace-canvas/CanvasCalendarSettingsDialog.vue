<script setup lang="ts">
import { computed, reactive, shallowRef, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseSelect from '@/components/BaseSelect.vue'
import { Plus, X } from '@/components/icons'
import api from '@/utils/api'
import { canvasUrl, type CanvasCalendar, type CanvasCalendarSettings } from './model'

const props = defineProps<{ workspaceId: string; calendar: CanvasCalendar }>()
const emit = defineEmits<{ close: []; saved: [calendar: CanvasCalendar] }>()
const { t } = useI18n()
const formId = useId()
const draft = reactive<CanvasCalendarSettings>(structuredClone(props.calendar.settings))
const saving = shallowRef(false)
const error = shallowRef('')
const overrideYear = shallowRef(props.calendar.quarters[0]?.year ?? Number(props.calendar.current.slice(0, 4)))
const timezoneSearch = shallowRef('')
const formats = ['months', '4-4-5', '4-5-4', '5-4-4'] as const
const weekdays = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
const timezones = ['UTC', 'Asia/Shanghai', 'Asia/Hong_Kong', 'America/New_York', 'Europe/London']
const formatOptions = computed(() => formats.map(value => ({ value, label: t(`workspace_canvas.quarter.formats.${value}`) })))
const monthOptions = computed(() => Array.from({ length: 12 }, (_, index) => ({
  value: index + 1, label: t('workspace_canvas.quarter.month_number', { month: index + 1 }),
})))
const yearLabelOptions = computed(() => [
  { value: 'start', label: t('workspace_canvas.quarter.label_start') },
  { value: 'end', label: t('workspace_canvas.quarter.label_end') },
])
const weekdayOptions = computed(() => weekdays.map((day, value) => ({ value, label: t(`workspace_canvas.quarter.weekdays.${day}`) })))
const weekEndRuleOptions = computed(() => [
  { value: 'nearest', label: t('workspace_canvas.quarter.nearest') },
  { value: 'last', label: t('workspace_canvas.quarter.last') },
])
const extraQuarterOptions = [1, 2, 3, 4].map(value => ({ value, label: `Q${value}` }))
const timezoneOptions = computed(() => {
  const search = timezoneSearch.value.trim().slice(0, 100)
  const keyword = search.toLowerCase()
  const options = [...new Set([...timezones, draft.timezone])].filter(zone => zone.toLowerCase().includes(keyword))
  if (search && !options.some(zone => zone.toLowerCase() === keyword)) options.unshift(search)
  return options.map(value => ({ value, label: value }))
})
const canAdd = computed(() => Number.isInteger(overrideYear.value) && overrideYear.value >= 1000
  && overrideYear.value <= 9997 && !draft.overrides.some(item => item.year === overrideYear.value))
const dayAfter = (value: string) => new Date(Date.parse(`${value}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10)

watch(draft, () => { error.value = '' })

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
  <el-dialog :model-value="true" class="canvas-dialog" :title="t('workspace_canvas.quarter.settings')" width="min(710px, 95vw)"
    :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" append-to-body @close="emit('close')">
    <form :id="formId" class="calendar-form" data-testid="canvas-calendar-settings" @submit.prevent="save">
      <div class="calendar-fields">
        <div class="calendar-field">
          <span>{{ t('workspace_canvas.quarter.format') }}</span>
          <BaseSelect v-model="draft.format" :options="formatOptions" :disabled="saving"
            :aria-label="t('workspace_canvas.quarter.format')" />
        </div>
        <div class="calendar-field">
          <span>{{ t('workspace_canvas.quarter.start_month') }}</span>
          <BaseSelect v-model="draft.start_month" :options="monthOptions" :disabled="saving"
            :aria-label="t('workspace_canvas.quarter.start_month')" />
        </div>
        <div class="calendar-field">
          <span>{{ t('workspace_canvas.quarter.timezone') }}</span>
          <BaseSelect v-model="draft.timezone" :options="timezoneOptions" :disabled="saving" searchable remote-search
            :aria-label="t('workspace_canvas.quarter.timezone')" :placeholder="draft.timezone"
            :search-placeholder="t('workspace_canvas.quarter.timezone')"
            @open="timezoneSearch = ''" @search="timezoneSearch = $event" />
        </div>
        <div class="calendar-field">
          <span>{{ t('workspace_canvas.quarter.year_label') }}</span>
          <BaseSelect v-model="draft.year_label" :options="yearLabelOptions" :disabled="saving"
            :aria-label="t('workspace_canvas.quarter.year_label')" />
        </div>
        <template v-if="draft.format !== 'months'">
          <div class="calendar-field">
            <span>{{ t('workspace_canvas.quarter.week_end') }}</span>
            <BaseSelect v-model="draft.week_end" :options="weekdayOptions" :disabled="saving"
              :aria-label="t('workspace_canvas.quarter.week_end')" />
          </div>
          <div class="calendar-field">
            <span>{{ t('workspace_canvas.quarter.week_end_rule') }}</span>
            <BaseSelect v-model="draft.week_end_rule" :options="weekEndRuleOptions" :disabled="saving"
              :aria-label="t('workspace_canvas.quarter.week_end_rule')" />
          </div>
          <div class="calendar-field">
            <span>{{ t('workspace_canvas.quarter.extra_week') }}</span>
            <BaseSelect v-model="draft.extra_week_quarter" :options="extraQuarterOptions" :disabled="saving"
              :aria-label="t('workspace_canvas.quarter.extra_week')" />
          </div>
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
    </form>
    <template #footer>
      <el-button :disabled="saving" @click="emit('close')">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" native-type="submit" :form="formId" :loading="saving">{{ t('common.save') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.calendar-form, .calendar-overrides { display: grid; gap: 14px; }
.calendar-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(215px, 1fr)); gap: 12px; }
.calendar-field, .calendar-form label { display: grid; gap: 5px; min-width: 0; color: #475569; font-size: 12px; }
.calendar-form label > input { box-sizing: border-box; min-height: 34px; min-width: 0; width: 100%;
  padding: 4px 8px; border: 1px solid #d9e4f0; border-radius: 7px; color: #183955; background: #fff; font: inherit; }
.override-heading, .override-card header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.override-heading .override-add { display: flex; align-items: center; }
.override-add input { width: 85px; }
.override-card { padding: 10px; border: 1px solid #e1ebf4; border-radius: 9px; background: #f8fbfe; }
.override-card header { margin-bottom: 8px; }
.override-card header button { display: inline-flex; border: 0; background: transparent; color: #64748b; cursor: pointer; }
.boundary-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 6px; }
.calendar-error { margin: 0; color: #a23a42; }
</style>
