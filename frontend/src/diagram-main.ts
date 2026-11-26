import { createApp } from 'vue'
import { createI18n } from 'vue-i18n'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './assets/main.css'
import { diagramMessages } from './locales/diagram'
import type { DiagramWindowApi } from './types/diagramDesktop'

async function diagramRuntime(): Promise<DiagramWindowApi | undefined> {
  if (window.sddDiagram) return window.sddDiagram
  if (!('__TAURI_INTERNALS__' in window)) return
  const [{ invoke }, { getCurrentWindow }] = await Promise.all([import('@tauri-apps/api/core'), import('@tauri-apps/api/window')])
  if (getCurrentWindow().label !== 'diagram') return
  return {
    save: request => invoke('desktop_invoke', {
      channel: 'sdd:download:save',
      payload: { ...request, data: Array.from(request.data instanceof Uint8Array ? request.data : new Uint8Array(request.data)) },
    }),
  }
}

async function mount() {
  const locale = localStorage.getItem('sdd_lang') === 'en' ? 'en' : 'zh'
  document.documentElement.lang = locale
  document.title = 'TraceForge · ' + diagramMessages[locale].title
  const root = document.getElementById('app')
  if (!root) return
  const native = await diagramRuntime()
  if (!native) {
    root.textContent = diagramMessages[locale].desktopOnly
    return
  }
  const { default: DiagramWorkbench } = await import('./components/diagram/DiagramWorkbench.vue')
  const i18n = createI18n({
    legacy: false, locale, fallbackLocale: 'en',
    messages: { zh: { diagram: diagramMessages.zh }, en: { diagram: diagramMessages.en } },
  })
  createApp(DiagramWorkbench, { native }).use(i18n).use(ElementPlus).mount(root)
}

void mount().catch(error => {
  console.error('The drawing board could not be started', error)
  const root = document.getElementById('app')
  if (root) root.textContent = 'TraceForge · ' + diagramMessages.zh.shortcuts.launchError
})
