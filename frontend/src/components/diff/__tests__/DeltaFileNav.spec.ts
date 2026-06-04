import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import DeltaFileNav from '../DeltaFileNav.vue'
import en from '@/locales/en.json'
import zh from '@/locales/zh.json'
import type { HumanDeltaFileDiff, DeltaRegion } from '@/types/workspaceAssets'

function i18nPlugin(locale = 'en') {
  return createI18n({
    legacy: false,
    locale,
    messages: { en, zh },
  })
}

function makeFileDiff(path: string, comparisonType: HumanDeltaFileDiff['comparison_type'] = 'common'): HumanDeltaFileDiff {
  return {
    file_path: path,
    change_type: 'modified',
    comparison_type: comparisonType,
    insertions: 5,
    deletions: 2,
    hunks: [],
    ai_insertions: 3,
    ai_deletions: 1,
    human_insertions: 4,
    human_deletions: 2,
    ai_hunks: [],
    human_hunks: [],
  }
}

function makeRegion(
  filePath: string,
  source: DeltaRegion['region_source'] = 'AI_ONLY',
  type: DeltaRegion['region_type'] = 'HUNK_MODIFIED',
): DeltaRegion {
  return {
    id: `region-${filePath}-${source}`,
    delta_id: 'delta-1',
    file_path: filePath,
    region_type: type,
    region_source: source,
    ai_line_start: 1,
    ai_line_end: 10,
    human_line_start: null,
    human_line_end: null,
    ai_insertions: 5,
    ai_deletions: 2,
    human_insertions: 0,
    human_deletions: 0,
    summary: null,
    decisions: [],
  }
}

describe('DeltaFileNav', () => {
  it('groups files by directory path', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [
          makeFileDiff('src/components/Foo.vue', 'common'),
          makeFileDiff('src/components/Bar.vue', 'common'),
          makeFileDiff('src/utils/helper.ts', 'ai_only'),
          makeFileDiff('README.md', 'human_only'),
        ],
        deltaRegions: [],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    const dirHeaders = wrapper.findAll('.dir-header')
    const dirNames = dirHeaders.map(h => h.find('.dir-name').text())
    expect(dirNames).toContain('src/components/')
    expect(dirNames).toContain('src/utils/')

    const fileItems = wrapper.findAll('.file-item')
    expect(fileItems).toHaveLength(4)
  })

  it('does not put common files in ai_only category', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [
          makeFileDiff('src/both.py', 'common'),
          makeFileDiff('src/only_ai.py', 'ai_only'),
        ],
        deltaRegions: [
          makeRegion('src/both.py', 'AI_ONLY'),
          makeRegion('src/only_ai.py', 'AI_ONLY'),
        ],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    const categoryHeaders = wrapper.findAll('.category-header')
    const categoryLabels = categoryHeaders.map(h => h.find('.category-label').text())

    expect(categoryLabels).toContain('Modified')
    expect(categoryLabels).toContain('AI Only')

    const modifiedHeader = categoryHeaders.find(h => h.find('.category-label').text() === 'Modified')
    expect(modifiedHeader?.find('.category-count').text()).toBe('1')

    const aiOnlyHeader = categoryHeaders.find(h => h.find('.category-label').text() === 'AI Only')
    expect(aiOnlyHeader?.find('.category-count').text()).toBe('1')
  })

  it('classifies FILE_DELETED region as Deleted category', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [makeFileDiff('src/old.ts', 'ai_only')],
        deltaRegions: [makeRegion('src/old.ts', 'AI_ONLY', 'FILE_DELETED')],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    const categoryLabels = wrapper.findAll('.category-label').map(h => h.text())
    expect(categoryLabels).toContain('Deleted')
  })

  it('classifies FILE_RENAMED region as Renamed category', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [makeFileDiff('src/newName.ts', 'ai_only')],
        deltaRegions: [makeRegion('src/newName.ts', 'AI_ONLY', 'FILE_RENAMED')],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    const categoryLabels = wrapper.findAll('.category-label').map(h => h.text())
    expect(categoryLabels).toContain('Renamed')
  })

  it('classifies FILE_REWRITTEN region as Rewritten category', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [makeFileDiff('src/rewritten.ts', 'human_only')],
        deltaRegions: [makeRegion('src/rewritten.ts', 'HUMAN_ONLY', 'FILE_REWRITTEN')],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    const categoryLabels = wrapper.findAll('.category-label').map(h => h.text())
    expect(categoryLabels).toContain('Rewritten')
  })

  it('classifies DIVERGED regions as Modified', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [makeFileDiff('src/conflict.ts', 'ai_only')],
        deltaRegions: [makeRegion('src/conflict.ts', 'DIVERGED')],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    const categoryLabels = wrapper.findAll('.category-label').map(h => h.text())
    expect(categoryLabels).toContain('Modified')
    expect(categoryLabels).not.toContain('AI Only')
  })

  it('classifies all AI_ONLY regions (non-common) as AI Only', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [makeFileDiff('src/ai.ts', 'ai_only')],
        deltaRegions: [
          makeRegion('src/ai.ts', 'AI_ONLY'),
          makeRegion('src/ai.ts', 'AI_ONLY'),
        ],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    const categoryLabels = wrapper.findAll('.category-label').map(h => h.text())
    expect(categoryLabels).toContain('AI Only')
    expect(categoryLabels).not.toContain('Modified')
  })

  it('classifies all HUMAN_ONLY regions as Human Only', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [makeFileDiff('src/human.ts', 'human_only')],
        deltaRegions: [makeRegion('src/human.ts', 'HUMAN_ONLY')],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    const categoryLabels = wrapper.findAll('.category-label').map(h => h.text())
    expect(categoryLabels).toContain('Human Only')
  })

  it('shows region count badge for files with regions', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [makeFileDiff('src/test.py', 'common')],
        deltaRegions: [
          makeRegion('src/test.py', 'DIVERGED'),
          makeRegion('src/test.py', 'BOTH_SAME'),
        ],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    const badge = wrapper.find('.region-badge')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('2')
  })

  it('does not show region badge for files without regions', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [makeFileDiff('src/noregion.py', 'common')],
        deltaRegions: [],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    expect(wrapper.find('.region-badge').exists()).toBe(false)
  })

  it('highlights selected file', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [
          makeFileDiff('a.py', 'common'),
          makeFileDiff('b.py', 'common'),
        ],
        deltaRegions: [],
        selectedFilePath: 'a.py',
      },
      global: { plugins: [i18nPlugin()] },
    })

    const fileItems = wrapper.findAll('.file-item')
    expect(fileItems[0].classes()).toContain('file-selected')
    expect(fileItems[1].classes()).not.toContain('file-selected')
  })

  it('emits select-file event on click', async () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [makeFileDiff('src/main.py', 'common')],
        deltaRegions: [],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    await wrapper.find('.file-item').trigger('click')
    expect(wrapper.emitted('select-file')).toHaveLength(1)
    expect(wrapper.emitted('select-file')![0]).toEqual(['src/main.py'])
  })

  it('sorts directory groups by name', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [
          makeFileDiff('z_dir/file.ts', 'common'),
          makeFileDiff('a_dir/file.ts', 'common'),
          makeFileDiff('m_dir/file.ts', 'common'),
        ],
        deltaRegions: [],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    const dirHeaders = wrapper.findAll('.dir-header')
    const dirNames = dirHeaders.map(h => h.find('.dir-name').text())
    expect(dirNames).toEqual(['a_dir/', 'm_dir/', 'z_dir/'])
  })

  it('shows file count in header', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [
          makeFileDiff('a.py', 'common'),
          makeFileDiff('b.py', 'common'),
          makeFileDiff('c.py', 'common'),
        ],
        deltaRegions: [],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    expect(wrapper.find('.file-count').text()).toBe('3')
  })

  it('displays category count correctly', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [
          makeFileDiff('src/a.py', 'common'),
          makeFileDiff('src/b.py', 'common'),
          makeFileDiff('src/c.py', 'ai_only'),
        ],
        deltaRegions: [],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    const categoryHeaders = wrapper.findAll('.category-header')
    const modifiedHeader = categoryHeaders.find(h => h.find('.category-label').text() === 'Modified')
    expect(modifiedHeader?.find('.category-count').text()).toBe('2')

    const aiOnlyHeader = categoryHeaders.find(h => h.find('.category-label').text() === 'AI Only')
    expect(aiOnlyHeader?.find('.category-count').text()).toBe('1')
  })

  it('handles root-level files without dir header', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [
          makeFileDiff('README.md', 'common'),
          makeFileDiff('package.json', 'common'),
        ],
        deltaRegions: [],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    expect(wrapper.findAll('.dir-header')).toHaveLength(0)
    expect(wrapper.findAll('.file-item')).toHaveLength(2)
  })

  it('classifies common comparisonType as Modified even with AI_ONLY regions', () => {
    const wrapper = mount(DeltaFileNav, {
      props: {
        fileDiffs: [makeFileDiff('src/shared.ts', 'common')],
        deltaRegions: [
          makeRegion('src/shared.ts', 'AI_ONLY'),
          makeRegion('src/shared.ts', 'AI_ONLY'),
          makeRegion('src/shared.ts', 'AI_ONLY'),
        ],
        selectedFilePath: null,
      },
      global: { plugins: [i18nPlugin()] },
    })

    const categoryHeaders = wrapper.findAll('.category-header')
    const labels = categoryHeaders.map(h => h.find('.category-label').text())
    expect(labels).toContain('Modified')
    expect(labels).not.toContain('AI Only')
  })
})
