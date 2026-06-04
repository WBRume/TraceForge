import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import i18n from './i18n'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './assets/main.css'
import { initializeApiFromDesktopConfig } from '@/utils/api'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(i18n)
app.use(ElementPlus)

initializeApiFromDesktopConfig()
  .catch((error: unknown) => {
    console.error('Failed to initialize desktop config', error)
  })
  .finally(() => {
    app.mount('#app')
  })
