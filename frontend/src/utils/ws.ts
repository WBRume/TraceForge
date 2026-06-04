import api from '@/utils/api'

export const buildBackendWsUrl = (
  path: string,
  query?: Record<string, string | number | boolean | null | undefined>,
): string => {
  const rawApiBase = String(api.defaults.baseURL || `${window.location.origin}/api`)
  const apiUrl = rawApiBase.startsWith('http')
    ? new URL(rawApiBase)
    : new URL(rawApiBase, window.location.origin)
  const wsProtocol = apiUrl.protocol === 'https:' ? 'wss:' : 'ws:'
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const url = new URL(`${wsProtocol}//${apiUrl.host}${normalizedPath}`)

  Object.entries(query || {}).forEach(([key, value]) => {
    if (value === null || value === undefined) return
    url.searchParams.set(key, String(value))
  })

  return url.toString()
}
