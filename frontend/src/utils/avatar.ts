type AvatarTemplateStyle = 'classic' | 'soft' | 'split'

const HEX_COLOR_PATTERN = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/

const PALETTES: Array<[string, string, string]> = [
  ['#0ea5e9', '#2563eb', '#ffffff'],
  ['#14b8a6', '#0f766e', '#ffffff'],
  ['#22c55e', '#16a34a', '#ffffff'],
  ['#f59e0b', '#f97316', '#ffffff'],
  ['#ef4444', '#dc2626', '#ffffff'],
  ['#8b5cf6', '#6366f1', '#ffffff'],
  ['#06b6d4', '#0284c7', '#ffffff'],
  ['#ec4899', '#db2777', '#ffffff'],
]

const normalizeHexColor = (value: string, fallback = '#0ea5e9') => {
  const trimmed = value.trim()
  if (!HEX_COLOR_PATTERN.test(trimmed)) return fallback
  if (trimmed.length === 4) {
    return `#${trimmed[1]}${trimmed[1]}${trimmed[2]}${trimmed[2]}${trimmed[3]}${trimmed[3]}`.toLowerCase()
  }
  return trimmed.toLowerCase()
}

const escapeXml = (value: string) => (
  value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll('\'', '&apos;')
)

const hashToPaletteIndex = (seed: string) => {
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) {
    hash = ((hash << 5) - hash + seed.charCodeAt(i)) | 0
  }
  return Math.abs(hash) % PALETTES.length
}

const pickInitial = (displayName?: string | null, email?: string | null, userId?: string | null) => {
  const seed = displayName?.trim() || email?.trim() || userId?.trim() || '?'
  return seed.slice(0, 1).toLocaleUpperCase()
}

type BuildAvatarSvgInput = {
  displayName?: string | null
  email?: string | null
  userId?: string | null
  color?: string
  style?: AvatarTemplateStyle
}

export const buildAvatarSvg = ({
  displayName = '',
  email = '',
  userId = '',
  color = '',
  style = 'classic',
}: BuildAvatarSvgInput): string => {
  const initial = escapeXml(pickInitial(displayName, email, userId))
  const normalizedColor = normalizeHexColor(color || '#0ea5e9')
  const seed = `${displayName}|${email}|${userId}`
  const [fallbackStart, fallbackEnd, textColor] = PALETTES[hashToPaletteIndex(seed)]
  const startColor = color ? normalizedColor : fallbackStart
  const endColor = color ? '#0f172a' : fallbackEnd

  if (style === 'soft') {
    return (
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-hidden="true">`
      + `<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">`
      + `<stop offset="0%" stop-color="${startColor}" stop-opacity="0.92"/>`
      + `<stop offset="100%" stop-color="${endColor}" stop-opacity="0.86"/>`
      + `</linearGradient></defs>`
      + `<rect x="2" y="2" width="60" height="60" rx="30" fill="url(#bg)"/>`
      + `<circle cx="32" cy="32" r="27" fill="#ffffff" fill-opacity="0.12"/>`
      + `<text x="32" y="34" text-anchor="middle" dominant-baseline="middle" fill="${textColor}" font-size="28" font-family="'Segoe UI', 'PingFang SC', sans-serif" font-weight="700">${initial}</text>`
      + `</svg>`
    )
  }

  if (style === 'split') {
    return (
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-hidden="true">`
      + `<rect x="0" y="0" width="32" height="64" fill="${startColor}"/>`
      + `<rect x="32" y="0" width="32" height="64" fill="${endColor}"/>`
      + `<circle cx="32" cy="32" r="29" fill="#ffffff" fill-opacity="0.16"/>`
      + `<text x="32" y="34" text-anchor="middle" dominant-baseline="middle" fill="${textColor}" font-size="28" font-family="'Segoe UI', 'PingFang SC', sans-serif" font-weight="700">${initial}</text>`
      + `</svg>`
    )
  }

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-hidden="true">`
    + `<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">`
    + `<stop offset="0%" stop-color="${startColor}"/>`
    + `<stop offset="100%" stop-color="${endColor}"/>`
    + `</linearGradient></defs>`
    + `<rect x="0" y="0" width="64" height="64" rx="32" fill="url(#bg)"/>`
    + `<circle cx="32" cy="32" r="28" fill="#ffffff" fill-opacity="0.1"/>`
    + `<text x="32" y="34" text-anchor="middle" dominant-baseline="middle" fill="${textColor}" font-size="28" font-family="'Segoe UI', 'PingFang SC', sans-serif" font-weight="700">${initial}</text>`
    + `</svg>`
  )
}

export const isSvgText = (value: string) => /<\s*svg[\s>]/i.test(value)

export type { AvatarTemplateStyle }
