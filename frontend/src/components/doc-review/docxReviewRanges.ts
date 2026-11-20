import type { DocxParagraphAnchor, DocxParagraphEdit, ReviewBlock } from './docxReviewSource'

type TextRange = { node: Text; start: number; end: number; block: ReviewBlock }
type WordParagraph = { block: ReviewBlock; marker: HTMLElement; hasTextRange: boolean; edit?: DocxParagraphEdit }
type RenderedPiece = { node: Text | null; value: string; optional?: boolean }

function renderedParagraphPieces(paragraph: HTMLElement, noteMarks: Map<string, boolean>): RenderedPiece[] {
  const pieces: RenderedPiece[] = []
  const walker = paragraph.ownerDocument.createTreeWalker(paragraph, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT)
  let inNoteReference = false
  while (walker.nextNode()) {
    const node = walker.currentNode
    const element = node.nodeType === Node.TEXT_NODE ? node.parentElement : node as Element
    if (element?.closest('p') !== paragraph || element.closest('math, svg, style')) continue
    const boundary = noteMarks.get(element.id)
    if (boundary !== undefined) inNoteReference = boundary
    if (inNoteReference) continue
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node as Text
      if (text.data) pieces.push({ node: text, value: text.data })
    } else if (element.localName === 'br') {
      pieces.push({ node: null, value: '\n' })
    } else if (element.localName === 'wbr') {
      pieces.push({ node: null, value: '-' })
    }
  }
  return pieces
}

function mapParagraphs(paragraphs: HTMLElement[], anchor: DocxParagraphAnchor, characters: string[]) {
  const ranges: TextRange[] = []
  const noteMarks = new Map<string, boolean>()
  for (const [start, end] of anchor.noteMarks) {
    noteMarks.set(start, true)
    noteMarks.set(end, false)
  }
  let offset = anchor.start
  for (const [index, paragraph] of paragraphs.entries()) {
    const pieces = renderedParagraphPieces(paragraph, noteMarks)
    if (index) pieces.unshift({ node: null, value: '\n', optional: true })
    for (const piece of pieces) {
      const value = piece.value === '\u2003' && characters[offset] === '\t' ? '\t' : piece.value
      const length = Array.from(value).length
      if (characters.slice(offset, offset + length).join('') !== value) {
        if (piece.optional) continue
        return null
      }
      if (piece.node) ranges.push({ node: piece.node, start: offset, end: offset + length, block: anchor.block })
      offset += length
    }
  }
  return offset === anchor.end ? ranges : null
}

function nodeOffset(range: TextRange, character: number) {
  return Array.from(range.node.data).slice(0, character - range.start).join('').length
}

export function indexDocxReview(content: HTMLElement, anchors: DocxParagraphAnchor[]) {
  const document = content.ownerDocument
  const elements = Array.from(content.querySelectorAll<HTMLElement>('section.docx > article p'))
  const paragraphIndices = new Map(elements.map((element, index) => [element, index]))
  const markerElements = new Map(Array.from(content.querySelectorAll<HTMLElement>('span[id]'), node => [node.id, node]))
  const indexedText = new Map<Text, TextRange>()
  const blockRanges = new Map<string, TextRange[]>()
  const paragraphs: WordParagraph[] = []
  const blockCharacters = new Map<string, string[]>()

  for (const anchor of anchors) {
    const marker = markerElements.get(anchor.startMark)
    const start = marker?.closest('p')
    const end = markerElements.get(anchor.endMark)?.closest('p')
    // Word preview retains the continuation cells of vertical merges as hidden elements.
    if (!marker || !start || !end || start.closest('td[style*="display: none"]')) continue
    const first = paragraphIndices.get(start)
    const last = paragraphIndices.get(end)
    if (first === undefined || last === undefined || last < first) continue

    const { block } = anchor
    const characters = blockCharacters.get(block.id) ?? Array.from(block.text)
    blockCharacters.set(block.id, characters)
    const fragments = elements.slice(first, last + 1)
    const ranges = mapParagraphs(fragments, anchor, characters)
    if (anchor.edit) {
      for (const paragraph of fragments) paragraph.dataset.reviewParagraph = anchor.edit.id
    }
    if (anchor.edit || ranges?.length) {
      paragraphs.push({ block, marker, hasTextRange: Boolean(ranges?.length), edit: anchor.edit })
    }
    if (!ranges?.length) continue

    fragments.forEach(paragraph => { paragraph.dataset.reviewBlock = block.id })
    for (const range of ranges) indexedText.set(range.node, range)
    const current = blockRanges.get(block.id) ?? []
    current.push(...ranges)
    blockRanges.set(block.id, current)
  }

  function endpoint(selection: Range, isStart: boolean) {
    const container = isStart ? selection.startContainer : selection.endContainer
    const offset = isStart ? selection.startOffset : selection.endOffset
    const direct = indexedText.get(container as Text)
    if (direct) {
      return { block: direct.block, offset: direct.start + Array.from(direct.node.data.slice(0, offset)).length }
    }
    const element = container.nodeType === Node.ELEMENT_NODE ? container as Element : null
    const blockId = element?.closest<HTMLElement>('[data-review-block]')?.dataset.reviewBlock
    if (!blockId) return null
    const intersected = (blockRanges.get(blockId) ?? []).filter(piece => selection.intersectsNode(piece.node))
    const piece = isStart ? intersected[0] : intersected.at(-1)
    return piece ? { block: piece.block, offset: isStart ? piece.start : piece.end } : null
  }

  function selectedText(selection: Range) {
    const first = endpoint(selection, true)
    const last = endpoint(selection, false)
    if (!first || !last || first.block !== last.block || last.offset <= first.offset) return null
    const characters = blockCharacters.get(first.block.id)!
    let start = first.offset
    let end = last.offset
    while (start < end && !characters[start]?.trim()) start++
    while (end > start && !characters[end - 1]?.trim()) end--
    if (start === end) return null
    return {
      block_id: first.block.id,
      selected_text: characters.slice(start, end).join(''),
      char_start: start,
      char_end: end,
    }
  }

  function rangesForText(blockId: string, start?: number | null, end?: number | null, quote?: string | null) {
    const pieces = blockRanges.get(blockId)
    if (!pieces?.length) return []
    const characters = blockCharacters.get(blockId)!
    let first = start ?? 0
    let last = end ?? characters.length
    if (start == null && end == null && quote) {
      const text = pieces[0]!.block.text
      const offset = text.indexOf(quote)
      if (offset < 0 || text.indexOf(quote, offset + 1) >= 0) return []
      first = Array.from(text.slice(0, offset)).length
      last = first + Array.from(quote).length
    }
    if (first < 0 || last <= first || last > characters.length) return []
    if (quote && characters.slice(first, last).join('').trim() !== quote.trim()) return []
    return pieces.flatMap(piece => {
      const from = Math.max(first, piece.start)
      const to = Math.min(last, piece.end)
      if (to <= from) return []
      const range = document.createRange()
      range.setStart(piece.node, nodeOffset(piece, from))
      range.setEnd(piece.node, nodeOffset(piece, to))
      return [range]
    })
  }

  return { selectedText, rangesForText, paragraphs }
}
