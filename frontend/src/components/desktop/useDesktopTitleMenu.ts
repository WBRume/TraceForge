import { onMounted, onScopeDispose, useTemplateRef } from 'vue'
import type { DropdownInstance } from 'element-plus'

export function useDesktopTitleMenu() {
  const dropdown = useTemplateRef<DropdownInstance>('dropdown')
  const trigger = useTemplateRef<HTMLButtonElement>('trigger')
  let visible = false

  function onKeydown(event: KeyboardEvent) {
    if (event.key !== 'Escape' || !visible) return
    event.preventDefault()
    dropdown.value?.handleClose()
    trigger.value?.focus({ preventScroll: true })
  }

  onMounted(() => window.addEventListener('keydown', onKeydown))
  onScopeDispose(() => window.removeEventListener('keydown', onKeydown))

  return { trigger, setVisible(open: boolean) { visible = open } }
}
