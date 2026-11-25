import type { Component } from 'vue'
import {
  ArrowsPointingInIcon, BookMarked, ChevronRight, ClipboardList, FileText, Link, Maximize2,
  MessageSquare, PencilLine, Plus, Square, Trash2, Upload, Workflow,
} from '@/components/icons'
import type { Point, Size } from './model'

export type CanvasContextTarget = { type: 'surface' } | { type: 'node' | 'edge' | 'relation'; id: string }

export interface CanvasContextRequest {
  target: CanvasContextTarget
  anchor: Point
  position: Point
  size: Size
  restoreFocus: HTMLElement
}

export type CanvasMenuAction = 'new_requirement' | 'new_task' | 'new_case' | 'upload' | 'playbooks'
  | 'new_note' | 'new_frame' | 'fit' | 'open' | 'related' | 'properties' | 'delete'
  | 'edit_requirement' | 'child_requirement' | 'create_linked_task' | 'link_task' | 'link_requirement'
  | 'task_session' | 'task_documents' | 'share_document' | 'paragraphs' | 'promote_case'

export interface CanvasMenuItem {
  key: CanvasMenuAction
  label: string
  icon: Component
  divider?: boolean
  danger?: boolean
  disabled?: boolean
}

export const menuIcons: Record<CanvasMenuAction, Component> = {
  new_requirement: ClipboardList, new_task: MessageSquare, new_case: BookMarked, upload: Upload,
  playbooks: Workflow, new_note: PencilLine, new_frame: Square, fit: Maximize2, open: ChevronRight,
  related: ArrowsPointingInIcon, properties: Link, delete: Trash2, edit_requirement: PencilLine, child_requirement: Plus,
  create_linked_task: Plus, link_task: Link, link_requirement: Link, task_session: MessageSquare,
  task_documents: FileText, share_document: Link, paragraphs: FileText, promote_case: Workflow,
}
