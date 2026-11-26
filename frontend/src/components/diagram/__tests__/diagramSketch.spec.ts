import { describe, expect, it } from 'vitest'
import type { Point } from '@/utils/canvasViewport'
import { edgeDrawing } from '../diagramGeometry'
import { blankDiagram, decodeDiagram, makeNode, type DiagramDocument } from '../diagramModel'
import { recognizeSketch } from '../diagramSketch'
import { applySketch as commitSketch, type SketchSession } from '../diagramSketchDocument'
import type { SketchStrokes } from '../diagramSketchGeometry'

const stroke = (...vertices: [number, number][]): Point[] => vertices.map(([x, y]) => ({ x, y }))
const rectangle = stroke([0, 10], [1, 0], [150, 2], [149, 90], [-2, 89], [0, 19])
const smallRectangle = stroke([32, 22], [99, 22], [100, 63], [32, 65], [32, 23])

function applySketch(doc: DiagramDocument, paths: SketchStrokes, unit: number, session?: SketchSession, pause = 550) {
  const startedAt = (session?.endedAt ?? 0) + pause
  return commitSketch(doc, paths, unit, { startedAt, endedAt: startedAt + 210 }, session)!
}

function drawPaths(paths: SketchStrokes) {
  let current = blankDiagram('Test')
  let session: SketchSession | undefined
  for (const path of paths) {
    const step = applySketch(current, [path], 1, session)
    current = step.next
    session = step.session
  }
  return { doc: current, session }
}

describe('freehand formatting', () => {
  it('closes slightly open rectangles consistently in screen space', () => {
    for (const unit of [.4, 1, 4]) {
      const scaled = rectangle.map(({ x, y }) => ({ x: x * unit, y: y * unit }))
      const result = recognizeSketch([scaled], unit)
      if (result?.kind !== 'outline') throw new Error('Expected an outline')
      expect(result.shape).toBe('rectangle')
      expect(Math.abs(result.width / unit - 152)).toBeLessThan(3)
      expect(Math.abs(result.height / unit - 90)).toBeLessThan(3)
    }
  })

  it('joins adjacent strokes into an outline', () => {
    const drawn = [
      stroke([0, 0], [120, 0]), stroke([119, 3], [120, 80]),
      stroke([118, 82], [0, 81]), stroke([3, 79], [0, 2]),
    ]
    expect(recognizeSketch(drawn, 1)).toMatchObject({ kind: 'outline', shape: 'rectangle' })
  })

  it('fits the corners of a crooked open diamond and triangles with bowed sides', () => {
    const diamond = stroke([62, 32], [34, 66], [35, 84], [118, 136], [147, 94], [182, 69], [46, 0])
    const downward = stroke([22, 15], [78, 68], [198, 128], [276, 23], [14, 2], [30, 15])
    const upward = stroke([72, 19], [0, 71], [182, 84], [109, 50], [65, 0])
    expect(recognizeSketch([diamond], 1)).toMatchObject({ shape: 'diamond' })
    expect(recognizeSketch([downward], 1)).toMatchObject({ shape: 'triangle', direction: 'down' })
    expect(recognizeSketch([upward], 1)).toMatchObject({ shape: 'triangle', direction: 'up' })
  })

  it('separates simple ovals and diamonds from irregular closed strokes', () => {
    const oval = Array.from({ length: 33 }, (_, index) => {
      const angle = index * Math.PI / 16
      return { x: 110 + 52 * Math.cos(angle), y: 65 + 29 * Math.sin(angle) }
    })
    const diamond = stroke([50, 0], [102, 38], [51, 81], [0, 42], [47, 2])
    const irregular = stroke([0, 0], [50, 30], [85, 0], [71, 81], [102, 42], [0, 0])
    expect(recognizeSketch([oval], 1)).toMatchObject({ shape: 'oval' })
    expect(recognizeSketch([diamond], 1)).toMatchObject({ shape: 'diamond' })
    expect(recognizeSketch([irregular], 1)).toBeUndefined()
  })

  it('recognizes a loop from two rough arcs and keeps a straight chord with one arc separate', () => {
    const top = stroke([112, 167], [121, 140], [133, 110], [146, 83], [162, 63], [180, 55], [201, 55],
      [228, 65], [263, 80], [297, 98], [323, 117], [345, 141], [367, 162])
    const bottom = stroke([100, 145], [111, 166], [129, 188], [156, 203], [189, 215], [229, 221],
      [267, 222], [299, 211], [325, 197], [348, 191], [365, 176], [378, 160])
    expect(drawPaths([top, bottom]).doc.nodes.map(node => node.shape)).toEqual(['oval'])
    const chord = stroke([48, 54], [502, 54])
    for (const samples of [15, 36]) {
      const arc = Array.from({ length: samples }, (_, index) => {
        const angle = Math.PI * (1 - index / (samples - 1))
        return { x: 280 + 200 * Math.cos(angle), y: 54 + 110 * Math.sin(angle) }
      })
      expect(drawPaths([chord, arc]).doc.nodes.map(node => node.shape)).toEqual(['line', 'ink'])
    }
  })

  it('preserves three long straight sides of a box with one rounded end', () => {
    const rounded = stroke([83,70], [177,70], [230,73], [286,77], [338,83], [374,89], [395,99],
      [397,118], [396,142], [392,163], [383,190], [370,213], [354,229], [334,239], [310,244],
      [245,244], [178,244], [117,249], [52,253], [60,212], [66,177], [70,140], [73,108], [72,81])
    const oval = Array.from({ length: 61 }, (_, i) => {
      const angle = i * Math.PI / 30
      return { x: 225 + 173 * Math.cos(angle), y: 148 + 92 * Math.sin(angle) }
    })
    expect(recognizeSketch([rounded], 1)).toMatchObject({ shape: 'rectangle' })
    expect(recognizeSketch([oval], 1)).toMatchObject({ shape: 'oval' })
    for (const [width, height] of [[20,20], [23,18], [32,22]]) {
      const small = oval.map(point => ({ x: (point.x - 225) * width / 346, y: (point.y - 148) * height / 184 }))
      expect(recognizeSketch([small], 1)).toMatchObject({ shape: 'oval' })
    }
  })

  it('keeps a missing-side contour open and recognizes the separately drawn fourth side', () => {
    const left = stroke([73,19], [73,75], [73,131])
    const contour = stroke([66,31], [74,27], [108,27], [145,27], [177,29], [204,32], [223,36],
      [232,42], [233,61], [232,83], [226,102], [215,126], [207,132], [194,135],
      [163,135], [134,133], [113,132], [98,130], [86,132])
    for (const zoom of [1, .55, .27]) {
      const unit = 1 / zoom
      const toWorld = (path: Point[]) => path.map(({ x, y }) => ({ x: x * unit, y: y * unit }))
      expect(recognizeSketch([toWorld(contour)], unit)).toBeUndefined()
      for (const paths of [[left, contour], [contour, left]]) {
        const first = applySketch(blankDiagram('Missing side'), [toWorld(paths[0])], unit)
        const completed = applySketch(first.next, [toWorld(paths[1])], unit, first.session)
        expect(completed.next.nodes.map(node => node.shape)).toEqual(['rectangle'])
        expect(completed.original?.nodes).toHaveLength(2)
      }
      const first = applySketch(blankDiagram('After a pause'), [toWorld(left)], unit)
      const second = applySketch(first.next, [toWorld(contour)], unit, first.session, 1850)
      expect(second.next.nodes.map(node => node.shape)).toEqual(['line', 'ink'])
    }
  })

  it('requires closure for a curved outline even when it covers most directions', () => {
    const almost = Array.from({ length: 50 }, (_, i) => {
      const angle = Math.PI * 1.72 * i / 49
      return { x: 120 + 95 * Math.sin(angle), y: 75 + 57 * Math.cos(angle) }
    })
    expect(recognizeSketch([almost], 1)).toBeUndefined()
  })

  it('recognizes tilted rectangles that close against a side instead of the starting point', () => {
    const extended = stroke([41,18], [37,51], [15,129], [17,141], [41,146], [145,153],
      [270,153], [319,147], [327,112], [329,60], [324,46], [316,41], [214,22], [59,4], [0,0])
    const retraced = stroke([0,33], [10,66], [10,128], [13,50], [8,7], [91,8], [158,1],
      [202,0], [218,5], [230,17], [223,78], [216,90], [207,98], [186,106], [150,113], [60,113], [36,116])
    for (const unit of [1, 1 / .75, 1 / .28]) {
      for (const path of [extended, retraced]) {
        for (const ordered of [path, [...path].reverse()]) {
          const scaled = ordered.map(({ x, y }) => ({ x: x * unit, y: y * unit }))
          expect(recognizeSketch([scaled], unit)).toMatchObject({ shape: 'rectangle' })
        }
      }
    }
  })

  it('straightens elbows and detects arrows drawn with one or two strokes', () => {
    const elbow = stroke([0, 100], [63, 101], [61, 42], [125, 40])
    expect(recognizeSketch([elbow], 1)).toMatchObject({
      kind: 'line', arrow: false, points: stroke([0, 100.5], [62, 100.5], [62, 41], [125, 41]),
    })
    const oneStroke = stroke([0, 85], [123, 85], [106, 74], [123, 85], [106, 96])
    const shaftDrawnBackwards = stroke([123, 85], [62, 84], [0, 85])
    const head = stroke([106, 74], [123, 85], [106, 96])
    for (const paths of [[oneStroke], [shaftDrawnBackwards, head]]) {
      expect(recognizeSketch(paths, 1)).toMatchObject({ kind: 'line', arrow: true, points: stroke([0, 85], [123, 85]) })
    }
  })

  it('finds direction in a wavy arrow drawn in a single stroke in either order', () => {
    const drawn = stroke([335,84], [355,84], [410,85], [517,87], [597,87], [633,91], [664,91], [682,89],
      [712,89], [701,80], [690,65], [712,89], [714,101], [686,109])
    for (const path of [drawn, [...drawn].reverse()]) {
      const found = recognizeSketch([path], 1)
      expect(found).toMatchObject({ kind: 'line', arrow: true })
      if (found?.kind !== 'line') throw new Error('Expected arrow')
      expect(found.traced[0].x).toBeLessThan(340)
      expect(found.traced.at(-1)?.x).toBeGreaterThan(700)
      expect(found.startArrow).toBeUndefined()
    }
  })

  it('detects both outward heads in one continuous stroke', () => {
    const drawn = stroke([22, 67], [0, 80], [74, 81], [130, 83], [205, 80], [186, 94])
    expect(recognizeSketch([drawn], 1)).toMatchObject({
      kind: 'line', arrow: true, startArrow: true, traced: stroke([0, 80], [205, 80]),
    })
  })
})

describe('editable sketch conversion', () => {
  it('completes recent open sides and keeps unrelated or restored strokes separate', () => {
    const left = stroke([37, 3], [40, 67], [27, 143])
    const topAndRight = stroke([30, 0], [272, 14], [233, 138])
    const bottom = stroke([0, 131], [229, 131])
    const partial = drawPaths([left, topAndRight])
    expect(partial.doc.nodes.every(node => node.shape === 'line' || node.shape === 'ink')).toBe(true)
    const { next, original } = applySketch(partial.doc, [bottom], 1, partial.session)
    expect(next.nodes.map(node => node.shape)).toEqual(['rectangle'])
    expect(next.nodes[0].width).toBeLessThan(255)
    expect(original?.nodes.slice(0, 2)).toEqual(partial.doc.nodes)
    const expired = applySketch(partial.doc, [bottom], 1, partial.session, 1850)
    const reopened = applySketch(decodeDiagram(JSON.stringify(partial.doc)), [bottom], 1)
    for (const step of [expired, reopened]) {
      expect(step.next.nodes).toHaveLength(3)
      expect(step.next.nodes[2].shape).toBe('line')
    }
  })

  it('keeps nearby handwriting and trims the overshoot of a small nested box', () => {
    const frame = stroke([0, 0], [235, 5], [237, 125], [0, 122], [1, 0])
    const handwriting = stroke([153, 27], [165, 43], [165, 22], [176, 28], [179, 55], [185, 43])
    const inner = [
      stroke([38, 29], [34, 59]),
      stroke([36, 25], [77, 31], [79, 65], [75, 67]),
      stroke([46, 61], [143, 73]),
    ]
    const { doc: next } = drawPaths([frame, handwriting, ...inner])
    expect(next.nodes.map(node => node.shape)).toEqual(['frame', 'ink', 'rectangle'])
    expect(next.nodes[2].width).toBeLessThan(52)
  })

  it('detects nested boxes in either order and keeps the pre-formatting ink', () => {
    for (const [first, second] of [[rectangle, smallRectangle], [smallRectangle, rectangle]]) {
      const existing = applySketch(blankDiagram('Test'), [first], 1)!.next
      const { next, original } = applySketch(existing, [second], 1)!
      expect(next.nodes.map(node => node.shape).sort()).toEqual(['frame', 'rectangle'])
      expect(original?.nodes.map(node => node.shape)).toEqual(['rectangle', 'ink'])
      expect(decodeDiagram(JSON.stringify(original)).nodes.at(-1)?.paths).toHaveLength(1)
    }
  })

  it('stores real edge endpoints and applies an arrowhead at the drawn end', () => {
    const a = { ...makeNode('rectangle', { x: 0, y: 30 }, ''), width: 100, height: 100 }
    const b = { ...makeNode('rectangle', { x: 250, y: 30 }, ''), width: 100, height: 100 }
    const doc = { ...blankDiagram('Test'), nodes: [a, b] }
    const line = applySketch(doc, [stroke([100, 64], [178, 65], [250, 64])], 1)!
    expect(line.next.edges[0]).toMatchObject({ source: a.id, target: b.id, relation: 'association' })
    const { next } = applySketch(line.next, [stroke([120, 54], [100, 64], [120, 74])], 1, line.session)
    const reopened = decodeDiagram(JSON.stringify(next))
    const [edge] = reopened.edges
    expect(edge).toMatchObject({ source: b.id, target: a.id, relation: 'flow' })
    const moved = { ...a, y: a.y + 24, height: 200 }
    expect(edgeDrawing(edge, b, moved).points.at(-1)).toEqual({ x: 100, y: 122 })
    expect(reopened.nodes).toHaveLength(2)
  })

  it('attaches rough strokes through frame borders without choosing an intervening child', () => {
    const a = { ...makeNode('frame', { x: 128, y: 96 }, ''), width: 361, height: 212 }
    const b = { ...makeNode('frame', { x: 689, y: 113 }, ''), width: 302, height: 200 }
    const child = { ...makeNode('rectangle', { x: 777, y: 165 }, ''), width: 138, height: 111 }
    const doc = { ...blankDiagram('Test'), nodes: [a, b, child] }
    const wavy = stroke([467, 120], [539, 125], [644, 117], [708, 129])
    const deep = stroke([442, 288], [784, 288])
    for (const path of [wavy, deep]) {
      const { next } = applySketch(doc, [path], 1)
      expect(next.nodes).toEqual(doc.nodes)
      expect(next.edges[0]).toMatchObject({ source: a.id, target: b.id,
        anchors: [{ side: 'right' }, { side: 'left' }] })
    }
    const shortShaft = applySketch(doc, [stroke([495, 236], [660, 236])], 1)
    expect(shortShaft.next.edges).toHaveLength(0)
    const arrowHead = stroke([639, 220], [687, 235], [679, 249], [647, 261])
    const arrow = applySketch(shortShaft.next, [arrowHead], 1, shortShaft.session)
    expect(arrow.next.nodes).toEqual(doc.nodes)
    expect(arrow.next.edges[0]).toMatchObject({ source: a.id, target: b.id, relation: 'flow' })
    const whenOld = applySketch(shortShaft.next, [arrowHead], 1, shortShaft.session, 2100)
    expect(whenOld.next.edges).toHaveLength(0)
    expect(whenOld.next.nodes[3].id).toBe(shortShaft.next.nodes[3].id)
  })

  it('keeps a closed box independent when an oval is drawn inside it', () => {
    const oval = Array.from({ length: 31 }, (_, i) => {
      const angle = Math.PI * i / 15
      return { x: 75 + 35 * Math.cos(angle), y: 44 + 20 * Math.sin(angle) }
    })
    const before = applySketch(blankDiagram('Test'), [rectangle], 1)
    const after = applySketch(before.next, [oval], 1, before.session)
    expect(after.next.nodes.map(node => node.shape)).toEqual(['rectangle', 'oval'])
    expect(after.next.nodes[0]).toEqual(before.next.nodes[0])
  })

  it('adds a second arrowhead to an already saved connection and preserves both ports', () => {
    const a = { ...makeNode('rectangle', { x: 0, y: 30 }, ''), width: 100, height: 100 }
    const b = { ...makeNode('rectangle', { x: 250, y: 30 }, ''), width: 100, height: 100 }
    const doc = { ...blankDiagram('Test'), nodes: [a, b] }
    const one = applySketch(doc, [stroke([100,64], [170,64], [250,64], [232,53], [250,64], [231,75])], 1)
    const original = one.next.edges[0]
    expect(original).toMatchObject({ source: a.id, target: b.id, relation: 'flow' })
    const restored = decodeDiagram(JSON.stringify(one.next))
    const two = applySketch(restored, [stroke([119,53], [100,64], [116,75])], 1)
    expect(two.next.nodes).toHaveLength(2)
    expect(two.next.edges).toEqual([{ ...restored.edges[0], relation: 'bidirectional' }])
    expect(decodeDiagram(JSON.stringify(two.next)).edges[0].relation).toBe('bidirectional')
  })

  it('recognizes a head drawn first and also accepts two separate wings', () => {
    const head = stroke([133,52], [152,65], [135,78])
    const shaft = stroke([152,65], [75,65], [0,65])
    const before = drawPaths([head, shaft]).doc
    expect(before.nodes.map(node => [node.shape, node.arrow])).toEqual([['line', true]])
    expect(before.nodes[0].paths?.[0]).toEqual([[0,0], [1,0]])

    const split = drawPaths([shaft, head.slice(0, 2), head.slice(1)]).doc
    expect(split.nodes.map(node => [node.shape, node.arrow])).toEqual([['line', true]])
    expect(split.nodes[0].paths?.[0]).toEqual([[0,0], [1,0]])
  })

  it('stores both arrowheads on a standalone line', () => {
    const path = stroke([20,48], [0,60], [190,60], [168,75])
    const first = applySketch(blankDiagram('Self-contained'), [path], 1)
    const restored = decodeDiagram(JSON.stringify(first.next))
    expect(restored.nodes[0]).toMatchObject({ shape: 'line', arrow: true, startArrow: true })
  })

  it('opens untouched ink and standalone arrows without requiring connector targets', () => {
    const initial = blankDiagram('Test')
    const raw = stroke([0, 0], [25, 30], [45, -12], [66, 45], [70, 21], [81, 35])
    const { next } = applySketch(initial, [raw], 1)!
    const arrow = stroke([0, 75], [150, 75], [128, 63], [150, 75], [128, 87])
    const result = applySketch(next, [arrow], 1)!
    const restored = decodeDiagram(JSON.stringify(result.next))
    expect(restored.nodes.map(node => [node.shape, node.arrow])).toEqual([['ink', undefined], ['line', true]])
    expect(restored.edges).toHaveLength(0)
    expect(restored.nodes[0].paths?.[0]).toHaveLength(raw.length)
    const invalid = { ...result.next, nodes: [{ ...restored.nodes[0], paths: [[[0, 0], [1.2, 0]]] }] }
    expect(() => decodeDiagram(JSON.stringify(invalid))).toThrow('Invalid drawing document')
  })
})
