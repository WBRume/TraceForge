import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { effectScope, shallowRef } from 'vue'
import { type ChatDraftScope, useChatTextDraft } from '../useChatTextDraft'

const taskA: ChatDraftScope = ['https://traceforge.example', 'user-a', 'workspace-a', 'task-a']
const scopes: ReturnType<typeof effectScope>[] = []

beforeEach(() => localStorage.clear())
afterEach(() => scopes.splice(0).forEach(scope => scope.stop()))

function openDraft(initialScope = taskA) {
  const identity = shallowRef<ChatDraftScope | null>(initialScope)
  const scope = effectScope()
  scopes.push(scope)
  const draft = scope.run(() => useChatTextDraft(() => identity.value))!
  return { draft, identity, close: () => scope.stop() }
}

describe('task conversation text drafts', () => {
  it('restores the exact text after reopening and removes a manually cleared draft', () => {
    const original = openDraft()
    original.draft.set('  待续\n第二行  ')
    original.close()

    const reopened = openDraft()
    expect(reopened.draft.current.value.content).toBe('  待续\n第二行  ')
    reopened.draft.set('')
    reopened.close()

    expect(openDraft().draft.current.value.content).toBe('')
    expect(localStorage.length).toBe(0)
  })

  it('uses independent drafts for each task, workspace, account and server', () => {
    const { draft, identity } = openDraft()
    draft.set('任务 A 草稿')
    const otherScopes: ChatDraftScope[] = [
      [taskA[0], taskA[1], taskA[2], 'task-b'],
      [taskA[0], taskA[1], 'workspace-b', taskA[3]],
      [taskA[0], 'user-b', taskA[2], taskA[3]],
      ['https://other.example', taskA[1], taskA[2], taskA[3]],
    ]
    for (const [index, otherScope] of otherScopes.entries()) {
      identity.value = otherScope
      expect(draft.current.value.content).toBe('')
      draft.set(`草稿 ${index}`)
    }
    identity.value = null
    expect(draft.current.value.content).toBe('')
    identity.value = taskA
    expect(draft.current.value.content).toBe('任务 A 草稿')
  })

  it('keeps newer text when the original draft is accepted', () => {
    const { draft } = openDraft()
    draft.set('原文')
    const submitted = draft.current.value
    openDraft().draft.set('新的草稿')
    draft.clearSent(submitted)

    expect(draft.current.value.content).toBe('新的草稿')
    expect(openDraft().draft.current.value.content).toBe('新的草稿')
  })
})
