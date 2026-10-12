import { expect, it, vi } from 'vitest'
import { defineComponent, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { useCollaborationLeave } from '../useCollaborationLeave'
import type { LocalCollaboration } from '../useLocalCollaboration'

it('holds route changes for confirmation, cancels safely, and releases before both task switches and exits', async () => {
  const participating = ref(true), busy = ref(false), leaving = ref(false)
  const leave = vi.fn(async () => { participating.value = false; return true })
  let guard!: ReturnType<typeof useCollaborationLeave>
  const Chat = defineComponent({ setup() {
    guard = useCollaborationLeave({participating, busy, leaving, leave} as unknown as LocalCollaboration)
    return () => null
  } })
  const router = createRouter({ history: createMemoryHistory(), routes: [
    {path: '/chat/:taskId', component: Chat}, {path: '/elsewhere', component: {template: '<div />'}},
  ] })
  await router.push('/chat/one'); await router.isReady()
  const wrapper = mount(RouterView, {global: {plugins: [router]}})
  const first = router.push('/chat/two'); await flushPromises()
  expect(guard.show.value).toBe(true)
  expect(router.currentRoute.value.path).toBe('/chat/one')
  guard.cancel(); await first
  expect(leave).not.toHaveBeenCalled()
  const second = router.push('/chat/two'); await flushPromises()
  busy.value = true; await guard.confirm(); expect(leave).not.toHaveBeenCalled()
  busy.value = false; await guard.confirm(); await second
  expect(router.currentRoute.value.path).toBe('/chat/two')
  expect(leave).toHaveBeenCalledOnce()
  participating.value = true
  const third = router.push('/elsewhere'); await flushPromises()
  expect(guard.show.value).toBe(true)
  await guard.confirm(); await third
  expect(leave).toHaveBeenCalledTimes(2)
  wrapper.unmount()
})
