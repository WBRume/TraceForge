/**
 * 成员稳定配色：creator_id 哈希到固定色板（首色为项目主色），
 * 气泡/头像/作者名用同一颜色区分多用户。
 */
const MEMBER_COLOR_PALETTE = ['#0284C7', '#7c3aed', '#db2777', '#ea580c', '#16a34a', '#0891b2', '#4f46e5', '#b45309']

export const memberColorFor = (userId: string | null | undefined): string => {
  const id = String(userId || '').trim()
  if (!id) return MEMBER_COLOR_PALETTE[0]
  let hash = 0
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0
  }
  return MEMBER_COLOR_PALETTE[hash % MEMBER_COLOR_PALETTE.length]
}

/** 成员色的半透明变体（避免 CSS color-mix 的兼容性差异） */
export const memberColorRgba = (userId: string | null | undefined, alpha: number): string => {
  const hex = memberColorFor(userId)
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

export const messageAuthorColor = (msg: any): string => (
  String(msg?.role || '').toLowerCase() === 'user'
    ? memberColorFor(msg?.creator_id)
    : '#0284C7'
)
