export const TASK_FLOAT_ROUTE = '/task-float'

export type FloatPoint = { x: number; y: number }
export type FloatSize = { width: number; height: number }

export type PanelDrag =
  | { type: 'start' }
  | { type: 'move' | 'end'; position: FloatPoint | null }

export interface TaskFloatPrepareRequest {
  id: string
  workspaceId: string
  taskId: string
  title: string
  size: FloatSize
}

export interface TaskFloatPlacement {
  id: string
  position: FloatPoint | null
  dropped: boolean
}

export interface DesktopFloatDrag {
  grab: FloatPoint
  dropped: boolean
}

export interface TaskFloatClosed {
  id: string
  action: 'closed' | 'dismissed' | 'returned'
  position?: FloatPoint
}

export interface DesktopTaskFloatsApi {
  prepare: (request: TaskFloatPrepareRequest) => Promise<void>
  place: (request: TaskFloatPlacement) => Promise<void>
  close: (id: string) => Promise<void>
  onClosed: (listener: (event: TaskFloatClosed) => void) => () => void
}

export interface TaskFloatWindowApi {
  close: () => Promise<void>
  returnToClient: () => Promise<void>
  drag?: (request: DesktopFloatDrag) => Promise<void>
}

declare global {
  interface Window {
    sddTaskFloat?: TaskFloatWindowApi
  }
}
