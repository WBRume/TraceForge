import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import IdeOpenButton from '@/components/collaboration/IdeOpenButton.vue'

const config = vi.hoisted(() => ({ getConfig: vi.fn(), setConfig: vi.fn() }))
vi.mock('@/utils/runtime', () => ({ getSddDesktop: () => ({ config }) }))
let wrapper: VueWrapper
beforeEach(() => {
  config.getConfig.mockResolvedValue({ ide: { editor: 'idea', executable: 'G:/IDE/idea64.exe' } })
  config.setConfig.mockResolvedValue({})
})
afterEach(() => { wrapper?.unmount(); document.body.innerHTML = '' })
async function setup() {
  wrapper = mount(IdeOpenButton, { attachTo: document.body })
  await flushPromises()
}
async function menu() {
  await wrapper.get('[aria-label="选择 IDE"]').trigger('click')
  await vi.waitFor(() => expect(wrapper.get('[aria-label="选择 IDE"]').attributes('aria-expanded')).toBe('true'))
  await flushPromises()
  return [...document.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')]
}

describe('IDE split button', () => {
  it('opens with the remembered IDE and saves a new choice before opening', async () => {
    await setup()
    await wrapper.get('[aria-label="在 IntelliJ IDEA 中打开"]').trigger('click')
    expect(wrapper.emitted('open')).toHaveLength(1)
    let finish!: () => void
    config.setConfig.mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve }))
    const items = await menu()
    items[2]!.click(); await flushPromises()
    expect(config.setConfig).toHaveBeenCalledWith({ ide: { editor: 'pycharm', executable: '', launchers: { idea: 'G:/IDE/idea64.exe' } } })
    expect(wrapper.emitted('open')).toHaveLength(1)
    finish(); await flushPromises()
    expect(wrapper.emitted('open')).toHaveLength(2)
    expect(wrapper.find('[aria-label="在 PyCharm 中打开"]').exists()).toBe(true)
  })
  it('does not open with the wrong editor when saving fails', async () => {
    await setup()
    config.setConfig.mockRejectedValue(new Error('disk full'))
    const items = await menu()
    items[0]!.click(); await flushPromises()
    expect(wrapper.emitted('open')).toBeUndefined()
    expect(wrapper.emitted('error')?.at(-1)).toEqual(['无法保存 IDE 设置，请重试。'])
    expect(wrapper.get('[aria-label="选择 IDE"]').attributes('aria-expanded')).toBe('true')
  })
  it('supports keyboard selection and Escape without launching an IDE', async () => {
    await setup()
    const items = await menu()
    items[1]!.focus()
    items[1]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    expect(document.activeElement).toBe(items[2])
    items[2]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    await vi.waitFor(() => expect(wrapper.get('[aria-label="选择 IDE"]').attributes('aria-expanded')).toBe('false'))
    expect(document.activeElement).toBe(wrapper.get('[aria-label="选择 IDE"]').element)
    expect(wrapper.emitted('open')).toBeUndefined()
  })
  it('edits the launcher inside the menu without opening a file', async () => {
    await setup(); await menu()
    document.querySelector<HTMLButtonElement>('.configure-ide')!.click(); await flushPromises()
    const input = document.querySelector<HTMLInputElement>('#ide-launcher-path')!
    expect(input.value).toBe('G:/IDE/idea64.exe')
    input.value = 'G:/Apps/IDEA/idea64.exe'; input.dispatchEvent(new Event('input', { bubbles: true }))
    document.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    await flushPromises()
    expect(config.setConfig).toHaveBeenCalledWith({ ide: { editor: 'idea', executable: input.value, launchers: { idea: input.value } } })
    expect(wrapper.emitted('open')).toBeUndefined()
  })
})
