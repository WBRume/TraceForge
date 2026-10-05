import { describe, expect, it, vi } from 'vitest'
import { defineComponent, reactive } from 'vue'
import { mount } from '@vue/test-utils'
import { useTaskList } from '../useTaskList'
import type { TaskRailView } from '@/types/taskRail'

const api = vi.hoisted(() => ({ get:vi.fn(), put:vi.fn(), delete:vi.fn() }))
vi.mock('@/utils/api', () => ({ default:api }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t:(key:string) => key }) }))

function harness() {
  const filter = reactive<{ view:TaskRailView; requirementId?:string }>({ view:'all' })
  let list!:ReturnType<typeof useTaskList>
  const wrapper = mount(defineComponent({ setup() {
    list = useTaskList({ getWorkspaceId:() => 'workspace', selectRouteTask:vi.fn(), canCreateTask:() => true, getRailFilter:() => filter })
    return () => null
  } }))
  return { list, filter, wrapper }
}

describe('task list rail filters', () => {
  it('ignores old responses, resets pagination and prevents route tasks leaking into a filtered list', async () => {
    const { list, filter, wrapper } = harness()
    let finishOld!:(value:unknown) => void
    api.get.mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve }))
    const oldRequest = list.loadTasks()
    filter.view = 'requirement'
    filter.requirementId = 'req-101'
    api.get.mockResolvedValueOnce({ data:{ items:[{ id:'new' }], has_more:true } })
    await list.loadTasks({ trySelectRouteTask:false })
    finishOld({ data:{ items:[{ id:'stale' }], has_more:false } })
    await oldRequest
    expect(list.tasks.value.map((task) => task.id)).toEqual(['new'])
    expect(api.get.mock.calls[1]?.[1].params).toMatchObject({ requirement_id:'req-101', page:1 })
    list.upsertTask({ id:'unrelated' })
    expect(list.tasks.value.map((task) => task.id)).toEqual(['new'])
    api.get.mockResolvedValueOnce({ data:{ items:[{ id:'next' }], has_more:false } })
    await list.loadMoreTasks()
    expect(api.get.mock.calls[2]?.[1].params.page).toBe(2)
    filter.view = 'independent'
    api.get.mockResolvedValueOnce({ data:{ items:[], has_more:false } })
    await list.loadTasks({ trySelectRouteTask:false })
    expect(api.get.mock.calls[3]?.[1].params).toMatchObject({ independent:'true', page:1 })
    expect(list.tasks.value).toEqual([])
    expect(list.taskListHasMore.value).toBe(false)
    wrapper.unmount()
  })

  it('removes an unfavorited task and refills the current-user favorite view', async () => {
    const { list, filter, wrapper } = harness()
    filter.view = 'following'
    list.tasks.value = [{ id:'favorite', is_following:true }]
    api.delete.mockResolvedValueOnce({ data:{ is_following:false } })
    api.get.mockResolvedValueOnce({ data:{ items:[], has_more:false } })
    expect(await list.toggleTaskFollow(list.tasks.value[0])).toBe(false)
    expect(list.tasks.value).toEqual([])
    expect(api.get.mock.calls.at(-1)?.[1].params).toMatchObject({ following:'true' })
    wrapper.unmount()
  })

  it('preserves existing tasks during reload to avoid jumping to empty loading state', async () => {
    const { list, wrapper } = harness()
    list.tasks.value = [{ id: 'task-1' }, { id: 'task-2' }]
    let resolveReload!: (value: unknown) => void
    api.get.mockImplementationOnce(() => new Promise((resolve) => { resolveReload = resolve }))
    const flight = list.loadTasks({ trySelectRouteTask: false })
    // While loading in flight, tasks must NOT be wiped out to []
    expect(list.taskListLoading.value).toBe(true)
    expect(list.tasks.value).toHaveLength(2)

    resolveReload({ data: { items: [{ id: 'task-1' }], has_more: false } })
    await flight
    expect(list.tasks.value).toEqual([{ id: 'task-1' }])

    // Explicit clear: true wipes immediately
    api.get.mockImplementationOnce(() => new Promise(() => {}))
    void list.loadTasks({ clear: true })
    expect(list.tasks.value).toEqual([])
    wrapper.unmount()
  })
})
