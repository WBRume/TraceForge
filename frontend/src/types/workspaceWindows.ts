export const MAIN_WORKSPACE_WINDOW = 'main'
export const WORKSPACE_HOME = '/workspaces'
export const WORKSPACE_TAB_LIMIT = 40

export interface WorkspaceTab {
  id: string
  path: string
  title?: string
}

export interface WorkspaceWindowState {
  id: string
  scope: string
  tabs: WorkspaceTab[]
  activeTabId: string
  revision: number
}

export interface WindowPoint { x: number; y: number }
export interface WindowRect extends WindowPoint { width: number; height: number }
export interface WindowPlacement extends WindowRect { maximized: boolean }

export interface TabStripBounds extends WindowRect {
  tabs: { id: string; midpoint: number }[]
}

export type TabDestination = { windowId: string; beforeTabId?: string } | { position?: WindowPoint }
export type WindowCommand =
  | { type: 'connect'; scope: string | null; path: string }
  | { type: 'navigate'; tabId: string; path: string }
  | { type: 'title'; tabId: string; path: string; title: string }
  | { type: 'open'; path: string }
  | { type: 'select' | 'close'; tabId: string }
  | { type: 'move'; tabId: string; destination: TabDestination }

export interface WorkspaceWindowUpdate {
  state: WorkspaceWindowState
  receivedTabId?: string
}

export interface DesktopWorkspaceWindowsApi {
  isPrimary: boolean
  command: (command: WindowCommand) => Promise<WorkspaceWindowState | null>
  setStrip: (strip: TabStripBounds | null) => Promise<void>
  drag: (tabId: string, phase: 'preview' | 'drop' | 'cancel') => Promise<TabDestination | null>
  moveWindow: (grab: WindowPoint) => Promise<void>
  control: (action: 'minimize' | 'maximize' | 'close') => Promise<void>
  onUpdate: (listener: (update: WorkspaceWindowUpdate) => void) => () => void
  onDropHint: (listener: (hint: { beforeTabId?: string } | null) => void) => () => void
}

export function isWorkspaceTabPath(path: unknown): path is string {
  return typeof path === 'string' && path.length <= 4096 && !/[\\\u0000-\u001f\u007f]/.test(path)
    && /^\/(workspaces|config|ops|knowledge|settings|provisioning)(?:[/?#]|$)/.test(path)
}
