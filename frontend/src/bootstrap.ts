import { initializeDesktopRuntime } from './desktop/initialize'

// Router and API module constants must see the runtime before they are evaluated.
initializeDesktopRuntime()
  .then(() => import('./main'))
  .catch(error => {
    console.error('Failed to initialize desktop runtime', error)
    const root = document.getElementById('app')
    if (root) root.textContent = '桌面服务启动失败，请重启应用。'
  })
