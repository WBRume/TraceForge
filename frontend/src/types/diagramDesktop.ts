import type { DesktopSaveRequest, DesktopSaveResult } from './sddDesktop'
import type { DesktopWorkspaceWindowsApi } from './workspaceWindows'

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
  chrome?: 'overlay' | Pick<DesktopWorkspaceWindowsApi, 'control'>
  save(request: DesktopSaveRequest): Promise<DesktopSaveResult>
}

declare global {
  interface Window {
    sddDiagram?: DiagramWindowApi
  }
}
