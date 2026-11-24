import { describe, expect, it, vi } from 'vitest'
import { ArchitecturalDioramaEngine, squarifyBlocks } from '../dioramaEngine'
import { convexHull, pointInPoly, resolveBuildingMaterial } from '../dioramaGeometry'
import type { DashboardDioramaPayload, DioramaRepoItem } from '@/types/dashboardDiorama'

function createMockContext(): CanvasRenderingContext2D {
  const grad = { addColorStop: vi.fn() }
  return {
    save: vi.fn(),
    restore: vi.fn(),
    scale: vi.fn(),
    fillRect: vi.fn(),
    beginPath: vi.fn(),
    closePath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    arc: vi.fn(),
    arcTo: vi.fn(),
    ellipse: vi.fn(),
    quadraticCurveTo: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    setLineDash: vi.fn(),
    fillText: vi.fn(),
    measureText: vi.fn((text: string) => ({ width: text.length * 6.5 })),
    createLinearGradient: vi.fn(() => grad),
    createRadialGradient: vi.fn(() => grad),
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 1,
    lineDashOffset: 0,
    globalAlpha: 1,
    shadowColor: '',
    shadowBlur: 0,
    shadowOffsetY: 0,
    filter: '',
    font: '',
    textAlign: 'left',
    textBaseline: 'alphabetic',
  } as unknown as CanvasRenderingContext2D
}

function makeRepo(id: string, name: string, moduleCount: number, available = true): DioramaRepoItem {
  const modules = Array.from({ length: moduleCount }, (_, idx) => ({
    id: `${id}/mod-${idx}`,
    repo_id: id,
    name: `mod-${idx}`,
    loc: (idx + 1) * 420,
    file_count: idx + 2,
    commits: idx + 1,
    added: (idx + 1) * 35,
    deleted: (idx + 1) * 10,
    recent_commits: [],
    files: [
      {
        path: `mod-${idx}/index.ts`,
        name: 'index.ts',
        loc: (idx + 1) * 420,
        lang: 'ts',
        commits: idx + 1,
        added: 35,
        deleted: 10,
        last_date: '2026-11-20',
        is_aggregate: false,
        file_count: 1,
      },
    ],
  }))
  const loc = modules.reduce((acc, m) => acc + m.loc, 0)
  return {
    id,
    name,
    slug: name,
    branch: 'main',
    state: available ? 'READY' : 'PENDING',
    color: '#0ea5e9',
    loc,
    file_count: modules.reduce((acc, m) => acc + m.file_count, 0),
    module_count: modules.length,
    available,
    modules,
  }
}

function makePayload(repos: DioramaRepoItem[]): DashboardDioramaPayload {
  const firstModId = repos[0]?.modules[0]?.id ?? 'r1/mod-0'
  return {
    workspace_id: 'ws-test',
    workspace_name: 'TraceForge Test',
    days: 30,
    date_range: ['2026-11-19', '2026-11-20'],
    total_loc: repos.reduce((acc, r) => acc + r.loc, 0),
    total_files: repos.reduce((acc, r) => acc + r.file_count, 0),
    total_modules: repos.reduce((acc, r) => acc + r.module_count, 0),
    total_commits: 5,
    repos,
    members: [
      {
        id: 'u1',
        display_name: 'Alice',
        email: 'alice@example.com',
        role: 'OWNER',
        color: '#0284c7',
      },
    ],
    tasks: [
      {
        id: 't1',
        name: 'Build diorama',
        status: 'RUNNING',
        task_type: 'FEATURE',
        creator_id: 'u1',
        creator_name: 'Alice',
        requirement_ids: ['req-1'],
        requirement_titles: ['2.5D Diorama'],
        repos: repos.map(r => r.id),
        modules: [firstModId],
        primary_modules: [firstModId],
        files: [],
        added: 120,
        deleted: 18,
        updated_at: '2026-11-20T10:00:00Z',
      },
    ],
    timeline: [
      {
        date: '2026-11-19',
        commit_count: 2,
        total_churn: 80,
        commits: [],
        module_heat: {
          [firstModId]: { commits: 2, added: 60, deleted: 20 },
        },
      },
      {
        date: '2026-11-20',
        commit_count: 3,
        total_churn: 140,
        commits: [],
        module_heat: {
          [firstModId]: { commits: 3, added: 110, deleted: 30 },
        },
      },
    ],
    generated_at: '2026-11-20T12:00:00Z',
  }
}

describe('dioramaGeometry', () => {
  it('conserves area and stays within bounds for squarifyBlocks', () => {
    const rects = squarifyBlocks(
      [
        { ref: 'a', weight: 60 },
        { ref: 'b', weight: 30 },
        { ref: 'c', weight: 10 },
      ],
      10,
      20,
      200,
      100,
    )
    expect(rects).toHaveLength(3)
    const totalArea = rects.reduce((sum, r) => sum + r.w * r.h, 0)
    expect(totalArea).toBeCloseTo(200 * 100, 3)
    for (const r of rects) {
      expect(r.x).toBeGreaterThanOrEqual(9.999)
      expect(r.y).toBeGreaterThanOrEqual(19.999)
      expect(r.x + r.w).toBeLessThanOrEqual(210.001)
      expect(r.y + r.h).toBeLessThanOrEqual(120.001)
      expect(r.w).toBeGreaterThan(0)
      expect(r.h).toBeGreaterThan(0)
    }
  })

  it('handles empty, zero-weight, and single-item squarify inputs safely', () => {
    expect(squarifyBlocks([], 0, 0, 100, 100)).toEqual([])
    expect(squarifyBlocks([{ ref: 'x', weight: 0 }], 0, 0, 100, 100)).toEqual([])
    const single = squarifyBlocks([{ ref: 'only', weight: 42 }], -50, -50, 100, 80)
    expect(single).toEqual([{ ref: 'only', x: -50, y: -50, w: 100, h: 80 }])
  })

  it('computes convex hull and point-in-polygon checks accurately', () => {
    const square = [
      { x: 0, y: 0 },
      { x: 10, y: 0 },
      { x: 5, y: 5 },
      { x: 10, y: 10 },
      { x: 0, y: 10 },
    ]
    const hull = convexHull(square)
    expect(hull).toHaveLength(4)
    expect(pointInPoly(5, 5, hull)).toBe(true)
    expect(pointInPoly(15, 5, hull)).toBe(false)
  })

  it('resolves light-mode TraceForge material tokens', () => {
    const calm = resolveBuildingMaterial(0, false, false, false, false)
    const active = resolveBuildingMaterial(0.85, false, false, false, false)
    const dimmed = resolveBuildingMaterial(0.5, true, false, false, false)
    expect(calm.top).toBe('#ffffff')
    expect(calm.floorLines).toBeNull()
    expect(active.floorLines).toContain('rgba(255, 255, 255')
    expect(dimmed.top).toBe('#f8fafc')
  })
})

describe('ArchitecturalDioramaEngine', () => {
  function mountEngine(payload: DashboardDioramaPayload) {
    const ctx = createMockContext()
    const canvas = document.createElement('canvas')
    vi.spyOn(canvas, 'getContext').mockReturnValue(ctx)
    const viewport = document.createElement('div')
    vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue({
      width: 960,
      height: 540,
      top: 0,
      left: 0,
      right: 960,
      bottom: 540,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    })

    let rafCb: FrameRequestCallback | null = null
    const rafSpy = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
      rafCb = cb
      return 77
    })
    const cancelSpy = vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {})

    const onSelect = vi.fn()
    const onDrillChange = vi.fn()
    const engine = new ArchitecturalDioramaEngine(canvas, viewport, payload, {
      pendingRepoLabel: 'Pending sync',
      onSelect,
      onDrillChange,
    })

    const flushFrame = (ts = 16) => {
      const cb = rafCb
      rafCb = null
      if (cb) cb(ts)
    }

    return { engine, ctx, canvas, viewport, rafSpy, cancelSpy, onSelect, onDrillChange, flushFrame }
  }

  it('adapts layout dynamically across 1, 2, and 4 repositories including pending repos', () => {
    const single = mountEngine(makePayload([makeRepo('r1', 'core', 3)]))
    expect(single.engine.getPlinthCount()).toBe(1)
    expect(single.engine.getBuildingCount()).toBe(3)
    single.flushFrame(16)
    expect(single.ctx.fillRect).toHaveBeenCalled()
    single.engine.destroy()

    const multi = mountEngine(makePayload([
      makeRepo('r1', 'frontend', 4),
      makeRepo('r2', 'backend', 3),
      makeRepo('r3', 'gateway', 2),
      makeRepo('r4', 'docs-sync', 0, false),
    ]))
    expect(multi.engine.getPlinthCount()).toBe(4)
    expect(multi.engine.getBuildingCount()).toBe(9)
    multi.flushFrame(16)
    expect(multi.ctx.fillText).toHaveBeenCalledWith('docs-sync · Pending sync', expect.any(Number), expect.any(Number))

    multi.engine.setEnabledRepos(new Set(['r1', 'r2']))
    expect(multi.engine.getPlinthCount()).toBe(2)
    expect(multi.engine.getBuildingCount()).toBe(7)
    multi.engine.destroy()
  })

  it('supports metric, isoMode, timeline, focusEntity, and clean destroy()', () => {
    const payload = makePayload([makeRepo('r1', 'api', 2), makeRepo('r2', 'web', 2)])
    const removeWinSpy = vi.spyOn(window, 'removeEventListener')
    const { engine, cancelSpy, onSelect, onDrillChange, flushFrame } = mountEngine(payload)

    engine.setMetric('loc')
    engine.setIsoMode('top')
    engine.setTimeline(0, 'day', true)
    engine.setHighlight('t1', null)
    engine.focusEntity('module', 'r1/mod-0')
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ kind: 'module', id: 'r1/mod-0' }))
    expect(onDrillChange).toHaveBeenCalledWith(expect.objectContaining({
      repo: expect.objectContaining({ id: 'r1' }),
      module: expect.objectContaining({ id: 'r1/mod-0' }),
    }))

    flushFrame(32)
    engine.destroy()

    expect(cancelSpy).toHaveBeenCalled()
    expect(removeWinSpy).toHaveBeenCalledWith('pointermove', expect.any(Function))
    expect(removeWinSpy).toHaveBeenCalledWith('pointerup', expect.any(Function))
  })
})
