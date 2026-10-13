import { computed, onMounted, shallowRef } from 'vue'
import { getSddDesktop } from '@/utils/runtime'
import type { DesktopConfig } from '@/types/sddDesktop'

export const ideOptions = [
  { value: 'vscode', label: 'VS Code', mark: 'VS' },
  { value: 'idea', label: 'IntelliJ IDEA', mark: 'IJ' },
  { value: 'pycharm', label: 'PyCharm', mark: 'PC' },
] as const
export type IdeEditor = typeof ideOptions[number]['value']
type Preference = NonNullable<DesktopConfig['ide']>

export function useIdePreference(reportError: (message: string) => void) {
  const desktop = getSddDesktop()
  const preference = shallowRef<Preference>({ editor: 'vscode' })
  const busy = shallowRef(false)
  const selected = computed(() => ideOptions.find(option => option.value === preference.value.editor) || ideOptions[0])
  async function load() {
    if (!desktop?.config || busy.value) return
    busy.value = true
    try { preference.value = (await desktop.config.getConfig()).ide || { editor: 'vscode' } }
    catch { reportError('无法读取 IDE 设置，请重新打开菜单重试。') }
    finally { busy.value = false }
  }
  async function save(editor: IdeEditor, executable?: string) {
    if (!desktop?.config || busy.value) return false
    busy.value = true
    reportError('')
    const previous = preference.value
    const launchers = { ...previous.launchers }
    if (previous.editor !== 'vscode' && previous.executable) launchers[previous.editor] = previous.executable
    if (editor !== 'vscode' && executable !== undefined) launchers[editor] = executable.trim()
    const ide: Preference = { editor, launchers, executable: editor === 'vscode' ? '' : launchers[editor] || '' }
    try {
      await desktop.config.setConfig({ ide })
      preference.value = ide
      return true
    } catch { reportError('无法保存 IDE 设置，请重试。'); return false }
    finally { busy.value = false }
  }
  onMounted(load)
  return { preference, selected, busy, load, save }
}
