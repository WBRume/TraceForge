import type { AnnotationSelection } from './contextAnnotations'

export interface ParsedDiffLine {
  text: string
  type: 'plain' | 'add' | 'del' | 'hunk' | 'header' | 'file'
  filePath: string | null
  oldLine?: number
  newLine?: number
}

function gitPath(value: string): string {
  let path = value.trim()
  if (path.startsWith('"')) {
    path = path.replace(/(?:\\[0-7]{3})+/g, escaped => {
      const bytes = escaped.match(/\\([0-7]{3})/g)!.map(byte => parseInt(byte.slice(1), 8))
      return JSON.stringify(new TextDecoder().decode(new Uint8Array(bytes))).slice(1, -1)
    })
    try { path = JSON.parse(path) } catch { /* Keep an unfamiliar quoted path intact. */ }
  }
  return path.replace(/^[ab]\//, '')
}

export function parseUnifiedDiff(text: string): ParsedDiffLine[] {
  let filePath: string | null = null
  let oldLine = 0, newLine = 0, inHunk = false
  return text.split('\n').map(raw => {
    const line = raw.replace(/\r$/, '')
    const item: ParsedDiffLine = { text: line, type: 'plain', filePath }
    const hunk = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/)
    if (line.startsWith('diff --git ')) {
      inHunk = false
      const paths = line.slice(11).match(/^("(?:\\.|[^"])*"|a\/.+) ("(?:\\.|[^"])*"|b\/.+)$/)
      filePath = paths ? gitPath(paths[2]!) : null
      item.type = 'header'
    } else if (hunk) {
      oldLine = Number(hunk[1]); newLine = Number(hunk[2]); inHunk = true; item.type = 'hunk'
    } else if (inHunk && /^[ +\-]/.test(line)) {
      if (line[0] !== '+') item.oldLine = oldLine++
      if (line[0] !== '-') item.newLine = newLine++
      item.type = line[0] === '+' ? 'add' : line[0] === '-' ? 'del' : 'plain'
    } else if (line.startsWith('--- ') || line.startsWith('+++ ')) {
      item.type = 'file'
      const path = gitPath(line.slice(4))
      if (path !== '/dev/null') filePath = path
    } else if (line.startsWith('index ') || /^(new file|deleted file|old mode|new mode|rename |similarity )/.test(line)) {
      item.type = 'header'
    }
    item.filePath = filePath
    return item
  })
}

export function unifiedDiffSelection(lines: ParsedDiffLine[]): AnnotationSelection | null {
  const code = lines.filter(line => line.oldLine !== undefined || line.newLine !== undefined)
  const filePath = code[0]?.filePath
  if (!filePath || !code.length || code.some(line => line.filePath !== filePath)) return null
  const old = code.flatMap(line => line.oldLine === undefined ? [] : [line.oldLine])
  const modified = code.flatMap(line => line.newLine === undefined ? [] : [line.newLine])
  const deleted = code.some(line => line.type === 'del')
  const added = code.some(line => line.type === 'add')
  const mixed = deleted && added
  const original = deleted && !added
  const numbers = original ? old : modified
  return {
    source: { kind: 'diff', filePath, side: mixed ? 'unified' : original ? 'original' : 'modified',
      lineStart: numbers[0]!, lineEnd: numbers[numbers.length - 1]!,
      ...(mixed ? { oldLineStart: old[0], oldLineEnd: old[old.length - 1] } : {}),
    },
    selectedText: code.map(line => mixed ? line.text : line.text.slice(1)).join('\n'),
  }
}
