import type { DiagramTool } from './diagramModel'

export const diagramToolKeys = {
  select: 'v',
  pan: 'h',
  connect: 'c',
  sketch: 'p',
} as const satisfies Record<DiagramTool, string>

export const diagramCommandKeys = { open: 'o', export: 's', undo: 'z', redo: 'y' } as const
export const diagramDeleteKeys: readonly string[] = ['Delete', 'Backspace']
