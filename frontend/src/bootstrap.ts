async function startApp(): Promise<void> {
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
