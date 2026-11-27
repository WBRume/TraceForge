import { describe, expect, it } from 'vitest'
import { computeSpatialTheaterLayouts } from '../spatialTheaterLayout'

const STAGE_PERSPECTIVE = 1050

function projectScreen(x: number, y: number, z: number) {
  const scale = STAGE_PERSPECTIVE / (STAGE_PERSPECTIVE - z)
  return { sx: x * scale, sy: y * scale }
}

describe('computeSpatialTheaterLayouts', () => {
  const ids = ['task-alpha', 'task-beta', 'task-gamma', 'task-delta', 'task-epsilon']

  it('explodes background cards radially outward across X and Y without bunching behind center', () => {
    const first = computeSpatialTheaterLayouts({
      ids,
      activeIndex: 0,
      stageWidth: 1080,
      stageHeight: 520,
    })
    const second = computeSpatialTheaterLayouts({
      ids,
      activeIndex: 1,
      stageWidth: 1080,
      stageHeight: 520,
    })

    expect(first).toHaveLength(ids.length)
    expect(first[0].isFront).toBe(true)
    expect(first[0].zIndex).toBe(40)

    const bgProjected = first.slice(1).map(item => projectScreen(item.x, item.y, item.z))
    const xSpan = Math.max(...bgProjected.map(p => p.sx)) - Math.min(...bgProjected.map(p => p.sx))
    const ySpan = Math.max(...bgProjected.map(p => p.sy)) - Math.min(...bgProjected.map(p => p.sy))

    expect(xSpan).toBeGreaterThanOrEqual(420)
    expect(ySpan).toBeGreaterThanOrEqual(180)

    // No background card sits dead-center hidden behind the hero card
    for (const pt of bgProjected) {
      expect(Math.hypot(pt.sx, pt.sy)).toBeGreaterThanOrEqual(170)
    }

    // Switching focal card dynamically recomposes the burst
    expect(second[2].x).not.toBe(first[2].x)
    expect(second[2].y).not.toBe(first[2].y)
  })

  it('adapts burst bounds cleanly to narrower stages without NaN', () => {
    const compact = computeSpatialTheaterLayouts({
      ids: ['t1', 't2', 't3'],
      activeIndex: 0,
      stageWidth: 520,
      stageHeight: 420,
    })

    expect(compact).toHaveLength(3)
    for (const item of compact) {
      expect(Number.isFinite(item.x)).toBe(true)
      expect(Number.isFinite(item.y)).toBe(true)
      const pt = projectScreen(item.x, item.y, item.z)
      expect(Math.abs(pt.sx)).toBeLessThanOrEqual(220)
      expect(Math.abs(pt.sy)).toBeLessThanOrEqual(140)
    }
  })

  it('assigns a distinct front-to-back layer to every card at each carousel position', () => {
    const cards = Array.from({ length: 6 }, (_, index) => `theater-${index + 1}`)

    for (let activeIndex = 0; activeIndex < cards.length; activeIndex++) {
      const layout = computeSpatialTheaterLayouts({
        ids: cards,
        activeIndex,
        stageWidth: 1100,
        stageHeight: 618,
      })
      const byLayer = [...layout].sort((a, b) => a.zIndex - b.zIndex)
      const depths = byLayer.map(card => card.z)

      expect(new Set(layout.map(card => card.zIndex)).size).toBe(cards.length)
      expect(depths).toEqual([...depths].sort((a, b) => a - b))
      expect(byLayer.at(-1)).toBe(layout[activeIndex])
    }
  })
})
