import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import i18n from './i18n'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './assets/main.css'
import { initializeApiFromDesktopConfig } from '@/utils/api'
import { getSddDesktop } from '@/utils/runtime'
import { useAuthStore } from '@/stores/auth'
import { createDesktopTabs, desktopTabsKey } from '@/desktop/workspaceTabs'

const app = createApp(App)

app.use(createPinia())
app.use(i18n)
app.use(ElementPlus)

initializeApiFromDesktopConfig()
  .catch((error: unknown) => {
    console.error('Failed to initialize desktop config', error)
  })
  .then(async () => {
    app.use(router)
    await router.isReady()
    const windows = getSddDesktop()?.workspaceWindows
    if (windows) {
      const tabs = createDesktopTabs(windows, router, useAuthStore())
      app.provide(desktopTabsKey, tabs)
      app.onUnmount(tabs.stop)
      await tabs.start()
    }
    app.mount('#app')
    await nextTick()
    // Render the initial route before asking the desktop shell to show its window.
    let ready = false
    const show = () => {
      if (ready) return
      ready = true
      window.dispatchEvent(new Event('traceforge:app-ready'))
    }
    requestAnimationFrame(() => requestAnimationFrame(show))
    if (windows) window.setTimeout(show, 250)
  })
  .catch((error: unknown) => {
    console.error('Failed to mount application', error)
    const root = document.getElementById('app')
    if (root) root.textContent = '页面加载失败，请重启应用。'
    window.dispatchEvent(new Event('traceforge:app-ready'))
  })
