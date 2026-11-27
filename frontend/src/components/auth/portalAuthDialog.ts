import type { InjectionKey } from 'vue'

export type PortalAuthMode = 'login' | 'register'

export const openDesktopAuthDialogKey: InjectionKey<(mode: PortalAuthMode) => void> = Symbol('open-desktop-auth-dialog')
