import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { computed, defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import api from '@/utils/api'
import { useSkillAnalysisStore } from '@/stores/skillAnalysis'
import { useSkillAnalysis } from '@/composables/skill-editor/useSkillAnalysis'
import type { SkillAnalysis } from '@/types/skillAnalysis'

vi.mock('@/utils/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }))
const result = (status: SkillAnalysis['status'] = 'RUNNING', id = 'analysis'): SkillAnalysis => ({
  id, skill_id: 'skill', workspace_id: 'workspace', created_by_id: 'user', ref_kind: 'WORKTREE',
  status, progress: status === 'SUCCESS' ? 100 : 60, created_at: '2026-11-07T00:00:00',
  file_stats: {}, file_type_distribution: {}, key_files: [], risk_items: [], review_suggestions: [],
})

beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks(); localStorage.clear() })
afterEach(() => { vi.useRealTimers() })

describe('skill analysis background state', () => {
  it('does not reopen historical results or a dismissed completion', () => {
    const store = useSkillAnalysisStore()
    store.ingest(result('SUCCESS'))
    expect(store.jobs).toHaveLength(0)
    store.ingest(result('RUNNING', 'new'), true)
    store.ingest(result('SUCCESS', 'new'), true)
    expect(store.jobs[0]).toMatchObject({ terminal: true, domain_milestones: [] })
    store.dismiss('new')
    store.ingest(result('SUCCESS', 'new'), true)
    expect(store.jobs).toHaveLength(0)
  })

  it('keeps notifications newer than a delayed create or resync response', async () => {
    const store = useSkillAnalysisStore()
    store.ingest(result(), true)
    let finish!: (value: unknown) => void
    vi.mocked(api.get).mockImplementation(url => url.endsWith('/active')
      ? Promise.resolve({ data: [] }) : new Promise(resolve => { finish = resolve }))
    const refresh = store.refresh()
    store.ingest(result('SUCCESS'), true)
    finish({ data: result() })
    await refresh
    store.ingest({ ...result(), status: 'PENDING', progress: 0 }, true)
    expect(store.analyses.analysis.status).toBe('SUCCESS')
  })

  it('restores on connection events, coalesces reads and never polls', async () => {
    vi.useFakeTimers()
    const store = useSkillAnalysisStore()
    vi.mocked(api.get).mockResolvedValue({ data: [result()] })
    await Promise.all([store.refresh(), store.refresh()])
    expect(store.jobs[0]?.terminal).toBe(false)
    expect(api.get).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(60000)
    expect(api.get).toHaveBeenCalledTimes(1)
  })

  it('discards an old user snapshot after logout', async () => {
    const store = useSkillAnalysisStore()
    let finish!: (value: unknown) => void
    vi.mocked(api.get).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const refresh = store.refresh()
    store.reset()
    finish({ data: [result()] })
    await refresh
    expect(store.jobs).toHaveLength(0)
    expect(store.analyses).toEqual({})
  })

  it('subscribes the editor to shared state and retains a job after leaving without polling', async () => {
    vi.useFakeTimers()
    const store = useSkillAnalysisStore()
    const skillId = ref('skill')
    let editor!: ReturnType<typeof useSkillAnalysis>
    const wrapper = mount(defineComponent({ setup() {
      editor = useSkillAnalysis({ t: key => key, actionError: ref(''),
        skillId: computed(() => skillId.value), selectedWorkspaceId: ref('workspace'),
        hasPendingWorktreeChanges: ref(true), latestVersionId: ref(''), viewVersionId: ref('') })
      return () => null
    } }))
    vi.mocked(api.post).mockResolvedValue({ data: result() })
    await editor.runAnalysis()
    expect(editor.analysisRunning.value).toBe(true)
    store.ingest(result('SUCCESS'), true)
    expect(editor.latestAnalysis.value?.status).toBe('SUCCESS')
    expect(editor.analysisRunning.value).toBe(false)
    expect(store.jobs).toHaveLength(1)
    vi.mocked(api.post).mockResolvedValue({ data: result('RUNNING', 'second') })
    await editor.runAnalysis()
    wrapper.unmount()
    store.ingest(result('SUCCESS', 'second'), true)
    await vi.advanceTimersByTimeAsync(60000)
    expect(api.get).not.toHaveBeenCalled()
    expect(store.jobs.every(job => job.terminal)).toBe(true)
  })

  it('does not apply a previous skill response to a newly selected skill', async () => {
    const skillId = ref('skill')
    let editor!: ReturnType<typeof useSkillAnalysis>
    const wrapper = mount(defineComponent({ setup() {
      editor = useSkillAnalysis({ t: key => key, actionError: ref(''),
        skillId: computed(() => skillId.value), selectedWorkspaceId: ref('workspace'),
        hasPendingWorktreeChanges: ref(true), latestVersionId: ref(''), viewVersionId: ref('') })
      return () => null
    } }))
    let finish!: (value: unknown) => void
    vi.mocked(api.get).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const loading = editor.loadLatestAnalysis()
    skillId.value = 'another'
    finish({ data: result('SUCCESS') })
    await loading
    await flushPromises()
    expect(editor.latestAnalysis.value).toBeNull()
    expect(editor.analysisLoading.value).toBe(false)
    wrapper.unmount()
  })
})
