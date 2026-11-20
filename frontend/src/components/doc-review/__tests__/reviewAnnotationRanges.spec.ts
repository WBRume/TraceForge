import { expect, it } from 'vitest'
import { groupReviewAnnotations, reviewThreadIdsAt, type ReviewAnnotation } from '../reviewAnnotationRanges'

function span(node: Node, start: number, end: number) {
  const range = document.createRange()
  range.setStart(node, start)
  range.setEnd(node, end)
  return range
}

function thread(id: string, ranges: Range[]): ReviewAnnotation {
  return {
    marker: {
      thread_id: id, block_id: 'source-text', status: 'open', creator_id: id,
      created_at: '2026-11-20T01:00:00Z', message_count: 1,
    },
    ranges,
  }
}

it('groups identical and overlapping reviews across formatted runs while keeping adjacent and repeated quotes separate', () => {
  const body = document.createElement('div')
  body.innerHTML = '<p><b>审计</b><em>策略</em>要求</p><p>审计策略</p>'
  const first = body.querySelector('b')!.firstChild!
  const second = body.querySelector('em')!.firstChild!
  const adjacent = body.firstChild!.lastChild!
  const later = body.lastChild!.firstChild!
  const quote = [span(first, 0, 2), span(second, 0, 2)]

  const groups = groupReviewAnnotations([
    thread('adjacent', [span(adjacent, 0, 2)]),
    thread('partially-overlapping', [span(first, 1, 2)]),
    thread('review-1', quote),
    thread('review-2', quote),
    thread('repeated-quote', [span(later, 0, 4)]),
  ])

  expect(groups.map(group => group.threadIds)).toEqual([
    ['review-1', 'review-2', 'partially-overlapping'],
    ['adjacent'],
    ['repeated-quote'],
  ])
})

it('finds all discussions at the click point within partially overlapping highlights', () => {
  const text = document.createTextNode('审计策略')
  const first = Object.assign(span(text, 0, 3), { getClientRects: () => [new DOMRect(0, 0, 30, 12)] })
  const second = Object.assign(span(text, 2, 4), { getClientRects: () => [new DOMRect(20, 0, 20, 12)] })
  const entries = [thread('review-1', [first]), thread('review-2', [second])]

  expect(reviewThreadIdsAt(entries, new MouseEvent('click', { clientX: 24, clientY: 6 })))
    .toEqual(['review-1', 'review-2'])
  expect(reviewThreadIdsAt(entries, new MouseEvent('click', { clientX: 32, clientY: 6 })))
    .toEqual(['review-2'])
})
