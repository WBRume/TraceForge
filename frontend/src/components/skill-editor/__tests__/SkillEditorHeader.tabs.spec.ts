import { reactive } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SkillEditorHeader from '@/components/skill-editor/SkillEditorHeader.vue'
import type { SkillEditorViewModel } from '@/composables/useSkillEditorViewModel'

const createVm = (overrides: Record<string, unknown> = {}) => reactive({
  form: { dimension: 'GLOBAL' },
  pageTitle: 'Edit Skill',
  isEdit: true,
  activeEditorTab: 'files',
  navigateBack: vi.fn(),
  goEditorFilesTab: vi.fn(),
  goEditorAnalysisTab: vi.fn(),
  isUnpublishedSkill: false,
  isOfficialSourceSkill: false,
  canManage: true,
  sourceRepoUrl: '',
  canSyncOfficialSource: false,
  sourceSyncing: false,
  syncOfficialSource: vi.fn(),
  isReadOnly: false,
  readOnlyHintText: '',
  canSwitchToEdit: false,
  showSwitchToEditConfirm: false,
  switchToReadOnlyMode: vi.fn(),
  canSave: false,
  saving: false,
  saveSkill: vi.fn(),
  canPublish: false,
  publishing: false,
  openPublishConfirm: vi.fn(),
  ...overrides,
}) as unknown as SkillEditorViewModel

const mountHeader = (vm = createVm()) => mount(SkillEditorHeader, {
  props: { vm },
  global: {
    mocks: {
      $t: (key: string) => key,
    },
  },
})

describe('SkillEditorHeader tabs', () => {
  it('shows file and analysis tabs for existing skills', async () => {
    const vm = createVm()
    const wrapper = mountHeader(vm)

    expect(wrapper.text()).toContain('skills.editor.tab_files')
    expect(wrapper.text()).toContain('skills.editor.tab_analysis')
    expect(wrapper.find('.editor-tab.active').text()).toContain('skills.editor.tab_files')

    await wrapper.findAll('.editor-tab')[1].trigger('click')
    expect(vm.goEditorAnalysisTab).toHaveBeenCalledTimes(1)
  })

  it('does not show editor tabs on the new skill page', () => {
    const wrapper = mountHeader(createVm({ isEdit: false }))

    expect(wrapper.find('.editor-tabs').exists()).toBe(false)
  })
})
