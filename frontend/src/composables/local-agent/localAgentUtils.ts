export const normalizeRemoteUrl = (value: string | null | undefined): string => {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const sshMatch = raw.match(/^git@([^:]+):(.+)$/)
  if (sshMatch?.[1] && sshMatch?.[2]) {
    return `${sshMatch[1]}/${sshMatch[2]}`.replace(/\.git$/i, '').toLowerCase()
  }
  try {
    const url = new URL(raw)
    return `${url.host}${url.pathname}`.replace(/\.git$/i, '').replace(/\/+$/, '').toLowerCase()
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
