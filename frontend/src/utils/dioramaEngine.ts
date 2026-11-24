import type {
  DashboardDioramaPayload,
  DioramaDrillState,
  DioramaHit,
  DioramaIsoMode,
  DioramaMemberItem,
  DioramaMetric,
  DioramaModuleHeatStats,
  DioramaModuleItem,
  DioramaRepoItem,
  DioramaTaskItem,
  DioramaWindowMode,
} from '@/types/dashboardDiorama'
import {
  clamp,
  drawIsoPrism,
  pointInPoly,
  resolveBuildingMaterial,
  roundRectPath,
  squarifyBlocks,
  type Point2D,
  type ProjectedPoint,
  type RectBox,
} from './dioramaGeometry'

export { squarifyBlocks }

interface PlinthNode {
  kind: 'repo'
  id: string
  repo: DioramaRepoItem
  x: number
  y: number
  w: number
  h: number
  cx: number
  cy: number
  slabH: number
}

interface BuildingNode {
  kind: 'module'
  id: string
  repoId: string
  repo: DioramaRepoItem
  module: DioramaModuleItem
  x: number
  y: number
  w: number
  h: number
  cx: number
  cy: number
  curH: number
  targetH: number
  curGlow: number
  targetGlow: number
}

interface HitEntry {
  node: BuildingNode
  poly: Point2D[]
  minX: number
  maxX: number
  minY: number
  maxY: number
}

interface RippleWave {
  wx: number
  wy: number
  start: number
  duration: number
  maxR: number
}

interface ImpactInfo {
  active: boolean
  strict: boolean
  modSet: Set<string>
  repoSet: Set<string>
  activeTask: DioramaTaskItem | null
}

export interface DioramaEngineCallbacks {
  onZoomChange?: (pct: number) => void
  onDrillChange?: (drill: DioramaDrillState | null) => void
  onHover?: (hit: DioramaHit | null, sx: number, sy: number) => void
  onSelect?: (hit: DioramaHit) => void
  pendingRepoLabel?: string
}

/**
 * 2.5D Apple-Maps-inspired architectural white-model canvas engine tailored
 * to TraceForge's crisp light-blue & pure-white surface system.
 */
export class ArchitecturalDioramaEngine {
  private readonly canvas: HTMLCanvasElement
  private readonly ctx: CanvasRenderingContext2D
  private readonly viewportEl: HTMLElement
  private readonly cb: DioramaEngineCallbacks
  private pendingRepoLabel: string

  private data: DashboardDioramaPayload
  private width = 900
  private height = 560
  private dpr = 1
  private readonly worldSize = 940

  private cam = { x: 0, y: 0, scale: 1 }
  private targetCam = { x: 0, y: 0, scale: 1 }
  private baseFitScale = 0.85
  private angle = Math.PI / 4
  private targetAngle = Math.PI / 4
  private pitch = 0.52
  private targetPitch = 0.52

  private metric: DioramaMetric = 'heat'
  private isoMode: DioramaIsoMode = '3d'
  private windowMode: DioramaWindowMode = 'cumulative'
  private dayIndex = 0
  private enabledRepos = new Set<string>()
  private showAvatars = true
  private showLabels = true

  private hovered: DioramaHit | null = null
  private selected: { kind: 'repo' | 'module'; id: string } | null = null
  private highlightTaskId: string | null = null
  private highlightMemberId: string | null = null
  private searchMatchIds = new Set<string>()

  private plinths: PlinthNode[] = []
  private buildings: BuildingNode[] = []
  private readonly buildingById = new Map<string, BuildingNode>()
  private readonly plinthById = new Map<string, PlinthNode>()
  private memberById = new Map<string, DioramaMemberItem>()
  private plaqueBoxes: RectBox[] = []
  private projectedHitList: HitEntry[] = []

  public readonly modHeat = new Map<string, DioramaModuleHeatStats>()
  private maxModScore = 1
  private maxModLoc = 1

  private ripples: RippleWave[] = []
  private arcPhase = 0
  private rafId = 0
  private lastTs = 0
  private destroyed = false

  private pointerDown = false
  private dragging = false
  private dragStart = { x: 0, y: 0, camX: 0, camY: 0 }

  private resizeObserver: ResizeObserver | null = null
  private readonly boundWheel: (e: WheelEvent) => void
  private readonly boundPointerDown: (e: PointerEvent) => void
  private readonly boundPointerMove: (e: PointerEvent) => void
  private readonly boundPointerUp: (e: PointerEvent) => void
  private readonly boundPointerLeave: () => void
  private readonly boundDoubleClick: (e: MouseEvent) => void

  constructor(
    canvas: HTMLCanvasElement,
    viewportEl: HTMLElement,
    data: DashboardDioramaPayload,
    callbacks: DioramaEngineCallbacks = {},
  ) {
    const context = canvas.getContext('2d', { alpha: false })
    if (!context) throw new Error('Unable to initialize 2D canvas context')
    this.canvas = canvas
    this.ctx = context
    this.viewportEl = viewportEl
    this.data = data
    this.cb = callbacks
    this.pendingRepoLabel = callbacks.pendingRepoLabel ?? 'Pending sync'

    this.boundWheel = e => this.onWheel(e)
    this.boundPointerDown = e => this.onPointerDown(e)
    this.boundPointerMove = e => this.onPointerMove(e)
    this.boundPointerUp = e => this.onPointerUp(e)
    this.boundPointerLeave = () => this.onPointerLeave()
    this.boundDoubleClick = e => this.onDoubleClick(e)

    this.bindEvents()
    this.setData(data, true)
    this.resize()
    this.resetView(true)
    this.scheduleRender()
  }

  private bindEvents(): void {
    if (typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver(() => this.resize())
      this.resizeObserver.observe(this.viewportEl)
    }
    this.canvas.addEventListener('wheel', this.boundWheel, { passive: false })
    this.canvas.addEventListener('pointerdown', this.boundPointerDown)
    window.addEventListener('pointermove', this.boundPointerMove)
    window.addEventListener('pointerup', this.boundPointerUp)
    this.canvas.addEventListener('mouseleave', this.boundPointerLeave)
    this.canvas.addEventListener('dblclick', this.boundDoubleClick)
  }

  public destroy(): void {
    this.destroyed = true
    if (this.rafId) {
      cancelAnimationFrame(this.rafId)
      this.rafId = 0
    }
    this.resizeObserver?.disconnect()
    this.resizeObserver = null
    this.canvas.removeEventListener('wheel', this.boundWheel)
    this.canvas.removeEventListener('pointerdown', this.boundPointerDown)
    window.removeEventListener('pointermove', this.boundPointerMove)
    window.removeEventListener('pointerup', this.boundPointerUp)
    this.canvas.removeEventListener('mouseleave', this.boundPointerLeave)
    this.canvas.removeEventListener('dblclick', this.boundDoubleClick)
  }

  public setPendingRepoLabel(label: string): void {
    this.pendingRepoLabel = label
    this.scheduleRender()
  }

  public setData(data: DashboardDioramaPayload, resetFilter = false): void {
    this.data = data
    this.memberById = new Map(data.members.map(m => [m.id, m]))
    if (resetFilter || !this.enabledRepos.size) {
      this.enabledRepos = new Set(data.repos.map(r => r.id))
    } else {
      const validIds = new Set(data.repos.map(r => r.id))
      const next = new Set([...this.enabledRepos].filter(id => validIds.has(id)))
      this.enabledRepos = next.size ? next : validIds
    }
    this.dayIndex = Math.max(0, data.timeline.length - 1)
    this.buildCityGeometry()
    this.recomputeHeat(false)
    this.scheduleRender()
  }

  public hasBuilding(moduleId: string): boolean {
    return this.buildingById.has(moduleId)
  }

  public getPlinthCount(): number {
    return this.plinths.length
  }

  public getBuildingCount(): number {
    return this.buildings.length
  }

  public resize(): void {
    if (this.destroyed) return
    const rect = this.viewportEl.getBoundingClientRect()
    this.width = Math.max(320, Math.floor(rect.width))
    this.height = Math.max(260, Math.floor(rect.height))
    this.dpr = Math.min(window.devicePixelRatio || 1, 2)
    this.canvas.width = Math.round(this.width * this.dpr)
    this.canvas.height = Math.round(this.height * this.dpr)
    this.canvas.style.width = `${this.width}px`
    this.canvas.style.height = `${this.height}px`
    this.fitCameraToStage(false)
    this.scheduleRender()
  }

  private fitCameraToStage(immediate: boolean): void {
    const availW = this.width - 76
    const availH = this.height - 96
    const span = this.worldSize * 1.42
    const scaleW = availW / span
    const scaleH = availH / (span * Math.max(0.55, this.targetPitch) + 120)
    const fitScale = clamp(Math.min(scaleW, scaleH), 0.45, 1.45)
    this.baseFitScale = fitScale
    const next = { x: this.width / 2, y: this.height * 0.56, scale: fitScale }
    this.targetCam = next
    if (immediate) this.cam = { ...next }
  }

  public resetView(immediate = false): void {
    this.fitCameraToStage(immediate)
    this.scheduleRender()
    this.cb.onDrillChange?.(null)
  }

  public setMetric(metric: DioramaMetric): void {
    this.metric = metric
    this.updateBuildingTargets()
    this.scheduleRender()
  }

  public setIsoMode(mode: DioramaIsoMode): void {
    this.isoMode = mode
    this.targetPitch = mode === 'top' ? 0.96 : 0.52
    this.updateBuildingTargets()
    this.scheduleRender()
  }

  public rotateView(dir: 1 | -1 = 1): void {
    this.targetAngle += dir * (Math.PI / 2)
    this.scheduleRender()
  }

  public setLayers(opts: { avatars?: boolean; labels?: boolean }): void {
    if (typeof opts.avatars === 'boolean') this.showAvatars = opts.avatars
    if (typeof opts.labels === 'boolean') this.showLabels = opts.labels
    this.scheduleRender()
  }

  public setEnabledRepos(repoIds: Set<string>): void {
    this.enabledRepos = new Set(repoIds)
    this.buildCityGeometry()
    this.updateBuildingTargets()
    this.resetView(false)
  }

  public setHighlight(taskId: string | null, memberId: string | null): void {
    this.highlightTaskId = taskId
    this.highlightMemberId = memberId
    this.updateBuildingTargets()
    this.scheduleRender()
  }

  public setSearchMatches(ids: Set<string>): void {
    this.searchMatchIds = new Set(ids)
    this.scheduleRender()
  }

  public setTimeline(dayIndex: number, windowMode: DioramaWindowMode, emitRipples: boolean): void {
    this.dayIndex = clamp(dayIndex, 0, Math.max(0, this.data.timeline.length - 1))
    this.windowMode = windowMode
    this.recomputeHeat(emitRipples)
    this.scheduleRender()
  }

  public zoomBy(factor: number, pivotSx?: number, pivotSy?: number): void {
    const px = pivotSx ?? this.width / 2
    const py = pivotSy ?? this.height / 2
    const prev = this.targetCam.scale
    const next = clamp(prev * factor, 0.42, 3.6)
    const ratio = next / prev
    this.targetCam.scale = next
    this.targetCam.x = px - (px - this.targetCam.x) * ratio
    this.targetCam.y = py - (py - this.targetCam.y) * ratio
    this.scheduleRender()
  }

  public focusEntity(kind: 'repo' | 'module', id: string): void {
    if (kind === 'repo') {
      const p = this.plinthById.get(id)
      if (!p) return
      this.selected = { kind: 'repo', id }
      const center = this.project(p.cx, p.cy, 0)
      const nextScale = clamp(this.baseFitScale * 1.65, 0.9, 2.4)
      const ratio = nextScale / this.cam.scale
      this.targetCam.scale = nextScale
      this.targetCam.x = this.width / 2 - (center.x - this.cam.x) * ratio
      this.targetCam.y = this.height * 0.54 - (center.y - this.cam.y) * ratio
      this.cb.onSelect?.({ kind: 'repo', id, repo: p.repo })
      this.cb.onDrillChange?.({ repo: p.repo, module: null })
      this.scheduleRender()
      return
    }
    const b = this.buildingById.get(id)
    if (!b) return
    this.selected = { kind: 'module', id }
    const center = this.project(b.cx, b.cy, b.targetH * 0.35)
    const nextScale = clamp(this.baseFitScale * 2.1, 1.2, 2.8)
    const ratio = nextScale / this.cam.scale
    this.targetCam.scale = nextScale
    this.targetCam.x = this.width / 2 - (center.x - this.cam.x) * ratio
    this.targetCam.y = this.height * 0.54 - (center.y - this.cam.y) * ratio
    this.cb.onSelect?.({ kind: 'module', id, repo: b.repo, module: b.module })
    this.cb.onDrillChange?.({ repo: b.repo, module: b.module })
    this.scheduleRender()
  }

  private buildCityGeometry(): void {
    const prevHeights = new Map(this.buildings.map(b => [b.id, b.curH]))
    this.plinths = []
    this.buildings = []
    this.buildingById.clear()
    this.plinthById.clear()

    const activeRepos = this.data.repos.filter(r => this.enabledRepos.has(r.id))
    if (!activeRepos.length) return

    const span = this.worldSize
    const half = span / 2
    const avenue = activeRepos.length === 1 ? 0 : 24

    const repoItems = activeRepos.map(repo => ({
      ref: repo,
      weight: Math.max(460, Math.pow(Math.max(repo.loc, 300), 0.68)),
    }))
    const laidRepos = squarifyBlocks(repoItems, -half, -half, span, span)

    let maxLoc = 1
    for (const lr of laidRepos) {
      const px = lr.x + avenue / 2
      const py = lr.y + avenue / 2
      const pw = Math.max(60, lr.w - avenue)
      const ph = Math.max(60, lr.h - avenue)
      const plinth: PlinthNode = {
        kind: 'repo',
        id: lr.ref.id,
        repo: lr.ref,
        x: px,
        y: py,
        w: pw,
        h: ph,
        cx: px + pw / 2,
        cy: py + ph / 2,
        slabH: 10,
      }
      this.plinths.push(plinth)
      this.plinthById.set(plinth.id, plinth)

      if (!lr.ref.modules.length) continue
      const sortedMods = lr.ref.modules
        .slice()
        .sort((a, b) => (b.commits * 400 + b.loc) - (a.commits * 400 + a.loc))
        .slice(0, 18)

      const pad = 16
      const blockItems = sortedMods.map(m => ({
        ref: m,
        weight: Math.max(120, Math.pow(Math.max(m.loc, 120), 0.72)),
      }))
      const laidBlocks = squarifyBlocks(
        blockItems,
        px + pad,
        py + pad,
        Math.max(30, pw - pad * 2),
        Math.max(30, ph - pad * 2),
      )

      for (const lb of laidBlocks) {
        const street = clamp(Math.min(lb.w, lb.h) * 0.1, 4.5, 9.5)
        const bx = lb.x + street
        const by = lb.y + street
        const bw = Math.max(14, lb.w - street * 2)
        const bh = Math.max(14, lb.h - street * 2)
        if (lb.ref.loc > maxLoc) maxLoc = lb.ref.loc

        const node: BuildingNode = {
          kind: 'module',
          id: lb.ref.id,
          repoId: lr.ref.id,
          repo: lr.ref,
          module: lb.ref,
          x: bx,
          y: by,
          w: bw,
          h: bh,
          cx: bx + bw / 2,
          cy: by + bh / 2,
          curH: prevHeights.get(lb.ref.id) ?? 4,
          targetH: 4,
          curGlow: 0,
          targetGlow: 0,
        }
        this.buildings.push(node)
        this.buildingById.set(node.id, node)
      }
    }
    this.maxModLoc = maxLoc
  }

  private recomputeHeat(emitRipples: boolean): void {
    this.modHeat.clear()
    const timeline = this.data.timeline
    let maxScore = 1

    if (timeline.length) {
      const startIdx = this.windowMode === 'day' ? this.dayIndex : 0
      const endIdx = this.dayIndex
      for (let i = startIdx; i <= endIdx; i++) {
        const day = timeline[i]
        if (!day) continue
        const recency = this.windowMode === 'day' ? 1 : 0.42 + 0.58 * ((i + 1) / (endIdx + 1))
        for (const [mid, st] of Object.entries(day.module_heat || {})) {
          const prev = this.modHeat.get(mid) ?? { commits: 0, added: 0, deleted: 0, score: 0 }
          prev.commits += st.commits
          prev.added += st.added
          prev.deleted += st.deleted
          prev.score += (st.commits * 1.8 + Math.log1p(st.added + st.deleted) * 0.65) * recency
          this.modHeat.set(mid, prev)
          if (prev.score > maxScore) maxScore = prev.score
        }
      }
    } else {
      for (const b of this.buildings) {
        if (b.module.commits > 0) {
          const score = b.module.commits * 1.8 + Math.log1p(b.module.added + b.module.deleted) * 0.65
          this.modHeat.set(b.id, {
            commits: b.module.commits,
            added: b.module.added,
            deleted: b.module.deleted,
            score,
          })
          if (score > maxScore) maxScore = score
        }
      }
    }

    this.maxModScore = maxScore
    this.updateBuildingTargets()

    if (emitRipples && timeline.length) {
      const curDay = timeline[this.dayIndex]
      if (curDay?.module_heat) {
        const now = performance.now()
        const touched = Object.entries(curDay.module_heat)
          .sort((a, b) => (b[1].added + b[1].deleted) - (a[1].added + a[1].deleted))
          .slice(0, 5)
        touched.forEach(([mid], idx) => {
          const b = this.buildingById.get(mid)
          if (!b) return
          this.ripples.push({
            wx: b.cx,
            wy: b.cy,
            start: now + idx * 70,
            duration: 950,
            maxR: Math.max(38, Math.min(b.w, b.h) * 1.05),
          })
        })
        if (this.ripples.length > 24) this.ripples.splice(0, this.ripples.length - 24)
      }
    }
  }

  private getImpactInfo(): ImpactInfo {
    const modSet = new Set<string>()
    const repoSet = new Set<string>()
    let activeTask: DioramaTaskItem | null = null

    if (this.highlightTaskId) {
      activeTask = this.data.tasks.find(t => t.id === this.highlightTaskId) ?? null
      if (activeTask) {
        activeTask.modules.forEach(m => modSet.add(m))
        activeTask.repos.forEach(r => repoSet.add(r))
      }
    } else if (this.highlightMemberId) {
      for (const t of this.data.tasks) {
        if (t.creator_id !== this.highlightMemberId) continue
        t.modules.forEach(m => modSet.add(m))
        t.repos.forEach(r => repoSet.add(r))
      }
    } else if (this.metric === 'impact') {
      for (const t of this.data.tasks) {
        if (!['RUNNING', 'AWAITING_INPUT', 'ROUND_COMPLETED', 'INTERRUPTED'].includes(t.status)) continue
        t.modules.forEach(m => modSet.add(m))
        t.repos.forEach(r => repoSet.add(r))
      }
    }
    return {
      active: Boolean(this.highlightTaskId || this.highlightMemberId || this.metric === 'impact'),
      strict: Boolean(this.highlightTaskId || this.highlightMemberId),
      modSet,
      repoSet,
      activeTask,
    }
  }

  private updateBuildingTargets(): void {
    const impact = this.getImpactInfo()
    const flatMode = this.isoMode === 'top'
    const maxTowerH = flatMode ? 4 : 128

    for (const b of this.buildings) {
      const mh = this.modHeat.get(b.id)
      const normHeat = mh ? Math.pow(clamp(mh.score / this.maxModScore, 0, 1), 0.78) : 0
      const normLoc = Math.pow(clamp(b.module.loc / this.maxModLoc, 0, 1), 0.65)
      const inImpact = impact.modSet.has(b.id) || (impact.modSet.size === 0 && impact.repoSet.has(b.repoId))

      if (impact.active) {
        if (inImpact) {
          const boost = 0.34 + 0.66 * Math.max(normHeat, 0.25)
          b.targetH = flatMode ? 3 : (26 + boost * (maxTowerH - 26))
          b.targetGlow = Math.max(0.55, normHeat)
        } else {
          b.targetH = 2.5
          b.targetGlow = 0
        }
      } else if (this.metric === 'loc') {
        b.targetH = flatMode ? 3 : (6 + normLoc * (maxTowerH - 12))
        b.targetGlow = normLoc * 0.72
      } else if (!mh || mh.commits === 0) {
        const hasAnyHeat = this.modHeat.size > 0
        b.targetH = hasAnyHeat ? 3 : (flatMode ? 3 : (5 + normLoc * 46))
        b.targetGlow = hasAnyHeat ? 0 : normLoc * 0.28
      } else {
        b.targetH = flatMode ? 3 : (12 + normHeat * (maxTowerH - 12))
        b.targetGlow = normHeat
      }
    }
  }

  private project(wx: number, wy: number, wz = 0): ProjectedPoint {
    const c = Math.cos(this.angle)
    const s = Math.sin(this.angle)
    const rx = wx * c - wy * s
    const ry = wx * s + wy * c
    const scale = this.cam.scale
    return {
      x: this.cam.x + rx * scale,
      y: this.cam.y + ry * this.pitch * scale - wz * scale * (1 - (this.pitch - 0.52) * 1.45),
      depth: ry,
    }
  }

  private screenToGround(sx: number, sy: number): Point2D {
    const scale = this.cam.scale
    const rx = (sx - this.cam.x) / scale
    const ry = (sy - this.cam.y) / (scale * this.pitch)
    const c = Math.cos(-this.angle)
    const s = Math.sin(-this.angle)
    return { x: rx * c - ry * s, y: rx * s + ry * c }
  }

  private hitTest(sx: number, sy: number): DioramaHit | null {
    for (let i = this.projectedHitList.length - 1; i >= 0; i--) {
      const entry = this.projectedHitList[i]
      if (sx < entry.minX || sx > entry.maxX || sy < entry.minY || sy > entry.maxY) continue
      if (pointInPoly(sx, sy, entry.poly)) {
        return { kind: 'module', id: entry.node.id, repo: entry.node.repo, module: entry.node.module }
      }
    }
    const g = this.screenToGround(sx, sy)
    for (const p of this.plinths) {
      if (g.x >= p.x && g.x <= p.x + p.w && g.y >= p.y && g.y <= p.y + p.h) {
        return { kind: 'repo', id: p.id, repo: p.repo }
      }
    }
    return null
  }

  private onWheel(e: WheelEvent): void {
    e.preventDefault()
    const rect = this.canvas.getBoundingClientRect()
    this.zoomBy(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - rect.left, e.clientY - rect.top)
  }

  private onPointerDown(e: PointerEvent): void {
    if (e.button !== 0) return
    const rect = this.canvas.getBoundingClientRect()
    this.pointerDown = true
    this.dragging = false
    this.dragStart = {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
      camX: this.targetCam.x,
      camY: this.targetCam.y,
    }
  }

  private onPointerMove(e: PointerEvent): void {
    const rect = this.canvas.getBoundingClientRect()
    const sx = e.clientX - rect.left
    const sy = e.clientY - rect.top

    if (this.pointerDown) {
      const dx = sx - this.dragStart.x
      const dy = sy - this.dragStart.y
      if (!this.dragging && Math.hypot(dx, dy) > 4) {
        this.dragging = true
        this.viewportEl.classList.add('is-dragging')
      }
      if (this.dragging) {
        this.targetCam.x = this.dragStart.camX + dx
        this.targetCam.y = this.dragStart.camY + dy
        this.cam.x = this.targetCam.x
        this.cam.y = this.targetCam.y
        this.cb.onHover?.(null, sx, sy)
        this.scheduleRender()
        return
      }
    }
    if (sx < 0 || sy < 0 || sx > this.width || sy > this.height) return

    const hit = this.hitTest(sx, sy)
    const prevK = this.hovered ? `${this.hovered.kind}:${this.hovered.id}` : ''
    const nextK = hit ? `${hit.kind}:${hit.id}` : ''
    this.hovered = hit
    this.viewportEl.classList.toggle('is-pointer', Boolean(hit))
    if (prevK !== nextK) this.scheduleRender()
    this.cb.onHover?.(hit, sx, sy)
  }

  private onPointerUp(e: PointerEvent): void {
    if (!this.pointerDown) return
    const wasDrag = this.dragging
    this.pointerDown = false
    this.dragging = false
    this.viewportEl.classList.remove('is-dragging')
    if (wasDrag) return

    const rect = this.canvas.getBoundingClientRect()
    const sx = e.clientX - rect.left
    const sy = e.clientY - rect.top
    if (sx < 0 || sy < 0 || sx > this.width || sy > this.height) return
    const hit = this.hitTest(sx, sy)
    if (hit) {
      this.selected = { kind: hit.kind, id: hit.id }
      this.cb.onSelect?.(hit)
      this.scheduleRender()
    }
  }

  private onPointerLeave(): void {
    if (!this.hovered) return
    this.hovered = null
    this.viewportEl.classList.remove('is-pointer')
    this.cb.onHover?.(null, 0, 0)
    this.scheduleRender()
  }

  private onDoubleClick(e: MouseEvent): void {
    const rect = this.canvas.getBoundingClientRect()
    const hit = this.hitTest(e.clientX - rect.left, e.clientY - rect.top)
    if (!hit) {
      this.resetView(false)
      return
    }
    this.focusEntity(hit.kind, hit.id)
  }

  public scheduleRender(): void {
    if (this.destroyed || this.rafId) return
    this.rafId = requestAnimationFrame(ts => this.frame(ts))
  }

  private frame(now: number): void {
    this.rafId = 0
    if (this.destroyed) return
    const dt = this.lastTs ? Math.min(40, now - this.lastTs) : 16
    this.lastTs = now
    const ease = 1 - Math.exp(-dt * 0.014)
    const hEase = 1 - Math.exp(-dt * 0.011)

    let moving = false
    if (
      Math.abs(this.targetCam.x - this.cam.x) > 0.15
      || Math.abs(this.targetCam.y - this.cam.y) > 0.15
      || Math.abs(this.targetCam.scale - this.cam.scale) > 0.001
    ) {
      this.cam.x += (this.targetCam.x - this.cam.x) * ease
      this.cam.y += (this.targetCam.y - this.cam.y) * ease
      this.cam.scale += (this.targetCam.scale - this.cam.scale) * ease
      moving = true
    } else {
      this.cam = { ...this.targetCam }
    }

    if (Math.abs(this.targetAngle - this.angle) > 0.0015) {
      this.angle += (this.targetAngle - this.angle) * ease
      moving = true
    } else {
      this.angle = this.targetAngle
    }

    if (Math.abs(this.targetPitch - this.pitch) > 0.0015) {
      this.pitch += (this.targetPitch - this.pitch) * ease
      moving = true
    } else {
      this.pitch = this.targetPitch
    }

    for (const b of this.buildings) {
      if (Math.abs(b.targetH - b.curH) > 0.12 || Math.abs(b.targetGlow - b.curGlow) > 0.005) {
        b.curH += (b.targetH - b.curH) * hEase
        b.curGlow += (b.targetGlow - b.curGlow) * hEase
        moving = true
      } else {
        b.curH = b.targetH
        b.curGlow = b.targetGlow
      }
    }

    const impact = this.getImpactInfo()
    const hasArcs = impact.strict && impact.modSet.size > 1
    if (hasArcs) {
      this.arcPhase = (this.arcPhase + dt * 0.025) % 1000
      moving = true
    }

    this.ripples = this.ripples.filter(rp => now - rp.start < rp.duration)
    if (this.ripples.length > 0) moving = true

    this.cb.onZoomChange?.(Math.round((this.cam.scale / (this.baseFitScale || 0.8)) * 100))
    this.draw(now, impact)
    if (moving) this.scheduleRender()
  }

  private draw(now: number, impact: ImpactInfo): void {
    const ctx = this.ctx
    const projector = (wx: number, wy: number, wz: number) => this.project(wx, wy, wz)
    this.projectedHitList = []

    ctx.save()
    ctx.scale(this.dpr, this.dpr)

    const bgGrad = ctx.createRadialGradient(
      this.width * 0.48,
      this.height * 0.42,
      40,
      this.width * 0.5,
      this.height * 0.5,
      Math.max(this.width, this.height) * 0.78,
    )
    bgGrad.addColorStop(0, '#fafdff')
    bgGrad.addColorStop(0.65, '#f1f5f9')
    bgGrad.addColorStop(1, '#e8eff7')
    ctx.fillStyle = bgGrad
    ctx.fillRect(0, 0, this.width, this.height)

    this.drawBlueprintGrid(ctx)

    const sortedPlinths = this.plinths
      .map(p => ({ p, depth: this.project(p.cx, p.cy, 0).depth }))
      .sort((a, b) => a.depth - b.depth)

    for (const { p } of sortedPlinths) {
      const isSel = this.selected?.kind === 'repo' && this.selected.id === p.id
      const isHov = this.hovered?.kind === 'repo' && this.hovered.id === p.id

      const s0 = this.project(p.x + 8, p.y + 8, -2)
      const s1 = this.project(p.x + p.w + 8, p.y + 8, -2)
      const s2 = this.project(p.x + p.w + 8, p.y + p.h + 8, -2)
      const s3 = this.project(p.x + 8, p.y + p.h + 8, -2)
      ctx.save()
      ctx.beginPath()
      ctx.moveTo(s0.x, s0.y)
      ctx.lineTo(s1.x, s1.y)
      ctx.lineTo(s2.x, s2.y)
      ctx.lineTo(s3.x, s3.y)
      ctx.closePath()
      ctx.fillStyle = 'rgba(15, 23, 42, 0.06)'
      ctx.filter = 'blur(8px)'
      ctx.fill()
      ctx.restore()

      drawIsoPrism(ctx, projector, this.pitch, this.cam.scale, p.x, p.y, p.w, p.h, 0, p.slabH, {
        top: p.repo.available ? '#f8fbff' : '#f1f5f9',
        left: '#e7eef6',
        right: '#d8e3ef',
        stroke: isSel ? '#0ea5e9' : (isHov ? '#38bdf8' : 'rgba(15, 23, 42, 0.1)'),
        topStroke: isSel ? '#0ea5e9' : 'rgba(15, 23, 42, 0.09)',
        lineWidth: isSel ? 1.8 : 1,
        dashed: !p.repo.available,
      })

      if (!p.repo.available || !p.repo.modules.length) {
        const c = this.project(p.cx, p.cy, p.slabH + 2)
        ctx.save()
        ctx.font = '500 11px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif'
        ctx.fillStyle = '#94a3b8'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(p.repo.available ? p.repo.name : `${p.repo.name} · ${this.pendingRepoLabel}`, c.x, c.y)
        ctx.restore()
      }
    }

    if (this.ripples.length > 0) this.drawRipples(ctx, now)

    const sortedBuildings = this.buildings
      .map(b => ({ b, depth: this.project(b.cx, b.cy, 0).depth }))
      .sort((a, b) => a.depth - b.depth)

    const roofCoords = new Map<string, { x: number; y: number; h: number; glow: number; b: BuildingNode }>()

    for (const { b } of sortedBuildings) {
      const g = clamp(b.curGlow, 0, 1)
      const inImpact = impact.modSet.has(b.id) || (impact.modSet.size === 0 && impact.repoSet.has(b.repoId))
      const dimmed = impact.active && !inImpact
      const isSel = this.selected?.kind === 'module' && this.selected.id === b.id
      const isHov = this.hovered?.kind === 'module' && this.hovered.id === b.id
      const isSearch = this.searchMatchIds.has(b.id)

      const liftZ = 10 + (isSel ? 5 : isHov ? 3 : 0)
      const style = resolveBuildingMaterial(g, dimmed, isSel || isSearch, isHov, inImpact && impact.strict)

      ctx.save()
      if (dimmed && !isHov && !isSel) ctx.globalAlpha = 0.48
      const geom = drawIsoPrism(ctx, projector, this.pitch, this.cam.scale, b.x, b.y, b.w, b.h, liftZ, b.curH, style)
      ctx.restore()

      roofCoords.set(b.id, { ...geom.roofCenter, h: b.curH, glow: g, b })
      this.projectedHitList.push({
        node: b,
        poly: geom.hull,
        minX: geom.minX,
        maxX: geom.maxX,
        minY: geom.minY,
        maxY: geom.maxY,
      })
    }

    this.plaqueBoxes = []
    for (const { p } of sortedPlinths) {
      this.drawPlinthLabel(ctx, p)
    }

    if (impact.strict && impact.modSet.size > 1) {
      this.drawSkyBridges(ctx, impact, roofCoords)
    }
    if (this.showAvatars) {
      this.drawMemberPins(ctx, roofCoords)
    }
    if (this.showLabels) {
      this.drawLandmarkLabels(ctx, impact, roofCoords)
    }

    ctx.restore()
  }

  private drawBlueprintGrid(ctx: CanvasRenderingContext2D): void {
    const span = this.worldSize * 0.72
    const step = 80
    ctx.save()
    ctx.strokeStyle = 'rgba(15, 23, 42, 0.04)'
    ctx.lineWidth = 1
    ctx.beginPath()
    for (let v = -span; v <= span; v += step) {
      const a = this.project(v, -span, 0)
      const b = this.project(v, span, 0)
      ctx.moveTo(a.x, a.y)
      ctx.lineTo(b.x, b.y)
      const c = this.project(-span, v, 0)
      const d = this.project(span, v, 0)
      ctx.moveTo(c.x, c.y)
      ctx.lineTo(d.x, d.y)
    }
    ctx.stroke()
    ctx.restore()
  }

  private drawPlinthLabel(ctx: CanvasRenderingContext2D, plinth: PlinthNode): void {
    const rawCorners = [
      { wx: plinth.x, wy: plinth.y },
      { wx: plinth.x + plinth.w, wy: plinth.y },
      { wx: plinth.x + plinth.w, wy: plinth.y + plinth.h },
      { wx: plinth.x, wy: plinth.y + plinth.h },
    ]
    rawCorners.sort((a, b) => (b.wx * b.wx + b.wy * b.wy) - (a.wx * a.wx + a.wy * a.wy))
    const outer = rawCorners[0]
    const anchor = this.project(outer.wx, outer.wy, 0)
    const cityCenter = this.project(0, 0, 0)

    let dx = anchor.x - cityCenter.x
    let dy = anchor.y - cityCenter.y
    const dist = Math.hypot(dx, dy) || 1
    dx /= dist
    dy /= dist

    ctx.save()
    const locTag = plinth.repo.loc >= 1000 ? `${(plinth.repo.loc / 1000).toFixed(1)}k` : String(plinth.repo.loc)
    const label = `${plinth.repo.name}  ·  ${locTag}`
    ctx.font = '600 10.5px "JetBrains Mono", Consolas, monospace'
    const tw = ctx.measureText(label).width + 20
    const th = 21

    const tipX = anchor.x + dx * 20
    const tipY = anchor.y + dy * 20
    let px = tipX - tw / 2
    let py = tipY - th / 2
    if (dy < -0.55) {
      px = anchor.x - tw - 48
      py = anchor.y - 42
    } else {
      if (dx < -0.35) px = tipX - tw + 6
      else if (dx > 0.35) px = tipX - 6
      if (dy > 0.35) py = tipY - 2
      else if (dy < -0.35) py = tipY - th + 2
    }

    px = clamp(px, 12, this.width - tw - 12)
    py = clamp(py, 44, this.height - th - 32)
    this.plaqueBoxes.push({ x1: px - 6, y1: py - 4, x2: px + tw + 6, y2: py + th + 4 })

    const boxCx = clamp(anchor.x, px + 8, px + tw - 8)
    const boxCy = clamp(anchor.y, py + 4, py + th - 4)
    ctx.beginPath()
    ctx.moveTo(anchor.x, anchor.y)
    ctx.lineTo(boxCx, boxCy)
    ctx.strokeStyle = 'rgba(15, 23, 42, 0.2)'
    ctx.lineWidth = 1
    ctx.stroke()

    roundRectPath(ctx, px, py, tw, th, 10.5)
    ctx.fillStyle = 'rgba(255, 255, 255, 0.94)'
    ctx.shadowColor = 'rgba(15, 23, 42, 0.08)'
    ctx.shadowBlur = 8
    ctx.shadowOffsetY = 2
    ctx.fill()
    ctx.shadowColor = 'transparent'
    ctx.strokeStyle = 'rgba(15, 23, 42, 0.1)'
    ctx.lineWidth = 1
    ctx.stroke()

    ctx.beginPath()
    ctx.arc(px + 9.5, py + th / 2, 3.2, 0, Math.PI * 2)
    ctx.fillStyle = plinth.repo.color
    ctx.fill()

    ctx.fillStyle = '#1e293b'
    ctx.textBaseline = 'middle'
    ctx.fillText(label, px + 17, py + th / 2 + 0.5)
    ctx.restore()
  }

  private drawRipples(ctx: CanvasRenderingContext2D, now: number): void {
    ctx.save()
    for (const rp of this.ripples) {
      const elapsed = now - rp.start
      if (elapsed < 0 || elapsed > rp.duration) continue
      const p = elapsed / rp.duration
      const eased = 1 - Math.pow(1 - p, 3)
      const center = this.project(rp.wx, rp.wy, 11)
      const rx = Math.max(10, rp.maxR * this.cam.scale * eased)
      const ry = rx * this.pitch
      ctx.beginPath()
      ctx.ellipse(center.x, center.y, rx, ry, 0, 0, Math.PI * 2)
      ctx.strokeStyle = '#0284c7'
      ctx.globalAlpha = (1 - p) * 0.6
      ctx.lineWidth = 2 * (1 - p * 0.5)
      ctx.stroke()
    }
    ctx.restore()
  }

  private drawSkyBridges(
    ctx: CanvasRenderingContext2D,
    impact: ImpactInfo,
    roofCoords: Map<string, { x: number; y: number; h: number; glow: number; b: BuildingNode }>,
  ): void {
    const perRepo = new Map<string, { x: number; y: number }>()
    const order = (impact.activeTask?.primary_modules ?? []).concat([...impact.modSet])
    for (const mid of order) {
      const b = this.buildingById.get(mid)
      if (!b || perRepo.has(b.repoId)) continue
      const rc = roofCoords.get(mid)
      if (rc) perRepo.set(b.repoId, rc)
    }
    const hubs = [...perRepo.values()]
    if (hubs.length < 2) return

    ctx.save()
    const a = hubs[0]
    for (let i = 1; i < hubs.length; i++) {
      const b = hubs[i]
      const mx = (a.x + b.x) / 2
      const my = Math.min(a.y, b.y) - Math.max(44, Math.hypot(b.x - a.x, b.y - a.y) * 0.24)

      ctx.beginPath()
      ctx.moveTo(a.x, a.y)
      ctx.quadraticCurveTo(mx, my, b.x, b.y)
      ctx.strokeStyle = 'rgba(2, 132, 199, 0.16)'
      ctx.lineWidth = 5
      ctx.stroke()

      ctx.beginPath()
      ctx.moveTo(a.x, a.y)
      ctx.quadraticCurveTo(mx, my, b.x, b.y)
      ctx.strokeStyle = '#0284c7'
      ctx.lineWidth = 1.8
      ctx.setLineDash([6, 5])
      ctx.lineDashOffset = -this.arcPhase
      ctx.stroke()
      ctx.setLineDash([])

      for (const pt of [a, b]) {
        ctx.beginPath()
        ctx.arc(pt.x, pt.y, 4, 0, Math.PI * 2)
        ctx.fillStyle = '#ffffff'
        ctx.fill()
        ctx.lineWidth = 1.8
        ctx.strokeStyle = '#0284c7'
        ctx.stroke()
      }
    }
    ctx.restore()
  }

  private drawMemberPins(
    ctx: CanvasRenderingContext2D,
    roofCoords: Map<string, { x: number; y: number; h: number; glow: number; b: BuildingNode }>,
  ): void {
    const pinsByMod = new Map<string, Array<{ member: DioramaMemberItem; task: DioramaTaskItem }>>()
    for (const task of this.data.tasks) {
      if (this.highlightTaskId && task.id !== this.highlightTaskId) continue
      if (this.highlightMemberId && task.creator_id !== this.highlightMemberId) continue
      const member = this.memberById.get(task.creator_id)
      if (!member) continue
      const primary = (task.primary_modules.length ? task.primary_modules : task.modules)[0]
      if (!primary || !roofCoords.has(primary)) continue
      const list = pinsByMod.get(primary) ?? []
      if (!list.some(x => x.member.id === member.id)) {
        list.push({ member, task })
        pinsByMod.set(primary, list)
      }
    }

    ctx.save()
    for (const [mid, list] of pinsByMod.entries()) {
      const rc = roofCoords.get(mid)
      if (!rc) continue
      list.slice(0, 2).forEach((entry, idx) => {
        const px = rc.x + idx * 25 - (list.length > 1 ? 12.5 : 0)
        const py = rc.y - 24

        ctx.beginPath()
        ctx.moveTo(px, rc.y - 2)
        ctx.lineTo(px, py + 10)
        ctx.strokeStyle = 'rgba(15, 23, 42, 0.25)'
        ctx.lineWidth = 1
        ctx.stroke()

        ctx.beginPath()
        ctx.arc(px, py, 11.5, 0, Math.PI * 2)
        ctx.fillStyle = '#ffffff'
        ctx.shadowColor = 'rgba(15, 23, 42, 0.16)'
        ctx.shadowBlur = 8
        ctx.shadowOffsetY = 2
        ctx.fill()
        ctx.shadowColor = 'transparent'

        ctx.beginPath()
        ctx.arc(px, py, 9.5, 0, Math.PI * 2)
        ctx.fillStyle = '#f0f9ff'
        ctx.fill()
        ctx.lineWidth = 1.4
        ctx.strokeStyle = entry.member.color
        ctx.stroke()

        const initial = (entry.member.display_name || '?').trim().slice(0, 1).toLocaleUpperCase()
        ctx.font = '700 9.5px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif'
        ctx.fillStyle = entry.member.color
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(initial, px, py + 0.5)

        if (entry.task.status === 'RUNNING') {
          ctx.beginPath()
          ctx.arc(px + 8, py - 8, 3, 0, Math.PI * 2)
          ctx.fillStyle = '#10b981'
          ctx.fill()
          ctx.lineWidth = 1.2
          ctx.strokeStyle = '#ffffff'
          ctx.stroke()
        }
      })
    }
    ctx.restore()
  }

  private drawLandmarkLabels(
    ctx: CanvasRenderingContext2D,
    impact: ImpactInfo,
    roofCoords: Map<string, { x: number; y: number; h: number; glow: number; b: BuildingNode }>,
  ): void {
    const zoomBoost = this.cam.scale / (this.baseFitScale || 0.8)
    const maxLabels = zoomBoost > 1.7 ? 16 : (zoomBoost > 1.2 ? 10 : 7)

    const candidates: Array<{
      rc: { x: number; y: number; h: number; glow: number; b: BuildingNode }
      priority: number
      isSel: boolean
      isHov: boolean
      isSearch: boolean
    }> = []

    for (const rc of roofCoords.values()) {
      const b = rc.b
      const isSel = this.selected?.kind === 'module' && this.selected.id === b.id
      const isHov = this.hovered?.kind === 'module' && this.hovered.id === b.id
      const isSearch = this.searchMatchIds.has(b.id)
      const inImpact = impact.strict && impact.modSet.has(b.id)
      if (impact.strict && !inImpact && !isHov && !isSel) continue

      let priority = rc.h * 2 + rc.glow * 40
      if (isSel) priority += 10000
      if (isHov) priority += 8000
      if (isSearch) priority += 5000
      if (inImpact) priority += 1200
      if (priority < 22 && !isSel && !isHov && !isSearch) continue
      candidates.push({ rc, priority, isSel, isHov, isSearch })
    }
    candidates.sort((a, b) => b.priority - a.priority)

    const placed: RectBox[] = this.plaqueBoxes.slice()
    ctx.save()
    ctx.font = '600 11px "JetBrains Mono", Consolas, monospace'

    for (const c of candidates) {
      if (placed.length - this.plaqueBoxes.length >= maxLabels && !c.isSel && !c.isHov && !c.isSearch) break
      const mh = this.modHeat.get(c.rc.b.id)
      const metricTag = this.metric === 'loc'
        ? (c.rc.b.module.loc >= 1000 ? `${(c.rc.b.module.loc / 1000).toFixed(1)}k` : `${c.rc.b.module.loc}`)
        : (mh && mh.commits > 0 ? `${mh.commits}c` : '')
      const text = metricTag ? `${c.rc.b.module.name}  ${metricTag}` : c.rc.b.module.name
      const tw = ctx.measureText(text).width + 14
      const th = 20
      const hasPinOffset = this.showAvatars && c.rc.h > 14 ? 42 : 20
      const lx = c.rc.x - tw / 2
      const ly = c.rc.y - hasPinOffset - th

      if (lx < 8 || ly < 10 || lx + tw > this.width - 8 || ly + th > this.height - 28) continue
      const box: RectBox = { x1: lx - 4, y1: ly - 3, x2: lx + tw + 4, y2: ly + th + 3 }
      const collides = placed.some(pb => !(box.x2 < pb.x1 || box.x1 > pb.x2 || box.y2 < pb.y1 || box.y1 > pb.y2))
      if (collides && !c.isHov && !c.isSel) continue
      placed.push(box)

      ctx.beginPath()
      ctx.moveTo(c.rc.x, c.rc.y - 3)
      ctx.lineTo(c.rc.x, ly + th)
      ctx.strokeStyle = c.isSel || c.isHov ? '#0284c7' : 'rgba(15, 23, 42, 0.18)'
      ctx.lineWidth = 1
      ctx.stroke()

      roundRectPath(ctx, lx, ly, tw, th, 7)
      ctx.fillStyle = c.isSel || c.isHov ? '#0c4a6e' : 'rgba(255, 255, 255, 0.92)'
      ctx.shadowColor = 'rgba(15, 23, 42, 0.1)'
      ctx.shadowBlur = 8
      ctx.shadowOffsetY = 2
      ctx.fill()
      ctx.shadowColor = 'transparent'
      ctx.strokeStyle = c.isSel || c.isHov ? '#38bdf8' : 'rgba(15, 23, 42, 0.08)'
      ctx.lineWidth = 1
      ctx.stroke()

      ctx.fillStyle = c.isSel || c.isHov ? '#ffffff' : '#0f172a'
      ctx.textAlign = 'left'
      ctx.textBaseline = 'middle'
      ctx.fillText(c.rc.b.module.name, lx + 7, ly + th / 2 + 0.5)

      if (metricTag) {
        const nameW = ctx.measureText(`${c.rc.b.module.name}  `).width
        ctx.fillStyle = c.isSel || c.isHov ? '#bae6fd' : '#0284c7'
        ctx.fillText(metricTag, lx + 7 + nameW, ly + th / 2 + 0.5)
      }
    }
    ctx.restore()
  }
}
