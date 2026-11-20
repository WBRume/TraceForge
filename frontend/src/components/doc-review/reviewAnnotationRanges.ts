import type { AssetThreadMarker } from '@/composables/asset-discussion/types'

export type ReviewAnnotation = { marker: AssetThreadMarker; ranges: Range[] }
export type ReviewAnnotationGroup = { entries: ReviewAnnotation[]; threadIds: string[] }
export type ReviewAnnotationTarget = {
  threadIds: string[]
  left: number
  top: number
  multipleAnchors?: boolean
  trigger?: HTMLElement
  frame?: HTMLIFrameElement
}

export function groupByReviewAuthor<T extends { creator_id: string; created_at: string }>(items: readonly T[]) {
  const byAuthor = new Map<string, T[]>()
  for (const item of [...items].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at))) {
    const authored = byAuthor.get(item.creator_id)
    if (authored) authored.push(item)
    else byAuthor.set(item.creator_id, [item])
  }
  return [...byAuthor.values()]
}

export function groupReviewAnnotations(annotations: ReviewAnnotation[]): ReviewAnnotationGroup[] {
  const ordered = annotations.filter(entry => entry.ranges.length).sort((a, b) =>
    a.ranges[0]!.compareBoundaryPoints(Range.START_TO_START, b.ranges[0]!),
  )
  const groups: ReviewAnnotationGroup[] = []
  let group: ReviewAnnotationGroup | undefined
  let end: Range | undefined
  for (const entry of ordered) {
    const first = entry.ranges[0]!
    const last = entry.ranges.at(-1)!
    // A quote can span several text nodes. Join intersecting quotes, keeping adjacent quotes independent.
    if (!group || !end || first.compareBoundaryPoints(Range.END_TO_START, end) >= 0) {
      group = { entries: [], threadIds: [] }
      groups.push(group)
      end = last
    } else if (last.compareBoundaryPoints(Range.END_TO_END, end) > 0) {
      end = last
    }
    group.entries.push(entry)
    group.threadIds.push(entry.marker.thread_id)
  }
  return groups
}

export function reviewThreadIdsAt(entries: ReviewAnnotation[], event: MouseEvent) {
  const { clientX, clientY } = event
  return entries.filter(({ ranges }) => ranges.some(range =>
    Array.from(range.getClientRects()).some(rect =>
      rect.width > 0 && rect.height > 0
      && clientX >= rect.left && clientX < rect.right && clientY >= rect.top && clientY < rect.bottom,
    ),
  )).map(({ marker }) => marker.thread_id)
}
