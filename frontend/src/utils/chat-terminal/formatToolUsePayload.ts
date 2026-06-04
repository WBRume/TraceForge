export interface ToolUseField {
  key: string
  label: string
  value: string
  multiline: boolean
  monospace: boolean
}

export interface ToolUseReadablePayload {
  fields: ToolUseField[]
  raw: string
}

const KEY_LABEL_MAP: Record<string, string> = {
  command: 'Command',
  description: 'Description',
  file_path: 'File',
  path: 'Path',
  pattern: 'Pattern',
  output_mode: 'Output',
  skill: 'Skill',
  query: 'Query',
  topn: 'TopN',
  limit: 'Limit',
  page: 'Page',
  page_size: 'PageSize',
  repo: 'Repo',
  repository_name: 'Repository',
}

const KEY_ORDER = [
  'command',
  'description',
  'file_path',
  'path',
  'pattern',
  'output_mode',
  'skill',
  'query',
  'repo',
  'repository_name',
  'limit',
  'topn',
  'page',
  'page_size',
]

const MONOSPACE_KEYS = new Set(['command', 'file_path', 'path', 'pattern', 'query', 'repo', 'repository_name'])
const MULTILINE_KEYS = new Set(['command', 'description'])
const MAX_VALUE_LENGTH = 320

const toRecord = (input: unknown): Record<string, unknown> | null => {
  if (input && typeof input === 'object' && !Array.isArray(input)) {
    return input as Record<string, unknown>
  }
  if (typeof input === 'string') {
    const text = input.trim()
    if (!text) return null
    try {
      const parsed = JSON.parse(text)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      // Keep string as fallback below.
    }
    return { value: text }
  }
  return null
}

const humanizeKey = (key: string): string => {
  if (KEY_LABEL_MAP[key]) return KEY_LABEL_MAP[key]
  return key
    .split('_')
    .filter(Boolean)
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(' ')
}

const stringifyValue = (value: unknown): string => {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    if (value.length === 0) return '[]'
    const allPrimitive = value.every((item) => ['string', 'number', 'boolean'].includes(typeof item))
    if (allPrimitive) return value.map((item) => String(item)).join(', ')
    return `${value.length} items`
  }
  if (typeof value === 'object') {
    const keys = Object.keys(value as Record<string, unknown>)
    if (keys.length === 0) return '{}'
    return `${keys.length} fields`
  }
  return String(value)
}

const truncateValue = (value: string): string => {
  if (value.length <= MAX_VALUE_LENGTH) return value
  return `${value.slice(0, MAX_VALUE_LENGTH)}...`
}

export const formatToolUsePayload = (
  input: unknown,
  formatToolInput: (value: unknown) => string,
): ToolUseReadablePayload => {
  const record = toRecord(input)
  const raw = formatToolInput(input)

  if (!record) {
    return {
      fields: raw
        ? [{
          key: 'raw',
          label: 'Input',
          value: truncateValue(raw),
          multiline: true,
          monospace: true,
        }]
        : [],
      raw,
    }
  }

  const keys = Object.keys(record)
  const ordered = [
    ...KEY_ORDER.filter((key) => keys.includes(key)),
    ...keys.filter((key) => !KEY_ORDER.includes(key)),
  ]

  const fields: ToolUseField[] = []
  for (const key of ordered) {
    const rawValue = record[key]
    const text = truncateValue(stringifyValue(rawValue))
    if (!text) continue
    fields.push({
      key,
      label: humanizeKey(key),
      value: text,
      multiline: MULTILINE_KEYS.has(key) || text.includes('\n'),
      monospace: MONOSPACE_KEYS.has(key),
    })
  }

  return { fields, raw }
}

