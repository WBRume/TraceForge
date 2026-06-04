import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import TaskSkillsDrawer from '@/components/chat/TaskSkillsDrawer.vue'

vi.mock('@/utils/monaco', () => ({
  ensureMonacoViteSetup: vi.fn(),
}))

vi.mock('@guolao/vue-monaco-editor', () => ({
  VueMonacoEditor: {
    name: 'VueMonacoEditor',
    template: '<div data-test="monaco-editor"></div>',
  },
}))

vi.mock('@/components/AppSideDrawer.vue', () => ({
  default: {
    name: 'AppSideDrawer',
    props: ['show', 'title'],
    template: '<section v-if="show"><slot name="icon" /><slot name="actions" /><slot /></section>',
  },
}))

vi.mock('@/components/chat/SkillRuntimeTracePanel.vue', () => ({
  default: {
    name: 'SkillRuntimeTracePanel',
    props: ['skills', 'selectedSkillId', 'events', 'loading'],
    template: '<div data-test="runtime-trace-panel"></div>',
  },
}))

const mountDrawer = () => mount(TaskSkillsDrawer, {
  props: {
    show: true,
    loading: false,
    skills: [
      {
        skill_id: 'skill-1',
        name: 'checklist-ender',
        dimension: 'WORKSPACE',
        publish_state: 'PUBLISHED',
        materialized_dir: 'checklist-ender',
        usage: { is_used: true, used_count: 1, last_used_at: '2026-04-29T10:00:00Z' },
      },
    ],
    selectedSkillId: 'skill-1',
    canEdit: true,
    fileTree: [
      {
        path: 'SKILL.md',
        name: 'SKILL.md',
        node_type: 'file',
      },
    ],
    fileTreeLoading: false,
    activeFilePath: 'SKILL.md',
    activeFileContent: '# Skill',
    activeFileLoading: false,
    activeFileSaving: false,
    activeFileBinary: false,
    activeFileDirty: true,
    traceEvents: [],
    traceLoading: false,
  },
  global: {
    mocks: {
      $t: (key: string, params?: Record<string, unknown>) => (
        key === 'chat.task_skills_used_tag' ? `used ${params?.count}` : key
      ),
    },
  },
})

describe('TaskSkillsDrawer', () => {
  it('keeps runtime skill file tree visible and opens trace only on demand', async () => {
    const wrapper = mountDrawer()
    const fileBrowserPanel = wrapper.find('.file-browser-panel')

    expect(wrapper.text()).toContain('chat.task_skills_file_tree')
    expect(fileBrowserPanel.exists()).toBe(true)
    expect(fileBrowserPanel.text()).toContain('SKILL.md')
    expect(wrapper.text()).toContain('common.save')
    expect(wrapper.find('[data-test="monaco-editor"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="runtime-trace-panel"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('used 1')

    await wrapper.find('.trace-trigger').trigger('click')

    expect(wrapper.find('.trace-inspector').exists()).toBe(true)
    expect(wrapper.find('.trace-inspector [data-test="runtime-trace-panel"]').exists()).toBe(true)

    await wrapper.find('.trace-inspector .icon-btn').trigger('click')

    expect(wrapper.find('[data-test="runtime-trace-panel"]').exists()).toBe(false)
  })
})
