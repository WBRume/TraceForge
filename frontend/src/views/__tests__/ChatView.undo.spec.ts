import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { expect, it, vi } from 'vitest'
import ChatView from '../ChatView.vue'

const undoMessage = vi.fn()

vi.mock('@/composables/chat/useChatViewModel', () => ({
  useChatViewModel: () => ({
    route: { params: { wsId: 'workspace', taskId: 'task' } },
    currentTask: ref({ id: 'task' }),
    activePreInput: ref(null),
    activeHitlCards: [],
    taskListContainer: ref(null),
    chatWorkbenchMode: 'platform',
    engineRunning: false,
    isChatLocked: false,
    showThinking: false,
    thinkingContent: '',
    thinkingExpanded: false,
    hidePatchWorkflows: true,
    showDeleteTaskConfirm: false,
    isUndoing: ref(false),
    canUndoMessage: () => true,
    undoMessage,
    registerPlaybookEvent: vi.fn(),
    registerShareSuggestionNudge: vi.fn(),
  }),
}))

vi.mock('@/composables/chat/share/useShareFlows', () => ({
  useShareFlows: () => ({
    sessionShares: { shares: ref([]), sharesLoading: ref(false), creating: ref(false), revokingIds: ref([]) },
    shareSuggestions: { pendingCount: ref(0) },
  }),
}))

vi.mock('@/composables/chat/diagnosis/useDiagnosisPlaybook', () => ({
  useDiagnosisPlaybook: () => ({ run: null, busy: false, error: '', tail: '', canContinue: false }),
}))

vi.mock('@/composables/chat/diagnosis/useGuideSession', () => ({
  useGuideSession: () => ({ state: null, busy: false, error: '' }),
}))

vi.mock('@/components/task-create/NewTaskModal.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/chat/sections/spec/SpecSidebar.vue', () => ({ default: { template: '<div />' } }))

it('waits for confirmation before undoing a message and closes the dialog while undo runs', async () => {
  let finishUndo!: () => void
  undoMessage.mockImplementation(() => new Promise<void>(resolve => { finishUndo = resolve }))
  const wrapper = mount(ChatView, {
    shallow: true,
    global: {
      mocks: { $t: (key: string) => key },
      renderStubDefaultSlot: true,
      stubs: {
        ChatHistoryPanel: {
          template: `<button @click="$emit('undo-request', { id: 'message' })">撤销</button>`,
        },
        ConfirmActionModal: false,
        ContextWindowDrawer: { template: '<div />' },
        TaskSessionShareDialog: { template: '<div />' },
        TaskSkillsDrawer: { template: '<div />' },
        ChatExecutionInput: { template: '<div />' },
        teleport: true,
      },
    },
  })

  try {
    const undo = wrapper.findAll('button').find(button => button.text() === '撤销')!
    await undo.trigger('click')
    expect(wrapper.get('[role="dialog"]').text()).toContain('chat.undo.confirm_title')
    expect(undoMessage).not.toHaveBeenCalled()
    await wrapper.get('[role="dialog"] .btn-secondary').trigger('click')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(undoMessage).not.toHaveBeenCalled()

    await undo.trigger('click')
    await wrapper.get('[role="dialog"] .confirm-btn').trigger('click')
    expect(undoMessage.mock.calls).toEqual([[{ id: 'message' }]])
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  } finally {
    finishUndo?.()
    wrapper.unmount()
  }
})
