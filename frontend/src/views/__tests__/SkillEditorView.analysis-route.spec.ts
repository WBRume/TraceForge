import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import SkillEditorView from '@/views/SkillEditorView.vue'

const state = vi.hoisted(() => ({
  vm: null as any,
}))

vi.mock('@/composables/useSkillEditorViewModel', () => ({
  useSkillEditorViewModel: () => state.vm,
}))

vi.mock('@/components/skill-editor/SkillEditorHeader.vue', () => ({
  default: { name: 'SkillEditorHeader', template: '<header data-test="editor-header"></header>' },
}))

vi.mock('@/components/skill-editor/SkillEditorWorkspace.vue', () => ({
  default: { name: 'SkillEditorWorkspace', template: '<section data-test="editor-workspace"></section>' },
}))

vi.mock('@/components/skill-editor/SkillEditorSidebar.vue', () => ({
  default: { name: 'SkillEditorSidebar', template: '<aside data-test="editor-sidebar"></aside>' },
}))

vi.mock('@/components/skill-editor/SkillEditorRightDrawer.vue', () => ({
  default: { name: 'SkillEditorRightDrawer', template: '<aside data-test="editor-right-drawer"></aside>' },
}))

vi.mock('@/components/skill-editor/SkillAnalysisPanel.vue', () => ({
  default: { name: 'SkillAnalysisPanel', template: '<section data-test="analysis-panel"></section>' },
}))

vi.mock('@/components/ConfirmActionModal.vue', () => ({
  default: {
    name: 'ConfirmActionModal',
    props: ['show'],
    template: '<div v-if="show"><slot name="content"></slot><slot></slot></div>',
  },
}))

vi.mock('@/components/BaseSelect.vue', () => ({
  default: { name: 'BaseSelect', template: '<select></select>' },
}))

vi.mock('@/components/user/UserAvatar.vue', () => ({
  default: { name: 'UserAvatar', template: '<span></span>' },
}))

const createVm = (overrides: Record<string, unknown> = {}) => ({
  loading: false,
  isAnalysisTabActive: false,
  isSidebarLayout: false,
  isEdit: true,
  showSwitchToEditConfirm: false,
  showPublishConfirm: false,
  showCreateNodeModal: false,
  showRenameNodeModal: false,
  showDeleteNodeConfirm: false,
  showRestoreConfirm: false,
  showRatingNotesModal: false,
  publishing: false,
  creatingNode: false,
  renamingNode: false,
  deletingNode: false,
  restoring: false,
  ratingNotesLoading: false,
  ratingNotes: [],
  pendingPublishNote: '',
  createNodeDialogTitle: '',
  createNodeParentPath: '',
  directoryOptions: [],
  createNodeName: '',
  createNodeNamePlaceholder: '',
  renameNodeDialogTitle: '',
  renameNodeSourcePath: '',
  renameNodeName: '',
  renameNodeNamePlaceholder: '',
  deleteNodePath: '',
  cancelPublishConfirm: vi.fn(),
  confirmPublish: vi.fn(),
  cancelCreateNode: vi.fn(),
  confirmCreateNode: vi.fn(),
  cancelRenameNode: vi.fn(),
  confirmRenameNode: vi.fn(),
  cancelDeleteNode: vi.fn(),
  confirmDeleteNode: vi.fn(),
  confirmRestoreVersion: vi.fn(),
  confirmSwitchToEditMode: vi.fn(),
  ...overrides,
})

const mountView = (vm: Record<string, unknown>) => {
  state.vm = vm
  return mount(SkillEditorView, {
    global: {
      mocks: {
        $t: (key: string) => key,
      },
    },
  })
}

describe('SkillEditorView analysis route', () => {
  it('renders the file editor area on the files tab', () => {
    const wrapper = mountView(createVm())

    expect(wrapper.find('[data-test="editor-workspace"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="editor-right-drawer"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="analysis-panel"]').exists()).toBe(false)
  })

  it('renders analysis as the main content and hides file editing chrome', () => {
    const wrapper = mountView(createVm({ isAnalysisTabActive: true }))

    expect(wrapper.find('[data-test="analysis-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="editor-workspace"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="editor-sidebar"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="editor-right-drawer"]').exists()).toBe(false)
  })
})
