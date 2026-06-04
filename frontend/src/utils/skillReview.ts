export const REVIEWER_COLOR_PALETTE = [
  '#0ea5e9',
  '#3b82f6',
  '#14b8a6',
  '#10b981',
  '#f59e0b',
  '#f97316',
  '#ef4444',
  '#ec4899',
  '#8b5cf6',
  '#6366f1',
  '#06b6d4',
  '#84cc16',
] as const

export const hashToInt = (seed: string) => {
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) {
    hash = ((hash << 5) - hash + seed.charCodeAt(i)) | 0
  }
  return Math.abs(hash)
}

export const reviewerColorIndex = (expertUserId: string) => (
  hashToInt(expertUserId) % REVIEWER_COLOR_PALETTE.length
)

export const reviewerColor = (expertUserId: string) => (
  REVIEWER_COLOR_PALETTE[reviewerColorIndex(expertUserId)]
)
