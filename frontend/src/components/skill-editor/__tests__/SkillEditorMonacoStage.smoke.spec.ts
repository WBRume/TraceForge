import { reactive } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SkillEditorMonacoStage from '@/components/skill-editor/SkillEditorMonacoStage.vue'
import type { SkillEditorViewModel } from '@/composables/useSkillEditorViewModel'

vi.mock('@guolao/vue-monaco-editor', () => ({
  VueMonacoEditor: {
    name: 'VueMonacoEditor',
    template: '<div data-testid="monaco-editor" />',
  },
  VueMonacoDiffEditor: {
    name: 'VueMonacoDiffEditor',
    template: '<div data-testid="monaco-diff-editor" />',
  },
}))

const createVmStub = (): SkillEditorViewModel => reactive({
  editorStageRef: null,
  handleEditorStagePointerDown: vi.fn(),
  activeFilePath: '',
  loadingFile: false,
  binaryFileMap: {} as Record<string, boolean>,
  isDiffMode: false,
  showLineReviewAvatars: false,
  lineAvatarSlots: [] as Array<Record<string, unknown>>,
  openReviewerPopover: vi.fn(),
  reviewerColor: vi.fn(() => '#000'),
  activeFileContent: '',
  activeLanguage: 'markdown',
  editorOptions: {},
  handleEditorMount: vi.fn(),
  diffPayload: {
    original: '',
    modified: '',
  },
  diffEditorOptions: {},
  avatarPopover: {
    visible: false,
    top: 0,
    left: 0,
    line: 1,
    userId: '',
  },
  avatarPopoverRef: null,
  popoverReviewerName: '',
  popoverReviewerAvatarSvg: null,
  popoverReviewerColor: '',
  closeAvatarPopover: vi.fn(),
  popoverLineReviewers: [] as Array<Record<string, unknown>>,
  switchPopoverReviewer: vi.fn(),
  activePopoverComments: [] as Array<Record<string, unknown>>,
  activeCommentId: '',
  pickPopoverComment: vi.fn(),
  formatDateTime: vi.fn(() => ''),
  canLineReview: false,
  selectedRange: null as null | Record<string, unknown>,
  inlineComposerPosition: {
    visible: false,
    top: 0,
    left: 0,
    maxWidth: 480,
  },
  commentBody: '',
  isInlineComposerFocused: false,
  clearSelectedRange: vi.fn(),
  canSubmitComment: false,
  commentSaving: false,
  submitComment: vi.fn(),
}) as unknown as SkillEditorViewModel

const mountStage = (vmStub?: SkillEditorViewModel) => mount(SkillEditorMonacoStage, {
  props: {
    vm: vmStub || createVmStub(),
  },
  global: {
    stubs: {
      SkillFileTabs: true,
      UserAvatar: true,
      Transition: false,
    },
    mocks: {
      $t: (key: string) => key,
    },
  },
})

describe('SkillEditorMonacoStage smoke', () => {
  it('renders empty hint when no active file', () => {
    const wrapper = mountStage()
    expect(wrapper.text()).toContain('skills.editor.file_tree_empty')
  })

  it('renders loading hint when file is loading', () => {
    const vm = createVmStub() as any
    vm.activeFilePath = 'SKILL.md'
    vm.loadingFile = true

    const wrapper = mountStage(vm)
    expect(wrapper.text()).toContain('skills.editor.loading')
  })

  it('renders binary hint when active file is binary in edit mode', () => {
    const vm = createVmStub() as any
    vm.activeFilePath = 'asset.bin'
    vm.binaryFileMap = { 'asset.bin': true }
    vm.isDiffMode = false

    const wrapper = mountStage(vm)
    expect(wrapper.text()).toContain('skills.editor.binary_file_hint')
  })

  it('renders monaco editor in edit mode and diff editor in diff mode', async () => {
    const vm = createVmStub() as any
    vm.activeFilePath = 'SKILL.md'
    vm.binaryFileMap = { 'SKILL.md': false }
    vm.isDiffMode = false
    const wrapper = mountStage(vm)

    expect(wrapper.find('[data-testid="monaco-editor"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="monaco-diff-editor"]').exists()).toBe(false)

    vm.isDiffMode = true
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[data-testid="monaco-diff-editor"]').exists()).toBe(true)
  })
})
