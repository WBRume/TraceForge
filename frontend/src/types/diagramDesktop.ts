import type { DesktopSaveRequest, DesktopSaveResult } from './sddDesktop'

export interface DiagramShortcutState {
  accelerator: string
  registered: boolean
}

export interface DiagramLauncher {
  open(): Promise<void>
  shortcut(): Promise<DiagramShortcutState>
  setShortcut(accelerator: string): Promise<DiagramShortcutState>
}

export interface DiagramWindowApi {
  save(request: DesktopSaveRequest): Promise<DesktopSaveResult>
}

declare global {
  interface Window {
    sddDiagram?: DiagramWindowApi
  }
}
