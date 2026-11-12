import type { Cell, Color, Worksheet } from 'exceljs'
import { format } from 'ssf'
import type { CSSProperties } from 'vue'

export const columnLabel = (index: number): string =>
  index > 26 ? columnLabel(Math.floor((index - 1) / 26)) + columnLabel((index - 1) % 26 + 1) : String.fromCharCode(64 + index)

function color(value?: Partial<Color>) {
  return value?.argb && /^[0-9a-f]{8}$/i.test(value.argb) ? `#${value.argb.slice(2)}` : undefined
}

function cellText(cell: Cell, date1904: boolean) {
  const value = cell.formula ? cell.result : cell.value
  if ((typeof value === 'number' || value instanceof Date) && cell.numFmt) {
    try { return format(cell.numFmt, value, { date1904 }) }
    catch { return cell.text }
  }
  return cell.text
}

function cellStyle(cell: Cell): CSSProperties {
  const { font, alignment, fill } = cell
  const horizontal = alignment?.horizontal
  const textAlign = horizontal === 'centerContinuous' ? 'center' : horizontal === 'distributed' || horizontal === 'fill' ? undefined : horizontal
  return {
    color: color(font?.color),
    fontFamily: font?.name,
    fontSize: font?.size ? `${Math.min(font.size, 72)}pt` : undefined,
    fontWeight: font?.bold ? 'bold' : undefined,
    fontStyle: font?.italic ? 'italic' : undefined,
    textDecoration: font?.underline ? 'underline' : font?.strike ? 'line-through' : undefined,
    backgroundColor: fill?.type === 'pattern' && fill.pattern === 'solid' ? color(fill.fgColor) : undefined,
    whiteSpace: alignment?.wrapText ? 'pre-wrap' : 'pre',
    textAlign: textAlign || (typeof cell.value === 'number' ? 'right' : undefined),
    verticalAlign: alignment?.vertical === 'middle' || alignment?.vertical === 'bottom' ? alignment.vertical : 'top',
  }
}

function cellPosition(address: string) {
  const [, letters = '', digits = '1'] = /^([A-Z]+)(\d+)$/.exec(address) || []
  return {
    column: [...letters].reduce((number, letter) => number * 26 + letter.charCodeAt(0) - 64, 0),
    row: Number(digits),
  }
}

export function sheetGrid(sheet: Worksheet, firstRow: number, firstColumn: number, rows: number, columns: number, date1904: boolean) {
  const lastRow = Math.min(sheet.rowCount, firstRow + rows - 1)
  const lastColumn = Math.min(sheet.columnCount, firstColumn + columns - 1)
  const merges = new Map<string, { row: number; column: number; colspan: number; rowspan: number } | null>()
  for (const range of sheet.model.merges) {
    const [from, to] = range.split(':').map(cellPosition)
    const top = Math.max(firstRow, from.row), bottom = Math.min(lastRow, to.row)
    const left = Math.max(firstColumn, from.column), right = Math.min(lastColumn, to.column)
    for (let row = top; row <= bottom; row++) {
      for (let column = left; column <= right; column++) {
        const entry = row === top && column === left
          ? { ...from, colspan: right - left + 1, rowspan: bottom - top + 1 }
          : null
        merges.set(`${row}:${column}`, entry)
      }
    }
  }
  const visibleColumns = Array.from({ length: Math.max(0, lastColumn - firstColumn + 1) }, (_, offset) => {
    const index = firstColumn + offset
    const column = sheet.getColumn(index)
    return { index, label: columnLabel(index), width: Math.min(600, Math.max(54, (column.width || 12) * 7 + 8)) }
  })
  const visibleRows = Array.from({ length: Math.max(0, lastRow - firstRow + 1) }, (_, offset) => {
    const index = firstRow + offset
    const row = sheet.getRow(index)
    const cells = visibleColumns.flatMap(({ index: column }) => {
      const merge = merges.get(`${index}:${column}`)
      if (merge === null) return []
      const cell = merge ? sheet.getCell(merge.row, merge.column) : row.getCell(column)
      return [{ column, text: cellText(cell, date1904), style: cellStyle(cell), colspan: merge?.colspan, rowspan: merge?.rowspan }]
    })
    return { index, cells, height: row.height ? `${row.height}pt` : undefined }
  })
  return { columns: visibleColumns, rows: visibleRows }
}
