const types = {
  pdf: { engine: 'pdf', tone: 'red' },
  docx: { engine: 'word', tone: 'blue' },
  xlsx: { engine: 'sheet', tone: 'green' },
  pptx: { engine: 'slides', tone: 'orange' },
  html: { engine: 'html', tone: 'violet' },
  htm: { engine: 'html', tone: 'violet', label: 'HTML' },
  png: { engine: 'image', tone: 'violet' },
  jpg: { engine: 'image', tone: 'violet' },
  jpeg: { engine: 'image', tone: 'violet' },
  gif: { engine: 'image', tone: 'violet' },
  webp: { engine: 'image', tone: 'violet' },
  svg: { engine: 'image', tone: 'violet' },
  patch: { engine: 'patch', tone: 'sky', label: 'DIFF' },
  diff: { engine: 'patch', tone: 'sky' },
  md: { engine: 'code', tone: 'blue', report: true },
  markdown: { engine: 'code', tone: 'blue', label: 'MD', report: true },
  txt: { engine: 'code', tone: 'slate', report: true },
  csv: { engine: 'code', tone: 'green', report: true },
} as const

export type PreviewEngine = (typeof types)[keyof typeof types]['engine']

export function fileType(path: string): { engine: PreviewEngine; tone: string; label: string; report: boolean } {
  const extension = /\.([a-z0-9]+)$/i.exec(path)?.[1].toLowerCase() || ''
  const type = Object.hasOwn(types, extension) ? types[extension as keyof typeof types] : undefined
  const engine = type?.engine || 'code'
  const label = type && 'label' in type && typeof type.label === 'string'
    ? type.label
    : extension && extension.length <= 5 ? extension.toUpperCase() : 'FILE'
  return { engine, label, tone: type?.tone || 'slate', report: Boolean(type && ('report' in type || !['code', 'patch'].includes(engine))) }
}

export function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  return bytes < 1024 ** 2 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 ** 2).toFixed(1)} MB`
}
