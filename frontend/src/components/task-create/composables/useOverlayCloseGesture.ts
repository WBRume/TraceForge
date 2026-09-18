import { onBeforeUnmount, onMounted, shallowRef } from 'vue'

/**
 * 遮罩层“按住拖出再松手”关闭手势：
 * - 仅在遮罩空白处按下左键才武装关闭（避免误触面板内部）
 * - 按下期间指针移出遮罩 / 点按取消 / 窗口失焦均解除武装
 */
export function useOverlayCloseGesture(close: () => void) {
  const armed = shallowRef(false)

  // 等价于模板 .self 修饰符：只响应落在遮罩自身上的指针事件
  const isSelf = (event: PointerEvent): boolean => event.target === event.currentTarget

  const arm = (event: PointerEvent) => {
    if (event.button !== 0 || !isSelf(event)) return
    armed.value = true
  }

  const finish = (event: PointerEvent) => {
    if (!isSelf(event) || !armed.value) return
    armed.value = false
    close()
  }

  const cancel = (event: PointerEvent) => {
    if (!isSelf(event)) return
    armed.value = false
  }

  const cancelOnWindowBlur = () => {
    armed.value = false
  }

  onMounted(() => window.addEventListener('blur', cancelOnWindowBlur))
  onBeforeUnmount(() => window.removeEventListener('blur', cancelOnWindowBlur))

  return {
    armed,
    handlers: {
      onPointerdown: arm,
      onPointerup: finish,
      onPointerleave: cancel,
      onPointercancel: cancel,
    },
  }
}
