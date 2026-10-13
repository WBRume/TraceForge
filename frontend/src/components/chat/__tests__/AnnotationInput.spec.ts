import { afterEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import zh from '@/locales/zh.json'
import ChatExecutionInput from '../ChatExecutionInput.vue'
import AnnotationPopover from '../annotations/AnnotationPopover.vue'
import { contextAnnotationsKey, useContextAnnotations } from '@/composables/chat/annotations/useContextAnnotations'

const cleanups: (() => void)[] = []
afterEach(() => { cleanups.splice(0).forEach(cleanup => cleanup()); vi.useRealTimers() })
function setup() {
  const scope = effectScope()
  const task = ref('a')
  const annotations = scope.run(() => useContextAnnotations(() => task.value))!
  annotations.select({ source: { kind: 'message', messageId: 'reply', startOffset: 0, endOffset: 4 }, selectedText: '所选文本' }, { x: 0, y: 0 })
  annotations.add('需要修正')
  const wrapper = mount(ChatExecutionInput, {
    props: { modelValue: '', disabled: false, running: false, canInterrupt: false, interrupting: false, placeholder: '输入消息', sendTitle: '发送', interruptTitle: '停止' },
    global: { provide: { [contextAnnotationsKey as symbol]: annotations }, plugins: [createI18n({ legacy: false, locale: 'zh', messages: { zh } })], stubs: { teleport: true } },
  })
  cleanups.push(() => { wrapper.unmount(); scope.stop() })
  return { wrapper, annotations, task }
}

describe('annotation composer', () => {
  it('keeps the hover preview open while moving from the chip into the bubble, then closes on leave', async () => {
    vi.useFakeTimers()
    const { wrapper } = setup()
    await wrapper.get('.annotation-summary').trigger('pointerenter', { pointerType: 'mouse' })
    expect(wrapper.get('[role="dialog"]').attributes('aria-label')).toBe('批注预览')
    await wrapper.get('.annotation-summary').trigger('pointerleave')
    await wrapper.get('.annotation-preview').trigger('pointerenter')
    await vi.advanceTimersByTimeAsync(200)
    expect(wrapper.find('.annotation-preview').exists()).toBe(true)
    await wrapper.get('.annotation-preview').trigger('pointerleave')
    await vi.advanceTimersByTimeAsync(200)
    expect(wrapper.find('.annotation-preview').exists()).toBe(false)
  })
  it('pins on click and closes on outside click, Escape or a task change', async () => {
    vi.useFakeTimers()
    const { wrapper, task } = setup()
    await wrapper.get('.annotation-toggle').trigger('click')
    await wrapper.get('.annotation-summary').trigger('pointerleave')
    await vi.advanceTimersByTimeAsync(200)
    expect(wrapper.find('.annotation-preview').exists()).toBe(true)
    document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
    await nextTick()
    expect(wrapper.find('.annotation-preview').exists()).toBe(false)
    await wrapper.get('.annotation-toggle').trigger('click')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await nextTick()
    expect(wrapper.find('.annotation-preview').exists()).toBe(false)
    await wrapper.get('.annotation-toggle').trigger('click')
    task.value = 'b'; await nextTick()
    task.value = 'a'; await nextTick()
    expect(wrapper.get('.annotation-toggle').attributes('aria-expanded')).toBe('false')
  })
  it('shows removable context while keeping the textarea empty and enables annotation-only send', async () => {
    const { wrapper } = setup()
    expect(wrapper.get('.card-textarea').element).toHaveProperty('value', '')
    expect(wrapper.get('.annotation-toggle').attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('.annotation-list').exists()).toBe(false)
    expect(wrapper.get('.send-btn').attributes('disabled')).toBeUndefined()
    await wrapper.get('.send-btn').trigger('click')
    expect(wrapper.emitted('submit')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await wrapper.get('.annotation-toggle').trigger('click')
    expect(wrapper.get('[aria-label="待发送批注"]').text()).toContain('需要修正')
    await wrapper.get('[aria-label="删除批注 1"]').trigger('click')
    expect(wrapper.find('[aria-label="待发送批注"]').exists()).toBe(false)
    expect(wrapper.get('.send-btn').attributes('disabled')).toBeDefined()
  })
  it('edits, collapses and clears the package without touching the user draft', async () => {
    const { wrapper, annotations } = setup()
    await wrapper.setProps({ modelValue: '补充要求' })
    await wrapper.get('.annotation-toggle').trigger('click')
    await wrapper.get('[aria-label="编辑批注 1"]').trigger('click')
    await wrapper.get('[aria-label="编辑批注内容"]').setValue('改成可选链')
    await wrapper.get('.annotation-body form').trigger('submit')
    expect(annotations.items.value[0]?.comment).toBe('改成可选链')
    await wrapper.get('.annotation-toggle').trigger('click')
    expect(wrapper.find('.annotation-list').exists()).toBe(false)
    await wrapper.get('[aria-label="清空批注"]').trigger('click')
    expect(annotations.items.value).toHaveLength(0)
    expect(wrapper.get('.card-textarea').element).toHaveProperty('value', '补充要求')
  })
  it('adds the selected context with one click, without an input step or automatically expanding it', async () => {
    const { wrapper, annotations } = setup()
    annotations.clear()
    annotations.select({ source: { kind: 'message', messageId: 'private-message-id', startOffset: 0, endOffset: 4 }, selectedText: '引用内容' }, { x: 20, y: 30 })
    const popover = mount(AnnotationPopover, { global: { provide: { [contextAnnotationsKey as symbol]: annotations }, stubs: { teleport: true } } })
    cleanups.push(() => popover.unmount())
    expect(popover.find('textarea').exists()).toBe(false)
    await popover.get('button').trigger('click')
    expect(annotations.items.value).toHaveLength(1)
    expect(annotations.items.value[0]).toMatchObject({ selectedText: '引用内容', comment: '' })
    expect(popover.find('.annotation-popover').exists()).toBe(false)
    expect(wrapper.get('.annotation-toggle').attributes('aria-expanded')).toBe('false')
    await wrapper.get('.annotation-toggle').trigger('click')
    expect(wrapper.get('blockquote').text()).toBe('引用内容')
    expect(wrapper.text()).not.toMatch(/private-message-id|会话回复|随消息发送/)
    expect(wrapper.find('.annotation-comment').exists()).toBe(false)
    annotations.select({ source: { kind: 'message', messageId: 'another-id', startOffset: 0, endOffset: 2 }, selectedText: '第二条' }, { x: 20, y: 30 })
    annotations.add()
    await nextTick()
    expect(wrapper.get('.annotation-toggle').attributes('aria-expanded')).toBe('false')
    expect(wrapper.get('.card-textarea').element).toHaveProperty('value', '')
  })
  it('does not submit an IME confirmation, and respects blocked or running states', async () => {
    const { wrapper } = setup()
    await wrapper.get('.card-textarea').trigger('keydown', { key: 'Enter', isComposing: true })
    expect(wrapper.emitted('submit')).toBeUndefined()
    await wrapper.setProps({ sendBlocked: true })
    await wrapper.get('.card-textarea').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('submit')).toBeUndefined()
    await wrapper.setProps({ sendBlocked: false, running: true })
    await wrapper.get('.card-textarea').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('submit')).toBeUndefined()
  })
  it('keeps context available for collaborative pre-input without copying it into the textarea', async () => {
    const { wrapper } = setup()
    await wrapper.setProps({ preInputMode: true })
    await wrapper.get('.send-btn').trigger('click')
    expect(wrapper.emitted('start-pre-input')?.[0]?.[0]).toMatchObject({ main_text: '' })
    expect(wrapper.emitted('submit')).toBeUndefined()
  })
})
