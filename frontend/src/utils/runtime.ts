import type { SddDesktopApi } from '@/types/sddDesktop'

export const isElectron = (): boolean =>
  typeof window !== 'undefined' && Boolean(window.sddDesktop)

export const getSddDesktop = (): SddDesktopApi | null => {
  if (!isElectron()) return null
  return window.sddDesktop ?? null
}
