export const normalizeRemoteUrl = (value: string | null | undefined): string => {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const sshMatch = raw.match(/^[^@/]+@([^:]+):(.+)$/)
  if (sshMatch?.[1] && sshMatch?.[2]) {
    return `${sshMatch[1].toLowerCase()}/${sshMatch[2]}`.replace(/\/+$/, '').replace(/\.git$/i, '')
  }
  try {
    const url = new URL(raw)
    return `${url.host.toLowerCase()}${url.pathname}`.replace(/\/+$/, '').replace(/\.git$/i, '')
  } catch {
    return raw.replace(/\.git$/i, '').replace(/\/+$/, '').toLowerCase()
  }
}

export const remoteUrlsMatch = (left: string | null | undefined, right: string | null | undefined): boolean => {
  const normalizedLeft = normalizeRemoteUrl(left)
  const normalizedRight = normalizeRemoteUrl(right)
  return Boolean(normalizedLeft && normalizedRight && normalizedLeft === normalizedRight)
}

export const createPatchBranchName = (taskId: string, patchSetNo: number): string =>
  `sdd/${taskId}/v${patchSetNo}`

export const createRepoPatchBranchName = (taskId: string, patchSetNo: number, repoSlug: string): string =>
  `sdd/${taskId}/v${patchSetNo}-${repoSlug}`

export const redactLog = (value: string): string =>
  String(value || '')
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer [REDACTED]')
    .replace(/(access_token|refresh_token|token|password|secret|api[_-]?key)\s*[:=]\s*["']?[^"'\s]+/gi, '$1=[REDACTED]')
    .replace(/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/g, '[REDACTED_JWT]')

export const excerptText = (value: string, maxLength = 12000): string => {
  const text = String(value || '')
  if (text.length <= maxLength) return text
  return text.slice(text.length - maxLength)
}
