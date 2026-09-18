import { describe, expect, it, vi } from 'vitest'

vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

import { useEngineState } from '../runtime/useEngineState'

const createEngine = () => {
  const statusCards: any[] = []
  let hasExecuting = false
  const engine = useEngineState({
    getStatusCards: () => statusCards,
    onStatusCardPush: (card) => statusCards.push(card),
    onStatusCardsDrop: () => { statusCards.length = 0 },
    hasExecutingJob: () => hasExecuting,
  })
  return {
    engine,
    statusCards,
    setExecuting: (value: boolean) => { hasExecuting = value },
  }
}

describe('useEngineState', () => {
  it('applies thinking frames with sequence guard and delta append', () => {
    const { engine } = createEngine()

    engine.applyThinkingFrame({ sequence: 2, content: 'hello ' })
    engine.applyThinkingFrame({ sequence: 1, content: 'stale' }) // 乱序丢弃
    engine.applyThinkingFrame({ sequence: 3, delta: 'world' })

    expect(engine.thinkingContent.value).toBe('hello world')
    expect(engine.showThinking.value).toBe(true)
    expect(engine.thinkingExpanded.value).toBe(false)
  })

  it('converges runtime panels when no job is executing and seeds a status card otherwise', () => {
    const { engine, statusCards, setExecuting } = createEngine()

    setExecuting(true)
    engine.convergeFromJobs('t1', [
      { id: 'j1', status: 'RUNNING', progress: 10, session_id: 's1', context_json: { model: 'm1' }, created_at: 'now' },
    ] as any)
    expect(statusCards).toHaveLength(1)
    expect(statusCards[0]).toMatchObject({ id: 'job-status-j1', status: 'INIT', model: 'm1' })

    setExecuting(false)
    engine.engineRunning.value = true
    engine.thinkingContent.value = 'partial'
    expect(engine.convergeFromJobs('t1', [{ id: 'j2', status: 'SUCCESS', progress: 100 }] as any)).toBe(true)
    expect(engine.engineRunning.value).toBe(false)
    expect(engine.thinkingContent.value).toBe('')
    expect(statusCards).toHaveLength(0)
  })

  it('persists and restores the runtime panel per task', () => {
    const { engine, statusCards, setExecuting } = createEngine()

    setExecuting(false)
    engine.engineRunning.value = true
    engine.thinkingContent.value = 'snapshot'
    engine.showThinking.value = true
    engine.thinkingExpanded.value = true
    statusCards.push({ id: 's1', type: 'status', status: 'RUNNING' })
    engine.persistForTask('t1')

    // 离开后恢复：思考面板与引擎态回到快照，状态卡交还调用方
    engine.resetThinking()
    engine.engineRunning.value = false
    const restoredCards = engine.restoreForTask('t1')
    expect(restoredCards).toEqual([{ id: 's1', type: 'status', status: 'RUNNING' }])
    expect(engine.thinkingContent.value).toBe('snapshot')
    expect(engine.engineRunning.value).toBe(true)
  })

  it('does not persist an idle session and clears the stale snapshot instead', () => {
    const { engine, setExecuting } = createEngine()
    setExecuting(false)
    engine.engineRunning.value = false
    engine.persistForTask('t2')
    expect(engine.restoreForTask('t2')).toEqual([])
  })
})
