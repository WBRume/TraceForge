<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import ExcelJS from 'exceljs'
import type { Workbook } from 'exceljs'
import PreviewPager from './PreviewPager.vue'
import { sheetGrid } from './spreadsheet'

const props = defineProps<{ bytes: ArrayBuffer }>()
const { t } = useI18n()
const book = shallowRef<Workbook>()
const sheetId = shallowRef<number>()
const rowPage = shallowRef(1)
const columnPage = shallowRef(1)
const failed = shallowRef(false)
const sheets = computed(() => book.value?.worksheets.filter(sheet => sheet.state === 'visible') || [])
const sheet = computed(() => sheets.value.find(sheet => sheet.id === sheetId.value))
const rowCount = 100
const columnCount = 24
const rowPages = computed(() => Math.ceil((sheet.value?.rowCount || 0) / rowCount))
const columnPages = computed(() => Math.ceil((sheet.value?.columnCount || 0) / columnCount))
const grid = computed(() => sheet.value && sheetGrid(
  sheet.value, (rowPage.value - 1) * rowCount + 1, (columnPage.value - 1) * columnCount + 1,
  rowCount, columnCount, Boolean(book.value?.properties.date1904),
))
const viewport = shallowRef<HTMLElement>()

watch(() => props.bytes, async (bytes, _, cleanup) => {
  let current = true
  cleanup(() => { current = false })
  book.value = undefined
  failed.value = false
  try {
    const workbook = new ExcelJS.Workbook()
    await workbook.xlsx.load(bytes)
    if (current) {
      book.value = workbook
      selectSheet(sheets.value[0]?.id)
    }
  } catch {
    if (current) failed.value = true
  }
}, { immediate: true })

function selectSheet(id?: number) {
  sheetId.value = id
  rowPage.value = 1
  columnPage.value = 1
}
watch([sheetId, rowPage, columnPage], () => viewport.value?.scrollTo(0, 0))
</script>

<template>
  <section class="sheet-preview">
    <p v-if="failed" class="sheet-state" role="alert">{{ t('file_preview.failed') }}</p>
    <p v-else-if="!book" class="sheet-state" role="status">{{ t('common.loading') }}</p>
    <template v-else>
      <div ref="viewport" class="sheet-viewport custom-scrollbar">
        <table v-if="grid?.columns.length && grid.rows.length" class="sheet-grid" :aria-label="sheet?.name">
          <colgroup><col style="width: 44px"><col v-for="column in grid.columns" :key="column.index" :style="{ width: column.width + 'px' }"></colgroup>
          <thead><tr><th scope="col"></th><th v-for="column in grid.columns" :key="column.index" scope="col">{{ column.label }}</th></tr></thead>
          <tbody>
            <tr v-for="row in grid.rows" :key="row.index" :style="{ height: row.height }">
              <th scope="row">{{ row.index }}</th>
              <td v-for="cell in row.cells" :key="cell.column" :style="cell.style" :colspan="cell.colspan" :rowspan="cell.rowspan" :title="cell.text">{{ cell.text }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="sheet-state">{{ t('file_preview.empty_sheet') }}</p>
      </div>
      <div class="sheet-controls">
        <nav class="sheet-tabs" :aria-label="t('file_preview.sheets')">
          <button v-for="tab in sheets" :key="tab.id" type="button" :aria-pressed="sheetId === tab.id" @click="selectSheet(tab.id)">{{ tab.name }}</button>
        </nav>
        <PreviewPager v-if="rowPages > 1" v-model="rowPage" :total="rowPages" :previous-label="t('file_preview.previous_rows')" :next-label="t('file_preview.next_rows')" />
        <PreviewPager v-if="columnPages > 1" v-model="columnPage" :total="columnPages" :previous-label="t('file_preview.previous_columns')" :next-label="t('file_preview.next_columns')" />
      </div>
    </template>
  </section>
</template>

<style scoped>
.sheet-preview { display: flex; flex: 1; flex-direction: column; min-width: 0; min-height: 0; background: #fff; }
.sheet-viewport { flex: 1; min-height: 0; overflow: auto; }
.sheet-grid { table-layout: fixed; width: max-content; border-collapse: separate; border-spacing: 0; font-size: 13px; color: #0f172a; }
.sheet-grid :is(th, td) { height: 27px; padding: 3px 8px; border-right: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0; box-sizing: border-box; }
.sheet-grid td { overflow: hidden; text-overflow: ellipsis; }
.sheet-grid th { color: #64748b; background: #f1f5f9; text-align: center; font-size: 11px; font-weight: 500; }
.sheet-grid thead { position: sticky; top: 0; z-index: 2; }
.sheet-grid tbody th { position: sticky; left: 0; z-index: 1; }
.sheet-state { padding: 16px; color: #64748b; text-align: center; font-size: 13px; }
.sheet-controls { display: flex; gap: 8px; align-items: center; padding: 5px 8px; border-top: 1px solid #e2e8f0; background: #f8fafc; color: #475569; font-size: 12px; }
.sheet-tabs { display: flex; flex: 1; min-width: 0; overflow: auto; gap: 4px; }
.sheet-tabs button { background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 5px 10px; color: #475569; cursor: pointer; white-space: nowrap; }
.sheet-tabs button[aria-pressed="true"] { border-color: #bae6fd; color: #0369a1; background: #f0f9ff; font-weight: 600; }
</style>
