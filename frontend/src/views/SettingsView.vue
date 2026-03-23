<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Languages, Shield, Bell, Palette, Check, ChevronRight } from 'lucide-vue-next'

const { locale } = useI18n()

const currentLang = ref(locale.value)

const changeLanguage = (lang: string) => {
  currentLang.value = lang
  locale.value = lang
  localStorage.setItem('sdd_lang', lang)
}

const settingsSections = [
  { id: 'general', icon: Languages, label: 'settings.language', description: 'settings.language_desc' },
  { id: 'appearance', icon: Palette, label: 'settings.theme', description: 'settings.theme_desc', disabled: true },
  { id: 'notifications', icon: Bell, label: 'settings.notifications', description: 'settings.notifications_desc', disabled: true },
  { id: 'security', icon: Shield, label: 'settings.security', description: 'settings.security_desc', disabled: true },
]

const activeSection = ref('general')
</script>

<template>
  <div class="settings-container">
    <header class="settings-header animate-slide-down">
      <div class="header-content">
        <h1 class="title-gradient">{{ $t('settings.title') }}</h1>
        <p class="subtitle">{{ $t('settings.subtitle') }}</p>
      </div>
    </header>

    <div class="settings-content animate-fade-in">
      <div class="settings-layout">
        <!-- Sidebar Navigation -->
        <aside class="settings-sidebar glass-panel">
          <nav class="sidebar-nav">
            <button 
              v-for="section in settingsSections" 
              :key="section.id"
              class="nav-item"
              :class="{ 'active': activeSection === section.id, 'disabled': section.disabled }"
              @click="!section.disabled && (activeSection = section.id)"
            >
              <div class="nav-item-icon">
                <component :is="section.icon" class="w-5 h-5" />
              </div>
              <div class="nav-item-text">
                <span class="nav-label">{{ $t(section.label) }}</span>
                <span v-if="section.disabled" class="coming-soon">Soon</span>
              </div>
              <ChevronRight v-if="activeSection === section.id" class="w-4 h-4 ml-auto" />
            </button>
          </nav>
        </aside>

        <!-- Main Content Area -->
        <main class="settings-main glass-panel">
          <transition name="fade-slide" mode="out-in">
            <!-- General Settings -->
            <section v-if="activeSection === 'general'" key="general" class="settings-section">
              <div class="section-header">
                <div class="icon-circle">
                  <Languages class="w-6 h-6" />
                </div>
                <div class="section-title-group">
                  <h2>{{ $t('settings.language') }}</h2>
                  <p>{{ $t('settings.language_desc') }}</p>
                </div>
              </div>

              <div class="language-options">
                <div 
                  class="lang-card"
                  :class="{ 'selected': currentLang === 'zh' }"
                  @click="changeLanguage('zh')"
                >
                  <div class="lang-flag">🇨🇳</div>
                  <div class="lang-info">
                    <span class="lang-name">简体中文</span>
                    <span class="lang-native">Simplified Chinese</span>
                  </div>
                  <div class="select-indicator">
                    <Check v-if="currentLang === 'zh'" class="w-4 h-4" />
                  </div>
                </div>

                <div 
                  class="lang-card"
                  :class="{ 'selected': currentLang === 'en' }"
                  @click="changeLanguage('en')"
                >
                  <div class="lang-flag">🇺🇸</div>
                  <div class="lang-info">
                    <span class="lang-name">English</span>
                    <span class="lang-native">United States</span>
                  </div>
                  <div class="select-indicator">
                    <Check v-if="currentLang === 'en'" class="w-4 h-4" />
                  </div>
                </div>
              </div>

              <div class="footer-note">
                <p>{{ $t('settings.applied_instantly') }}</p>
              </div>
            </section>
          </transition>
        </main>
      </div>
    </div>
  </div>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap');

.settings-container {
  min-height: 100vh;
  padding: 2rem 4rem;
  background-color: transparent;
  font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
}

/* Header */
.settings-header {
  margin-bottom: 3rem;
  max-width: 1100px;
  margin-inline: auto;
}

.title-gradient {
  font-size: 2.5rem;
  font-weight: 800;
  letter-spacing: -1px;
  background: linear-gradient(135deg, #1e3a8a 0%, #0ea5e9 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 0.5rem;
}

.subtitle {
  color: #64748b;
  font-size: 1.1rem;
}

/* Layout */
.settings-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 2rem;
  max-width: 1100px;
  margin: 0 auto;
}

/* Glass Panel Base */
.glass-panel {
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 1.5rem;
  box-shadow: 
    0 10px 15px -3px rgba(0, 0, 0, 0.05),
    0 4px 6px -2px rgba(0, 0, 0, 0.02),
    inset 0 0 0 1px rgba(255, 255, 255, 0.4);
}

/* Sidebar */
.settings-sidebar {
  padding: 1.5rem;
  height: fit-content;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.875rem 1rem;
  border-radius: 1rem;
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  text-align: left;
}

.nav-item:hover:not(.disabled) {
  background: rgba(14, 165, 233, 0.05);
  color: #0ea5e9;
  transform: translateX(4px);
}

.nav-item.active {
  background: #0ea5e9;
  color: white;
  box-shadow: 0 10px 15px -3px rgba(14, 165, 233, 0.3);
}

.nav-item-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.03);
  transition: all 0.3s;
}

.nav-item.active .nav-item-icon {
  background: rgba(255, 255, 255, 0.2);
}

.nav-item.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.nav-label {
  font-weight: 600;
  font-size: 0.9375rem;
}

.coming-soon {
  font-size: 0.65rem;
  padding: 2px 6px;
  background: #f1f5f9;
  color: #94a3b8;
  border-radius: 4px;
  text-transform: uppercase;
  margin-left: 0.5rem;
}

/* Main Content */
.settings-main {
  padding: 2.5rem;
}

.settings-section {
  width: 100%;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  margin-bottom: 2.5rem;
}

.icon-circle {
  width: 48px;
  height: 48px;
  background: #f0f9ff;
  color: #0ea5e9;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 6px -1px rgba(14, 165, 233, 0.1);
}

.section-title-group h2 {
  font-size: 1.25rem;
  font-weight: 700;
  color: #1e293b;
  margin-bottom: 0.25rem;
}

.section-title-group p {
  font-size: 0.875rem;
  color: #64748b;
}

/* Language Cards */
.language-options {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1.25rem;
}

.lang-card {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  padding: 1.25rem;
  background: #f8fafc;
  border: 2px solid transparent;
  border-radius: 1.25rem;
  cursor: pointer;
  transition: all 0.3s;
}

.lang-card:hover {
  background: #f1f5f9;
  transform: translateY(-2px);
  border-color: #e2e8f0;
}

.lang-card.selected {
  background: #f0f9ff;
  border-color: #0ea5e9;
  box-shadow: 0 10px 15px -3px rgba(14, 165, 233, 0.1);
}

.lang-flag {
  font-size: 2rem;
  line-height: 1;
}

.lang-info {
  display: flex;
  flex-direction: column;
}

.lang-name {
  font-weight: 700;
  color: #1e293b;
}

.lang-native {
  font-size: 0.75rem;
  color: #64748b;
}

.select-indicator {
  margin-left: auto;
  width: 24px;
  height: 24px;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s;
}

.lang-card.selected .select-indicator {
  background: #0ea5e9;
  border-color: #0ea5e9;
  color: white;
}

.footer-note {
  margin-top: 3rem;
  padding-top: 1.5rem;
  border-top: 1px solid #f1f5f9;
}

.footer-note p {
  font-size: 0.8125rem;
  color: #94a3b8;
}

/* Animations */
.animate-slide-down {
  animation: slideDown 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}

.animate-fade-in {
  animation: fadeIn 0.8s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideDown {
  from { opacity: 0; transform: translateY(-20px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.fade-slide-enter-active, .fade-slide-leave-active {
  transition: all 0.4s ease;
}

.fade-slide-enter-from {
  opacity: 0;
  transform: translateX(10px);
}

.fade-slide-leave-to {
  opacity: 0;
  transform: translateX(-10px);
}

/* Responsive */
@media (max-width: 1024px) {
  .settings-layout {
    grid-template-columns: 1fr;
  }
  .settings-sidebar {
    height: auto;
  }
  .sidebar-nav {
    flex-direction: row;
    overflow-x: auto;
    padding-bottom: 0.5rem;
  }
  .nav-item {
    flex-shrink: 0;
  }
}

@media (max-width: 640px) {
  .settings-container {
    padding: 1.5rem;
  }
  .title-gradient {
    font-size: 2rem;
  }
}
</style>

