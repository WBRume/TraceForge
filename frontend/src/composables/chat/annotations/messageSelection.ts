import type { AnnotationSelection } from './contextAnnotations'

export function readMessageSelection(root: HTMLElement, messageId: string): (AnnotationSelection & { x: number; y: number }) | null {
  const selection = window.getSelection()
  if (!messageId || !selection || selection.isCollapsed || !selection.rangeCount) return null
  const range = selection.getRangeAt(0)
  const content = root.querySelector('.msg-content')
  if (!content || !content.contains(range.startContainer) || !content.contains(range.endContainer)) return null
  const rangeText = range.toString()
  // Native selection retains visible line breaks between rendered Markdown nodes.
  const selectedText = content.classList.contains('message-markdown') ? selection.toString() : rangeText
  if (!selectedText.trim()) return null
  const prefix = range.cloneRange()
  prefix.selectNodeContents(content)
  prefix.setEnd(range.startContainer, range.startOffset)
  const startOffset = prefix.toString().length
  const rect = range.getBoundingClientRect()
  return {
    source: { kind: 'message', messageId, startOffset, endOffset: startOffset + rangeText.length },
    selectedText, x: rect.left, y: rect.bottom + 6,
  }
}
