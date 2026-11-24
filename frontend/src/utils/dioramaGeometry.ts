export interface Point2D {
  x: number
  y: number
}

export interface ProjectedPoint extends Point2D {
  depth: number
}

export interface RectBox {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface SquarifyInput<T> {
  ref: T
  weight: number
}

export interface SquarifyRect<T> {
  ref: T
  x: number
  y: number
  w: number
  h: number
}

export interface PrismStyle {
  top: string
  left?: string
  right?: string
  sideGradient?: boolean
  leftGrad?: [string, string]
  rightGrad?: [string, string]
  stroke: string
  topStroke?: string
  lineWidth?: number
  topLineWidth?: number
  floorLines?: string | null
  shadowColor?: string
  dashed?: boolean
}

export interface PrismGeometryResult {
  hull: Point2D[]
  minX: number
  maxX: number
  minY: number
  maxY: number
  roofCenter: Point2D
}

export function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v
}

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

export function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace('#', '')
  const n = Number.parseInt(clean, 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

export function mixRgb(hexA: string, hexB: string, t: number, alpha?: number): string {
  const a = hexToRgb(hexA)
  const b = hexToRgb(hexB)
  const r = Math.round(lerp(a[0], b[0], t))
  const g = Math.round(lerp(a[1], b[1], t))
  const bl = Math.round(lerp(a[2], b[2], t))
  return alpha !== undefined ? `rgba(${r}, ${g}, ${bl}, ${alpha})` : `rgb(${r}, ${g}, ${bl})`
}

export function roundRectPath(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
): void {
  const rr = Math.min(r, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + rr, y)
  ctx.arcTo(x + w, y, x + w, y + h, rr)
  ctx.arcTo(x + w, y + h, x, y + h, rr)
  ctx.arcTo(x, y + h, x, y, rr)
  ctx.arcTo(x, y, x + w, y, rr)
  ctx.closePath()
}

export function pointInPoly(px: number, py: number, pts: Point2D[]): boolean {
  let inside = false
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const xi = pts[i].x
    const yi = pts[i].y
    const xj = pts[j].x
    const yj = pts[j].y
    const hit = ((yi > py) !== (yj > py)) && (px < ((xj - xi) * (py - yi)) / (yj - yi + 1e-9) + xi)
    if (hit) inside = !inside
  }
  return inside
}

/** Pure Bruls-Huizing-van Wijk squarified layout for balanced isometric building footprints. */
export function squarifyBlocks<T>(
  items: SquarifyInput<T>[],
  x: number,
  y: number,
  w: number,
  h: number,
): SquarifyRect<T>[] {
  const res: SquarifyRect<T>[] = []
  if (!items.length || w <= 0 || h <= 0) return res
  const total = items.reduce((sum, it) => sum + Math.max(0, it.weight), 0)
  if (total <= 0) return res

  const areaTotal = w * h
  const scaled = items
    .slice()
    .sort((a, b) => b.weight - a.weight)
    .map(it => ({ ref: it.ref, area: (Math.max(0, it.weight) / total) * areaTotal }))

  let rx = x
  let ry = y
  let rw = w
  let rh = h
  let idx = 0

  const worst = (row: Array<{ ref: T; area: number }>, side: number): number => {
    if (!row.length || side <= 0) return Number.POSITIVE_INFINITY
    let sum = 0
    let maxA = 0
    let minA = Number.POSITIVE_INFINITY
    for (const r of row) {
      sum += r.area
      if (r.area > maxA) maxA = r.area
      if (r.area < minA) minA = r.area
    }
    if (minA <= 0 || sum <= 0) return Number.POSITIVE_INFINITY
    const s2 = side * side
    const sum2 = sum * sum
    return Math.max((s2 * maxA) / sum2, sum2 / (s2 * minA))
  }

  while (idx < scaled.length) {
    const side = Math.min(rw, rh)
    const row = [scaled[idx++]]
    let best = worst(row, side)
    while (idx < scaled.length) {
      row.push(scaled[idx])
      const nxt = worst(row, side)
      if (nxt <= best) {
        best = nxt
        idx++
      } else {
        row.pop()
        break
      }
    }
    const rowArea = row.reduce((sum, r) => sum + r.area, 0)
    if (rw >= rh) {
      const cw = rh > 0 ? rowArea / rh : 0
      let cy = ry
      for (const r of row) {
        const ih = cw > 0 ? r.area / cw : 0
        res.push({ ref: r.ref, x: rx, y: cy, w: cw, h: ih })
        cy += ih
      }
      rx += cw
      rw = Math.max(0, rw - cw)
    } else {
      const rhRow = rw > 0 ? rowArea / rw : 0
      let cx = rx
      for (const r of row) {
        const iw = rhRow > 0 ? r.area / rhRow : 0
        res.push({ ref: r.ref, x: cx, y: ry, w: iw, h: rhRow })
        cx += iw
      }
      ry += rhRow
      rh = Math.max(0, rh - rhRow)
    }
  }
  return res
}

export function convexHull(pts: Point2D[]): Point2D[] {
  const sorted = pts.slice().sort((a, b) => (a.x === b.x ? a.y - b.y : a.x - b.x))
  const cross = (o: Point2D, a: Point2D, b: Point2D) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)
  const lower: Point2D[] = []
  for (const p of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop()
    lower.push(p)
  }
  const upper: Point2D[] = []
  for (let i = sorted.length - 1; i >= 0; i--) {
    const p = sorted[i]
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop()
    upper.push(p)
  }
  upper.pop()
  lower.pop()
  return lower.concat(upper)
}

/** Light-mode TraceForge architectural white-model material resolver. */
export function resolveBuildingMaterial(
  glow: number,
  dimmed: boolean,
  isSelected: boolean,
  isHovered: boolean,
  isImpactFocus: boolean,
): PrismStyle {
  if (dimmed && !isHovered && !isSelected) {
    return {
      top: '#f8fafc',
      left: '#edf2f7',
      right: '#e2e8f0',
      stroke: 'rgba(148, 163, 184, 0.35)',
      lineWidth: 0.75,
    }
  }
  const t = isImpactFocus ? Math.max(0.58, glow) : glow
  const isTower = t > 0.14
  return {
    top: isSelected ? '#e0f2fe' : (isTower ? mixRgb('#ffffff', '#bae6fd', t * 0.92) : '#ffffff'),
    sideGradient: true,
    leftGrad: [mixRgb('#f4f8fc', '#7dd3fc', t * 0.95), mixRgb('#eaf1f8', '#e0f2fe', t * 0.75)],
    rightGrad: [mixRgb('#e2ebf5', '#0ea5e9', t * 0.92), mixRgb('#d4e0ee', '#38bdf8', t * 0.65)],
    stroke: isSelected
      ? '#0284c7'
      : (isHovered ? '#0ea5e9' : (isTower ? mixRgb('#cbd5e1', '#0284c7', t * 0.65) : 'rgba(148, 163, 184, 0.45)')),
    topStroke: isSelected
      ? '#0284c7'
      : (isHovered ? '#0ea5e9' : (isTower ? mixRgb('#e2e8f0', '#0284c7', t * 0.55) : 'rgba(148, 163, 184, 0.38)')),
    lineWidth: isSelected ? 1.8 : (isHovered ? 1.4 : 0.85),
    topLineWidth: isSelected ? 2 : (isHovered ? 1.5 : 0.95),
    floorLines: isTower ? `rgba(255, 255, 255, ${0.28 + t * 0.25})` : null,
    shadowColor: `rgba(15, 23, 42, ${0.045 + t * 0.05})`,
  }
}

export function drawIsoPrism(
  ctx: CanvasRenderingContext2D,
  project: (wx: number, wy: number, wz: number) => ProjectedPoint,
  pitch: number,
  camScale: number,
  x: number,
  y: number,
  w: number,
  h: number,
  zBase: number,
  height: number,
  style: PrismStyle,
): PrismGeometryResult {
  const b0 = project(x, y, zBase)
  const b1 = project(x + w, y, zBase)
  const b2 = project(x + w, y + h, zBase)
  const b3 = project(x, y + h, zBase)

  const t0 = project(x, y, zBase + height)
  const t1 = project(x + w, y, zBase + height)
  const t2 = project(x + w, y + h, zBase + height)
  const t3 = project(x, y + h, zBase + height)

  const basePts = [b0, b1, b2, b3]
  const topPts = [t0, t1, t2, t3]

  const edges = [
    { i: 0, j: 1, avgY: (b0.y + b1.y) / 2 },
    { i: 1, j: 2, avgY: (b1.y + b2.y) / 2 },
    { i: 2, j: 3, avgY: (b2.y + b3.y) / 2 },
    { i: 3, j: 0, avgY: (b3.y + b0.y) / 2 },
  ]
  edges.sort((a, b) => a.avgY - b.avgY)
  const frontWalls = edges.slice(2).sort((a, b) => {
    const ax = (basePts[a.i].x + basePts[a.j].x) / 2
    const bx = (basePts[b.i].x + basePts[b.j].x) / 2
    return ax - bx
  })

  if (height > 8 && style.shadowColor && pitch < 0.85) {
    const shDx = height * 0.42 * camScale
    const shDy = height * 0.16 * camScale
    ctx.beginPath()
    ctx.moveTo(b0.x + shDx, b0.y + shDy)
    ctx.lineTo(b1.x + shDx, b1.y + shDy)
    ctx.lineTo(b2.x + shDx, b2.y + shDy)
    ctx.lineTo(b3.x + shDx, b3.y + shDy)
    ctx.closePath()
    ctx.fillStyle = style.shadowColor
    ctx.fill()
  }

  if (height > 0.6) {
    frontWalls.forEach((wall, idx) => {
      const pA = basePts[wall.i]
      const pB = basePts[wall.j]
      const pBt = topPts[wall.j]
      const pAt = topPts[wall.i]

      ctx.beginPath()
      ctx.moveTo(pA.x, pA.y)
      ctx.lineTo(pB.x, pB.y)
      ctx.lineTo(pBt.x, pBt.y)
      ctx.lineTo(pAt.x, pAt.y)
      ctx.closePath()

      if (style.sideGradient && style.leftGrad && style.rightGrad) {
        const grad = ctx.createLinearGradient(0, Math.min(pAt.y, pBt.y), 0, Math.max(pA.y, pB.y))
        const stops = idx === 0 ? style.leftGrad : style.rightGrad
        grad.addColorStop(0, stops[0])
        grad.addColorStop(1, stops[1])
        ctx.fillStyle = grad
      } else {
        ctx.fillStyle = (idx === 0 ? style.left : style.right) ?? '#e2e8f0'
      }
      ctx.fill()

      if (style.floorLines && height > 28) {
        const floors = Math.min(6, Math.floor(height / 20))
        ctx.beginPath()
        for (let fl = 1; fl <= floors; fl++) {
          const frac = fl / (floors + 1)
          ctx.moveTo(lerp(pA.x, pAt.x, frac), lerp(pA.y, pAt.y, frac))
          ctx.lineTo(lerp(pB.x, pBt.x, frac), lerp(pB.y, pBt.y, frac))
        }
        ctx.strokeStyle = style.floorLines
        ctx.lineWidth = 0.75
        ctx.stroke()
      }

      ctx.strokeStyle = style.stroke
      ctx.lineWidth = style.lineWidth ?? 0.8
      ctx.stroke()
    })
  }

  ctx.beginPath()
  ctx.moveTo(t0.x, t0.y)
  ctx.lineTo(t1.x, t1.y)
  ctx.lineTo(t2.x, t2.y)
  ctx.lineTo(t3.x, t3.y)
  ctx.closePath()
  ctx.fillStyle = style.top
  ctx.fill()
  if (style.dashed) ctx.setLineDash([5, 4])
  ctx.strokeStyle = style.topStroke ?? style.stroke
  ctx.lineWidth = style.topLineWidth ?? style.lineWidth ?? 0.9
  ctx.stroke()
  if (style.dashed) ctx.setLineDash([])

  const allPts = topPts.concat(basePts)
  let minX = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  for (const p of allPts) {
    if (p.x < minX) minX = p.x
    if (p.x > maxX) maxX = p.x
    if (p.y < minY) minY = p.y
    if (p.y > maxY) maxY = p.y
  }

  return {
    hull: convexHull(allPts),
    minX,
    maxX,
    minY,
    maxY,
    roofCenter: { x: (t0.x + t1.x + t2.x + t3.x) / 4, y: (t0.y + t1.y + t2.y + t3.y) / 4 },
  }
}
