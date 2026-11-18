import JSZip from 'jszip'

const wordNamespace = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
const documentPart = 'word/document.xml'

export interface ReviewBlock {
  id: string
  type: string
  text: string
  docx_spans?: Array<{ paragraph: number; start: number; end: number }>
}

export interface DocxParagraphAnchor {
  startMark: string
  endMark: string
  block: ReviewBlock
  start: number
  end: number
  noteMarks: [start: string, end: string][]
}

function preserveSectionBreaks(body: Element) {
  const xml = body.ownerDocument
  const sections = Array.from(body.getElementsByTagNameNS(wordNamespace, 'sectPr'))
    .filter(section => section.parentElement?.localName === 'pPr' || section.parentElement === body)
  for (const [index, section] of sections.slice(0, -1).entries()) {
    const paragraph = section.parentElement?.parentElement
    if (paragraph?.localName !== 'p') continue
    const nextSection = sections[index + 1]
    const kind = nextSection.getElementsByTagNameNS(wordNamespace, 'type')[0]
      ?.getAttributeNS(wordNamespace, 'val')
    if (kind === 'continuous' || kind === 'nextColumn') continue
    const breaks = Array.from(paragraph.getElementsByTagNameNS(wordNamespace, 'br'))
    if (breaks.some(node => node.getAttributeNS(wordNamespace, 'type') === 'page')) continue

    const run = xml.createElementNS(wordNamespace, 'w:r')
    const pageBreak = xml.createElementNS(wordNamespace, 'w:br')
    pageBreak.setAttributeNS(wordNamespace, 'w:type', 'page')
    run.append(pageBreak)
    paragraph.append(run)
  }
}

export async function prepareDocxReview(bytes: ArrayBuffer, blocks: ReviewBlock[]) {
  const archive = await JSZip.loadAsync(bytes)
  const part = archive.file(documentPart)
  if (!part) throw new Error('DOCX has no document part')
  const xml = new DOMParser().parseFromString(await part.async('string'), 'application/xml')
  const body = xml.getElementsByTagNameNS(wordNamespace, 'body')[0]
  if (!body) throw new Error('DOCX has no document body')

  const paragraphs = Array.from(body.getElementsByTagNameNS(wordNamespace, 'p'))
  const prefix = `tf${crypto.getRandomValues(new Uint32Array(2)).join('_')}`
  const anchors: DocxParagraphAnchor[] = []
  let nextId = Array.from(xml.getElementsByTagNameNS(wordNamespace, 'bookmarkStart'))
    .reduce((maximum, mark) => Math.max(maximum, Number(mark.getAttributeNS(wordNamespace, 'id')) || 0), 0)

  const makeBookmark = (name: string) => {
    const id = String(++nextId)
    const start = xml.createElementNS(wordNamespace, 'w:bookmarkStart')
    start.setAttributeNS(wordNamespace, 'w:name', name)
    start.setAttributeNS(wordNamespace, 'w:id', id)
    const end = xml.createElementNS(wordNamespace, 'w:bookmarkEnd')
    end.setAttributeNS(wordNamespace, 'w:id', id)
    return [start, end] as const
  }

  for (const block of blocks) {
    for (const span of block.docx_spans ?? []) {
      const paragraph = paragraphs[span.paragraph]
      if (!paragraph) throw new Error('DOCX review positions do not match the version file')
      const startMark = `${prefix}_${span.paragraph}_s`
      const endMark = `${prefix}_${span.paragraph}_e`
      const noteMarks: DocxParagraphAnchor['noteMarks'] = []
      for (const run of Array.from(paragraph.children)) {
        if (run.namespaceURI !== wordNamespace || run.localName !== 'r') continue
        const children = Array.from(run.children).filter(child => child.localName !== 'rPr')
        if (!children.length || !children.every(child => ['footnoteReference', 'endnoteReference'].includes(child.localName))) continue
        const noteMark = `${prefix}_n${nextId}`
        const before = `${noteMark}_s`
        const after = `${noteMark}_e`
        run.before(...makeBookmark(before))
        run.after(...makeBookmark(after))
        noteMarks.push([before, after])
      }
      const first = paragraph.firstElementChild
      const insertBefore = first?.localName === 'pPr' ? first.nextSibling : first
      for (const marker of makeBookmark(startMark)) paragraph.insertBefore(marker, insertBefore)
      paragraph.append(...makeBookmark(endMark))
      anchors.push({ startMark, endMark, block, start: span.start, end: span.end, noteMarks })
    }
  }

  // Preserve the stored display result of simple fields and render Word's carriage returns.
  for (const field of Array.from(body.getElementsByTagNameNS(wordNamespace, 'fldSimple'))) {
    field.replaceWith(...Array.from(field.childNodes))
  }
  for (const lineBreak of Array.from(body.getElementsByTagNameNS(wordNamespace, 'cr'))) {
    lineBreak.replaceWith(xml.createElementNS(wordNamespace, 'w:br'))
  }
  preserveSectionBreaks(body)
  archive.file(documentPart, new XMLSerializer().serializeToString(xml))
  return { bytes: await archive.generateAsync({ type: 'arraybuffer', compression: 'DEFLATE' }), anchors }
}
