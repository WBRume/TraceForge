import type { SddDesktopApi } from '@/types/sddDesktop'

export const isDesktop = (): boolean =>
  typeof window !== 'undefined' && Boolean(window.sddDesktop)

export const isElectron = (): boolean => isDesktop() && window.sddDesktop?.runtime !== 'tauri'
export const isTauri = (): boolean => isDesktop() && window.sddDesktop?.runtime === 'tauri'

export const getSddDesktop = (): SddDesktopApi | null => {
  if (!isDesktop()) return null
  return window.sddDesktop ?? null
}
