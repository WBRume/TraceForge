import type { indexDocxReview } from './docxReviewRanges'

export type DocxRevisionMarker = {
  id: string
  block_id: string
  region_id: string
  start: number
  end: number
}

export type DocxRevisionPoint = { id: string; top: number; left: number }

export function addDocxRevisionHighlights(
  frame: HTMLIFrameElement,
  content: HTMLElement,
  index: ReturnType<typeof indexDocxReview>,
  markers: DocxRevisionMarker[],
  names: Readonly<Record<string, string>>,
  { hover, open }: {
    hover: (point: DocxRevisionPoint | null) => void
    open: (point: DocxRevisionPoint) => void
  },
) {
  const document = content.ownerDocument
  const win = frame.contentWindow as (Window & typeof globalThis) | null
  const paragraphs = new Map(index.paragraphs.map(item => [item.edit?.id, item.marker.closest('p')]))
  const rangesById = new Map<string, Range[]>()
  const groups = new Map<string, HTMLElement>()
  const entriesByParagraph = new Map<string, string[]>()
  const highlightName = 'traceforge-revision'

  function point(id: string, bounds: DOMRect): DocxRevisionPoint {
    const outer = frame.getBoundingClientRect()
    return { id, left: outer.left + bounds.left, top: outer.top + bounds.bottom }
  }

  for (const marker of markers) {
    const paragraph = paragraphs.get(marker.region_id)
    if (!paragraph) continue
    let group = groups.get(marker.region_id)
    if (!group) {
      group = document.createElement('span')
      group.className = 'tf-revision-markers'
      paragraph.append(group)
      groups.set(marker.region_id, group)
    }
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'tf-revision-marker'
    button.dataset.docxRevision = marker.id
    button.textContent = '•'
    button.setAttribute('aria-label', names[marker.id] || marker.id)
    group.append(button)
    rangesById.set(marker.id, index.rangesForText(marker.block_id, marker.start, marker.end))
    const ids = entriesByParagraph.get(marker.region_id) ?? []
    ids.push(marker.id)
    entriesByParagraph.set(marker.region_id, ids)
  }
  if (win?.CSS.highlights && win.Highlight) {
    win.CSS.highlights.set(highlightName, new win.Highlight(...[...rangesById.values()].flat()))
  }

  function locate(event: MouseEvent): DocxRevisionPoint | null {
    const target = event.target as HTMLElement | null
    const button = target?.closest<HTMLElement>('[data-docx-revision]')
    if (button?.dataset.docxRevision) return point(button.dataset.docxRevision, button.getBoundingClientRect())
    const region = target?.closest<HTMLElement>('[data-review-paragraph]')?.dataset.reviewParagraph
    if (!region) return null
    for (const id of entriesByParagraph.get(region) ?? []) {
      for (const range of rangesById.get(id) ?? []) {
        for (const box of range.getClientRects()) {
          if (event.clientX >= box.left && event.clientX <= box.right
            && event.clientY >= box.top && event.clientY <= box.bottom) return point(id, box)
        }
      }
    }
    return null
  }
  const move = (event: MouseEvent) => hover(locate(event))
  const leave = () => hover(null)
  const click = (event: MouseEvent) => {
    const target = locate(event)
    if (target) open(target)
  }
  content.addEventListener('mousemove', move)
  content.addEventListener('mouseleave', leave)
  content.addEventListener('click', click)
  win?.addEventListener('scroll', leave)

  return () => {
    content.removeEventListener('mousemove', move)
    content.removeEventListener('mouseleave', leave)
    content.removeEventListener('click', click)
    win?.removeEventListener('scroll', leave)
    win?.CSS.highlights?.delete(highlightName)
    groups.forEach(group => group.remove())
    hover(null)
  }
}
