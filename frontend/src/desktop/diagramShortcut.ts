export const DEFAULT_DIAGRAM_SHORTCUT = 'Ctrl+Alt+D'

const modifiers = ['Ctrl', 'Alt', 'Shift', 'Super'] as const
const keys = /^(?:[A-Z0-9]|F(?:[1-9]|1[0-2]))$/

export function normalizeDiagramShortcut(input: unknown) {
  if (typeof input !== 'string' || input.length > 35) return null
  const parts = input.split('+')
  const key = parts.pop()
  if (!key || !keys.test(key) || !parts.some(part => part === 'Ctrl' || part === 'Alt' || part === 'Super')) return null
  const ordered = modifiers.filter(modifier => parts.includes(modifier))
  return ordered.length === parts.length ? [...ordered, key].join('+') : null
}

export function diagramShortcutFromKey(event: KeyboardEvent) {
  const key = /^(?:Key|Digit)([A-Z0-9])$/.exec(event.code)?.[1] ?? event.code
  return normalizeDiagramShortcut([
    event.ctrlKey && 'Ctrl', event.altKey && 'Alt', event.shiftKey && 'Shift', event.metaKey && 'Super', key,
  ].filter(Boolean).join('+'))
}
