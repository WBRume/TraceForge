export type AnnotationSource = {
  kind: 'message'
  messageId: string
  startOffset: number
  endOffset: number
} | {
  kind: 'diff'
  filePath: string
  side: 'original' | 'modified' | 'unified'
  version?: string
  revision?: string
  lineStart: number
  lineEnd: number
  startColumn?: number
  endColumn?: number
  selectionEndLine?: number
  oldLineStart?: number
  oldLineEnd?: number
}

export interface ContextAnnotation {
  id: string
  source: AnnotationSource
  selectedText: string
  comment: string
}

export type AnnotationSelection = Pick<ContextAnnotation, 'source' | 'selectedText'>

export function annotationLabel(source: AnnotationSource): string {
  if (source.kind === 'message') return '所选文本'
  const lines = source.lineStart === source.lineEnd ? `${source.lineStart}` : `${source.lineStart}–${source.lineEnd}`
  const side = source.side === 'original' ? '原版本' : source.side === 'modified' ? '新版本' : 'Diff'
  return `${source.filePath}:${lines} · ${source.version || side}`
}

function fenced(text: string): string {
  const longest = Math.max(2, ...Array.from(text.matchAll(/`+/g), match => match[0].length))
  const fence = '`'.repeat(longest + 1)
  return `${fence}\n${text}\n${fence}`
}

/** The captured quote is immutable evidence; line numbers may move after a later edit. */
export function formatAnnotationMessage(input: string, annotations: readonly ContextAnnotation[]): string {
  if (!annotations.length) return input.trim()
  const sections = annotations.map((item, index) => {
    const source = item.source
    const anchor = source.kind === 'message'
      ? `消息 ID：${source.messageId}\n文字位置：${source.startOffset}–${source.endOffset}（从 0 开始，结束位置不含）`
      : [`文件：${source.filePath}`, `版本：${source.version || source.side}（${source.side}）`,
        `行号：${source.lineStart}–${source.lineEnd}`,
        source.startColumn !== undefined ? `代码范围：${source.lineStart}:${source.startColumn}–${source.selectionEndLine || source.lineEnd}:${source.endColumn}（从 1 开始，结束位置不含）` : '',
        source.oldLineStart !== undefined ? `原版本行号：${source.oldLineStart}–${source.oldLineEnd}` : '',
        source.revision ? `内容版本：${source.revision}` : '',
      ].filter(Boolean).join('\n')
    const comment = item.comment.trim() ? `\n修改意见：${item.comment}` : ''
    return `### 批注 ${index + 1}\n${anchor}\n所选${source.kind === 'diff' ? '代码' : '文本'}：\n${fenced(item.selectedText)}${comment}`
  })
  return [input.trim(), '请根据以下批注处理对应内容；所选文本是引用上下文。若文件已变化，请结合引用定位。', ...sections].filter(Boolean).join('\n\n')
}
