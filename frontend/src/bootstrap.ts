import { TASK_FLOAT_ROUTE } from './types/taskFloat'

async function startApp(): Promise<void> {
  if (window.sddTaskFloat || ('__TAURI_INTERNALS__' in window && location.hash.startsWith(`#${TASK_FLOAT_ROUTE}?`))) {
    if (!window.sddTaskFloat) {
      const { initializeTaskFloatRuntime } = await import('./desktop/initialize')
      await initializeTaskFloatRuntime()
    }
    await import('./desktop/taskFloatApp')
    return
  }
  // Electron's preload is already installed. Only Tauri needs asynchronous IPC
  // and HTTP setup before router/API module constants are evaluated.
  if (!window.sddDesktop && '__TAURI_INTERNALS__' in window) {
    const { initializeDesktopRuntime } = await import('./desktop/initialize')
    await initializeDesktopRuntime()
  }
  await import('./main')
}

void startApp().catch(error => {
  console.error('Failed to initialize desktop runtime', error)
  const root = document.getElementById('app')
  if (root) root.textContent = '桌面服务启动失败，请重启应用。'
  window.dispatchEvent(new Event('traceforge:app-ready'))
})
