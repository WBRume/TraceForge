/**
 * 工作区根目录路径工具：与后端 workspace_service 的路径策略保持一致。
 * - 工作区根目录配置存在时，创建工作区路径默认为 根目录/workspace/工作区名称；
 * - 且仅允许位于 根目录/workspace 之内。
 */

export const WORKSPACE_BASE_SEGMENT = 'workspace'

/** 将工作区名称转换为文件系统安全的目录名；无法转换时回退为 workspace。 */
export function slugifyWorkspaceDirName(name: string): string {
  const cleaned = String(name || '')
    .replace(/[\\/:*?"<>|\r\n\t]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^[-.\s]+|[-.\s]+$/g, '')
  return cleaned || 'workspace'
}

/** 以根目录自带的分隔符风格拼接路径（Windows 根目录用 \，其余用 /）。 */
export function joinWorkspacePath(...parts: string[]): string {
  const cleaned = parts.map((part) => String(part || '').trim()).filter(Boolean)
  if (cleaned.length === 0) return ''
  const separator = cleaned[0].includes('\\') ? '\\' : '/'
  return cleaned
    .map((part, index) =>
      index === 0 ? part.replace(/[\\/]+$/g, '') : part.replace(/^[\\/]+|[\\/]+$/g, '')
    )
    .join(separator)
}

/** 规范化路径段：拆分分隔符、消解 . 与 ..。 */
function normalizePathSegments(value: string): string[] {
  const segments: string[] = []
  for (const segment of String(value || '').split(/[\\/]+/)) {
    if (!segment || segment === '.') continue
    if (segment === '..') {
      segments.pop()
      continue
    }
    segments.push(segment)
  }
  return segments
}

/** 判断 path 是否位于 base 之内（允许等于 base）。Windows 风格路径按大小写不敏感比较。 */
export function isPathWithinBase(path: string, base: string): boolean {
  const normalize = (value: string) => {
    const segments = normalizePathSegments(value)
    const windowsLike = /^[a-zA-Z]:/.test(value) || value.startsWith('\\\\')
    const joined = segments.join('/')
    return windowsLike ? joined.toLowerCase() : joined
  }
  const baseNorm = normalize(base)
  if (!baseNorm) return true
  const pathNorm = normalize(path)
  if (!pathNorm) return false
  return pathNorm === baseNorm || pathNorm.startsWith(`${baseNorm}/`)
}
