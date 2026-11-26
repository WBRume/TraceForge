import { createI18n } from 'vue-i18n'
import zh from '../locales/zh.json'
import en from '../locales/en.json'
import { diagramMessages } from '../locales/diagram'

const i18n = createI18n({
  legacy: false, // 使用 Composition API
  locale: localStorage.getItem('sdd_lang') || 'zh',
  fallbackLocale: 'en',
  messages: {
    zh: { ...zh, diagram: diagramMessages.zh },
    en: { ...en, diagram: diagramMessages.en },
  }
})

export default i18n
