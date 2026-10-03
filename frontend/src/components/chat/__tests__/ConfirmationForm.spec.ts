import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import ConfirmationForm from '../sections/ConfirmationForm.vue'
import HitlInteractionCard from '../sections/HitlInteractionCard.vue'
import TerminalStatusBlock from '../terminal/TerminalStatusBlock.vue'
import zh from '@/locales/zh.json'
import en from '@/locales/en.json'
import type { ConfirmationField, HitlCard } from '@/composables/chat/types'
import type { TerminalHitlEntry } from '@/utils/chat-terminal/timeline-types'

const fields: ConfirmationField[] = [
  { key: 'build', type: 'string', title: '构建工具', required: true, custom: true,
    options: [{ value: 'maven', label: 'Maven' }, { value: 'gradle', label: 'Gradle' }] },
  { key: 'components', type: 'multiselect', title: '组件', required: true,
    options: [{ value: 'web', label: 'Spring Web' }, { value: 'test', label: 'JUnit' }] },
  { key: 'java', type: 'integer', title: 'Java 版本', required: true, minimum: 8 },
  { key: 'docker', type: 'boolean', title: 'Docker 支持' },
]

const localization = () => createI18n({ legacy: false, locale: 'zh', messages: { zh, en } })
const mountForm = (formFields = fields) => mount(ConfirmationForm, {
  props: { fields: formFields, submitLabel: zh.chat.questionnaire_submit },
  global: { plugins: [localization()] },
})

describe('ConfirmationForm', () => {
  it('presents one question per page and submits all answers once with native value types', async () => {
    const wrapper = mountForm()
    expect(wrapper.findAll('fieldset')).toHaveLength(1)
    expect(wrapper.get('[role="status"]').text()).toBe('第 1 题 / 共 4 题')
    expect(wrapper.text()).not.toContain('Java 版本')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    await wrapper.get('button.field-option').trigger('click')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('submit')).toBeUndefined()
    const checkboxes = wrapper.findAll('input[type="checkbox"]')
    await checkboxes[0]!.setValue(true)
    await checkboxes[1]!.setValue(true)
    await wrapper.get('form').trigger('submit')
    await wrapper.get('input[type="number"]').setValue('21')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('button[type="submit"]').text()).toBe('提交答案')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('submit')).toHaveLength(1)
    expect(JSON.parse(String(wrapper.emitted('submit')![0]![0]))).toEqual({
      build: 'maven', components: ['web', 'test'], java: 21, docker: false,
    })
  })

  it('preserves answers and page position across backward navigation and metadata refresh', async () => {
    const wrapper = mountForm(fields.slice(0, 2))
    await wrapper.get('input[type="text"]').setValue('Ant')
    await wrapper.get('form').trigger('submit')
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.setProps({ fields: fields.slice(0, 2).map(field => ({ ...field })) })
    expect(wrapper.get('[role="status"]').text()).toBe('第 2 题 / 共 2 题')
    await wrapper.get('button.form-previous').trigger('click')
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('Ant')
    await wrapper.get('form').trigger('submit')
    expect((wrapper.get('input[type="checkbox"]').element as HTMLInputElement).checked).toBe(true)
    await wrapper.get('form').trigger('submit')
    expect(JSON.parse(String(wrapper.emitted('submit')![0]![0]))).toEqual({ build: 'Ant', components: ['web'] })
  })

  it('blocks invalid answers before advancing or submitting', async () => {
    const wrapper = mountForm([fields[1]!, { ...fields[2]!, maximum: 21 }])
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="status"]').text()).toBe('第 1 题 / 共 2 题')
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.get('form').trigger('submit')
    await wrapper.get('input[type="number"]').setValue('21.5')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('submit')).toBeUndefined()
    await wrapper.get('input[type="number"]').setValue('21')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('submit')).toHaveLength(1)
  })

  it('supports custom multi-selections and includes newly applicable conditional pages', async () => {
    const wrapper = mountForm([
      { ...fields[1]!, custom: true },
      { key: 'database', type: 'boolean', title: '接入数据库' },
      { key: 'url', type: 'string', title: '数据库地址', required: true,
        when: [{ key: 'database', op: 'eq', value: true }] },
    ])
    expect(wrapper.get('[role="status"]').text()).toBe('第 1 题 / 共 2 题')
    await wrapper.get('input[type="text"]').setValue('Redis')
    await wrapper.get('button.field-option').trigger('click')
    await wrapper.get('form').trigger('submit')
    await wrapper.get('[aria-label="接入数据库"]').setValue(true)
    expect(wrapper.get('[role="status"]').text()).toBe('第 2 题 / 共 3 题')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[aria-label="数据库地址"]').setValue('localhost')
    await wrapper.get('form').trigger('submit')
    expect(JSON.parse(String(wrapper.emitted('submit')![0]![0]))).toEqual({
      components: ['Redis'], database: true, url: 'localhost',
    })
  })

  it.each(['platform', 'cli'])('uses the actual questionnaire title and hides flattened questions in %s', surface => {
    const i18n = localization()
    const card: HitlCard = {
      id: 'card', type: 'hitl', interaction_id: 'interaction', message_id: 'message',
      hitl_type: 'form', prompt: 'Questions\n构建工具\n组件\nJava 版本\nDocker 支持',
      options: [], fields, context: '', job_id: 'job', session_generation: 1, answered: false,
      answer: '', tempInput: '', created_at: '2026-10-03T15:00:00Z',
    }
    const entry: TerminalHitlEntry = {
      kind: 'hitl', id: 'entry', cardId: card.id, jobId: card.job_id,
      hitlType: card.hitl_type, prompt: card.prompt, options: [], fields, context: '',
      answered: false, createdAt: card.created_at, createdMs: Date.parse(card.created_at),
    }
    const wrapper = surface === 'platform'
      ? mount(HitlInteractionCard, { props: { card }, global: { plugins: [i18n] } })
      : mount(TerminalStatusBlock, { props: {
          entry, formatTime: () => '', t: (key, values) => i18n.global.t(key, values || {}),
        }, global: { plugins: [i18n] } })
    expect(wrapper.text()).toContain('请补充信息')
    expect(wrapper.text()).toContain('第 1 题 / 共 4 题')
    expect(wrapper.text()).not.toContain('中断')
    expect(wrapper.text()).not.toContain('Questions')
    expect(wrapper.text()).not.toContain('Java 版本')
    expect(wrapper.findAll('fieldset')).toHaveLength(1)
  })
})
