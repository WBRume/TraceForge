import { createI18n } from 'vue-i18n'
import zh from '../locales/zh.json'
import en from '../locales/en.json'

const i18n = createI18n({
  legacy: false, // 使用 Composition API
  locale: localStorage.getItem('sdd_lang') || 'zh',
  fallbackLocale: 'en',
  messages: {
    zh,
    en
  }
})

export default i18n
