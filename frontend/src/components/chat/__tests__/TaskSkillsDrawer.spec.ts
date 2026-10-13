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
    expect(wrapper.find('.trace-panel').exists()).toBe(false)
    expect(wrapper.text()).toContain('used 1')

    await wrapper.find('.trace-trigger').trigger('click')

    expect(wrapper.find('.trace-inspector').exists()).toBe(true)
    expect(wrapper.find('.trace-inspector .trace-panel').exists()).toBe(true)
    expect(wrapper.find('.trace-inspector').text().match(/使用证据链/g)).toHaveLength(1)
    expect(wrapper.text()).not.toContain('Runtime Evidence Trace')
    expect(wrapper.find('.trace-boundary').exists()).toBe(false)

    await wrapper.find('.trace-refresh').trigger('click')
    expect(wrapper.emitted('refreshTrace')).toHaveLength(1)

    await wrapper.find('.trace-inspector [aria-label="common.close"]').trigger('click')

    expect(wrapper.find('.trace-panel').exists()).toBe(false)
    wrapper.unmount()
  })

  it('uses the shared three-stage expand, collapse, and close controls', async () => {
    const wrapper = mountDrawer()
    expect(wrapper.find('.side-drawer-panel').classes()).toContain('level-2')
    await wrapper.find('.expand-btn').trigger('click')
    expect(wrapper.find('.side-drawer-panel').classes()).toContain('level-3')
    expect(wrapper.find('.expand-btn').attributes('disabled')).toBeDefined()
    await wrapper.find('.collapse-btn').trigger('click')
    await wrapper.find('.collapse-btn').trigger('click')
    expect(wrapper.find('.side-drawer-panel').classes()).toContain('level-1')
    await wrapper.find('.collapse-btn').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })
})
