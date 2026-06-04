export const normalizePathValue = (value: string) => String(value || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '').trim()

export const parentDirPath = (path: string) => {
  const normalized = normalizePathValue(path)
  const index = normalized.lastIndexOf('/')
  if (index <= 0) return ''
  return normalized.slice(0, index)
}

export const pathBaseName = (path: string) => {
  const normalized = normalizePathValue(path)
  const index = normalized.lastIndexOf('/')
  if (index < 0) return normalized
  return normalized.slice(index + 1)
}

export const pathStartsWithPrefix = (path: string, prefix: string) => (
  path === prefix || path.startsWith(`${prefix}/`)
)

export const rebasePathPrefix = (path: string, oldPrefix: string, newPrefix: string) => {
  if (path === oldPrefix) return newPrefix
  if (path.startsWith(`${oldPrefix}/`)) {
    return `${newPrefix}${path.slice(oldPrefix.length)}`
  }
  return path
}
