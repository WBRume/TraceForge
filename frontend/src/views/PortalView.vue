<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { 
  ArrowRight, Shield, GitBranch, Languages, Database,
  Terminal, ServerCog, LibraryBig
} from '@/components/icons'
import { useAuthStore } from '@/stores/auth'
import { isDesktop } from '@/utils/runtime'
import UserMenu from '@/components/user/UserMenu.vue'
import PortalAuthDialog from '@/components/auth/PortalAuthDialog.vue'
import { openDesktopAuthDialogKey, type PortalAuthMode } from '@/components/auth/portalAuthDialog'

const { locale, t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()
const desktop = isDesktop()
const openDesktopAuthDialog = inject(openDesktopAuthDialogKey, null)

const toggleLanguage = () => {
  const newLang = locale.value === 'zh' ? 'en' : 'zh'
  locale.value = newLang
  localStorage.setItem('sdd_lang', newLang)
}
const observer = ref<IntersectionObserver | null>(null)
const authMode = shallowRef<PortalAuthMode | null>(null)

function openAuthModal(mode: PortalAuthMode) {
  if (openDesktopAuthDialog) openDesktopAuthDialog(mode)
  else authMode.value = mode
}

const handleStartBuilding = () => {
  if (authStore.isAuthenticated) {
    router.push('/workspaces')
  } else {
    openAuthModal('login')
  }
}

const features = computed(() => [
  {
    icon: Database,
    title: t('portal.features.asset_traceability.title'),
    description: t('portal.features.asset_traceability.desc'),
    tag: t('portal.features.asset_traceability.tag'),
    points: [
      t('portal.features.asset_traceability.points.0'),
      t('portal.features.asset_traceability.points.1'),
      t('portal.features.asset_traceability.points.2')
    ]
  },
  {
    icon: Terminal,
    title: t('portal.features.terminal_hitl.title'),
    description: t('portal.features.terminal_hitl.desc'),
    tag: t('portal.features.terminal_hitl.tag'),
    points: [
      t('portal.features.terminal_hitl.points.0'),
      t('portal.features.terminal_hitl.points.1'),
      t('portal.features.terminal_hitl.points.2')
    ]
  },
  {
    icon: ServerCog,
    title: t('portal.features.contract_mock.title'),
    description: t('portal.features.contract_mock.desc'),
    tag: t('portal.features.contract_mock.tag'),
    points: [
      t('portal.features.contract_mock.points.0'),
      t('portal.features.contract_mock.points.1'),
      t('portal.features.contract_mock.points.2')
    ]
  },
  {
    icon: GitBranch,
    title: t('portal.features.delta_playbook.title'),
    description: t('portal.features.delta_playbook.desc'),
    tag: t('portal.features.delta_playbook.tag'),
    points: [
      t('portal.features.delta_playbook.points.0'),
      t('portal.features.delta_playbook.points.1'),
      t('portal.features.delta_playbook.points.2')
    ]
  }
])

const highlightFeatures = computed(() => [
  {
    icon: Database,
    title: t('portal.highlights.asset_title'),
    desc: t('portal.highlights.asset_desc')
  },
  {
    icon: Shield,
    title: t('portal.highlights.traceable_title'),
    desc: t('portal.highlights.traceable_desc')
  },
  {
    icon: LibraryBig,
    title: t('portal.highlights.knowledge_title'),
    desc: t('portal.highlights.knowledge_desc')
  }
])

onMounted(() => {
  observer.value = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('fade-in-visible')
      }
    })
  }, { threshold: 0.1 })

  document.querySelectorAll('.fade-in').forEach(el => {
    observer.value?.observe(el)
  })
})

onBeforeUnmount(() => {
  observer.value?.disconnect()
})
</script>

<template>
  <div class="portal-container">
    <nav class="navbar" :class="{ 'desktop-navbar': desktop }">
      <div v-if="!desktop" class="logo">
        <div class="logo-icon"></div>
        <span class="logo-text">{{ $t('portal.title') }}</span>
      </div>
      <div class="nav-links">
        <router-link to="/docs" class="nav-link">{{ $t('portal.documentation') }}</router-link>
        <router-link to="/architecture" class="nav-link">{{ $t('portal.architecture') }}</router-link>
        <div class="v-divider"></div>
        <template v-if="authStore.isAuthenticated">
          <UserMenu
            v-if="!openDesktopAuthDialog"
            :display-name="authStore.user?.display_name"
            :email="authStore.user?.email"
            :user-id="authStore.user?.id"
            :avatar-svg="authStore.user?.avatar_svg"
            :avatar-url="authStore.user?.avatar_url"
            size="sm"
          />
          <button class="btn-primary" @click="router.push('/workspaces')">{{ $t('portal.enter_workspace') }}</button>
        </template>
        <template v-else>
          <button v-if="!openDesktopAuthDialog" class="btn-ghost" @click="openAuthModal('login')">{{ $t('common.login') }}</button>
          <button class="btn-primary" @click="handleStartBuilding">{{ $t('portal.start_building') }}</button>
        </template>
        
        <!-- Language Switcher：登录后语言设置统一收敛到用户设置页 -->
        <button v-if="!authStore.isAuthenticated" class="lang-switch-btn" @click="toggleLanguage" :title="$t('portal.switch_lang_title')">
          <Languages class="w-4 h-4" />
          <span>{{ locale === 'zh' ? 'EN' : 'ZH' }}</span>
        </button>
      </div>
    </nav>

    <main>
      <section class="hero-section fade-in">
        <div class="hero-content">
          <div class="badge-tag">
            <span class="pulse-dot"></span>
            {{ $t('portal.version_badge') }}
          </div>
          <h1 class="hero-title">
            {{ $t('portal.hero_title') }}<br>
            <span class="text-gradient">{{ $t('portal.subtitle') }}</span>
          </h1>
          <p class="hero-subtitle">
            {{ $t('portal.hero_desc') }}
          </p>
          <div class="hero-cta">
            <button class="btn-primary hero-btn" @click="handleStartBuilding">
              {{ $t('portal.start_building') }} <ArrowRight class="ml-2 w-5 h-5" />
            </button>
            <button class="btn-outline" @click="router.push('/architecture')">
              {{ $t('portal.show_demo') }} <ArrowRight class="ml-2 w-4 h-4" />
            </button>
          </div>
        </div>
      </section>

      <section class="highlights-section fade-in">
        <div class="h-container">
          <div v-for="(h, i) in highlightFeatures" :key="i" class="h-card">
            <div class="h-icon">
              <component :is="h.icon" class="w-8 h-8" />
            </div>
            <div class="h-content">
              <h3>{{ h.title }}</h3>
              <p>{{ h.desc }}</p>
            </div>
          </div>
        </div>
      </section>

      <section class="features-section fade-in">
        <div class="section-header">
          <h2 class="section-title">{{ $t('portal.core_drivers_title') }}</h2>
          <p>{{ $t('portal.core_drivers_desc') }}</p>
        </div>
        <div class="bento-grid">
          <div v-for="(feat, index) in features" :key="index" class="feature-card">
            <div class="feature-card-top">
              <div class="icon-glow-wrapper">
                <component :is="feat.icon" class="w-6 h-6" />
              </div>
              <span v-if="feat.tag" class="feature-tag">{{ feat.tag }}</span>
            </div>
            <h3 class="feature-card-title">{{ feat.title }}</h3>
            <p class="feature-card-desc">{{ feat.description }}</p>
            <div class="feature-points">
              <span v-for="(pt, pIdx) in feat.points" :key="pIdx" class="point-pill">
                <span class="point-bullet"></span>
                <span>{{ pt }}</span>
              </span>
            </div>
          </div>
        </div>
      </section>
      
      <section class="social-proof fade-in">
        <div class="stat-banner">
          <div class="stat-item">
            <span class="stat-num">100%</span>
            <span class="stat-label">{{ $t('portal.stats.productivity') }}</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-num">0 阻断</span>
            <span class="stat-label">{{ $t('portal.stats.traceable') }}</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-num">AI+HITL</span>
            <span class="stat-label">{{ $t('portal.stats.quality') }}</span>
          </div>
        </div>
      </section>
    </main>

    <footer class="footer">
      <div class="footer-content">
        <div class="footer-brand">
          <span class="logo-text-small">TraceForge</span>
          <p>{{ $t('portal.footer_tagline') }}</p>
        </div>
        <div class="footer-copy">
          &copy; 2026 TraceForge. Built for Professionals.
        </div>
      </div>
    </footer>
    <PortalAuthDialog v-if="!openDesktopAuthDialog" v-model="authMode" />
  </div>
</template>

<style scoped src="../components/auth/portalPrimaryButton.css"></style>
<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@300;400;500;600;700&family=Poppins:wght@400;500;600;700&display=swap');

:root {
  --color-sky-50: var(--color-primary-50);
  --color-sky-500: var(--color-primary-500);
  --color-sky-600: var(--color-primary-600);
  --color-sky-700: var(--color-primary-700);
  --color-blue-900: var(--color-primary-900);
  --color-slate-600: #475569;
  --color-white: #ffffff;
}

.portal-container {
  min-height: 100vh;
  background-color: #ffffff;
  background-image: 
    radial-gradient(circle at 10% 20%, #eff6ff 0%, transparent 40%),
    radial-gradient(circle at 90% 80%, #f0f9ff 0%, transparent 40%);
  display: flex;
  flex-direction: column;
  font-family: 'Open Sans', sans-serif;
  color: #1e3a8a;
}

/* Navbar */
.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5rem 4rem;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(10px);
  position: sticky;
  top: 0;
  z-index: 100;
  border-bottom: 1px solid #e2e8f0;
}
.desktop-navbar { justify-content: flex-end; }

.logo {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: url('/favicon.svg') center / contain no-repeat;
}

.logo-text {
  font-family: 'Poppins', sans-serif;
  font-size: 1.25rem;
  font-weight: 700;
  letter-spacing: -0.5px;
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 2rem;
}

.nav-link {
  text-decoration: none;
  color: #475569;
  font-weight: 500;
  font-size: 0.9375rem;
  transition: color 0.2s;
}

.nav-link:hover {
  color: #0ea5e9;
}

.v-divider {
  width: 1px;
  height: 24px;
  background-color: #e2e8f0;
}

.lang-switch-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  padding: 0.5rem 0.875rem;
  border-radius: 8px;
  color: #475569;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 0.8125rem;
  margin-left: 0.5rem;
}

.lang-switch-btn:hover {
  background: #f1f5f9;
  border-color: #0ea5e9;
  color: #0ea5e9;
}

/* Buttons */
.btn-ghost {
  background: none;
  border: none;
  color: #475569;
  font-weight: 600;
  cursor: pointer;
  padding: 0.625rem 1rem;
  transition: color 0.2s;
}

.btn-ghost:hover {
  color: #0ea5e9;
}

.btn-outline {
  background: white;
  border: 1px solid #e2e8f0;
  color: #1e3a8a;
  padding: 0.75rem 1.5rem;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  transition: all 0.2s;
}

.btn-outline:hover {
  background: #f8fafc;
  border-color: #0ea5e9;
  color: #0ea5e9;
}

/* Hero Section */
.hero-section {
  padding: 6rem 2rem 4rem;
  text-align: center;
}

.hero-content {
  max-width: 900px;
  margin: 0 auto;
}

.badge-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  background: #f0f9ff;
  color: #0369a1;
  padding: 0.5rem 1rem;
  border-radius: 9999px;
  font-size: 0.8125rem;
  font-weight: 600;
  border: 1px solid #e2e8f0;
  margin-bottom: 2rem;
}

.pulse-dot {
  width: 8px;
  height: 8px;
  background-color: var(--color-primary-500);
  border-radius: 50%;
  position: relative;
}

.pulse-dot::after {
  content: '';
  position: absolute;
  width: 100%;
  height: 100%;
  background: #0ea5e9;
  border-radius: 50%;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% { transform: scale(1); opacity: 1; }
  100% { transform: scale(3); opacity: 0; }
}

.hero-title {
  font-family: 'Poppins', sans-serif;
  font-size: 4.5rem;
  line-height: 1.1;
  font-weight: 800;
  color: #1e3a8a;
  margin-bottom: 1.5rem;
  letter-spacing: -1.5px;
}

.text-gradient {
  background: linear-gradient(135deg, #0ea5e9 0%, #3b82f6 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero-subtitle {
  font-size: 1.25rem;
  color: #475569;
  line-height: 1.7;
  margin-bottom: 2.5rem;
  max-width: 700px;
  margin-inline: auto;
}

.hero-cta {
  display: flex;
  gap: 1rem;
  justify-content: center;
}

.hero-btn {
  padding: 0.875rem 2rem;
  font-size: 1.0625rem;
}

/* Highlights */
.highlights-section {
  padding: 0 4rem;
  margin-top: -3rem;
  position: relative;
  z-index: 10;
}

.h-container {
  max-width: 1200px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.5rem;
}

.h-card {
  background: white;
  border-radius: 1rem;
  padding: 2rem;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.08), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
  border: 1px solid #f1f5f9;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  transition: transform 0.3s;
}

.h-card:hover {
  transform: translateY(-5px);
  border-color: #0ea5e9;
}

.h-icon {
  background: #f0f9ff;
  color: #0ea5e9;
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.h-content h3 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.125rem;
  font-weight: 700;
  margin-bottom: 0.5rem;
  color: #0f172a;
}

.h-content p {
  font-size: 0.875rem;
  color: #475569;
  line-height: 1.6;
}

/* Features */
.features-section {
  padding: 4rem 4rem 6rem;
}

.section-header {
  text-align: center;
  margin-bottom: 4rem;
}

.section-title {
  font-family: 'Poppins', sans-serif;
  font-size: 2.25rem;
  font-weight: 700;
  margin-bottom: 0.75rem;
}

.section-header p {
  color: #64748b;
  font-size: 1.1rem;
}

.bento-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 2rem;
  max-width: 1200px;
  margin: 0 auto;
}

.feature-card {
  padding: 2.25rem;
  background: white;
  border: 1px solid #f1f5f9;
  border-radius: 1.5rem;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.feature-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
}

.feature-tag {
  font-size: 0.8125rem;
  font-weight: 700;
  color: #0369a1;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  padding: 0.25rem 0.75rem;
  border-radius: 9999px;
  letter-spacing: 0.02em;
}

.feature-card:hover {
  transform: translateY(-6px);
  border-color: #0ea5e966;
  box-shadow: 0 20px 25px -5px rgba(14, 165, 233, 0.1), 0 10px 10px -5px rgba(14, 165, 233, 0.04);
}

.icon-glow-wrapper {
  width: 52px;
  height: 52px;
  background: #f0f9ff;
  color: #0ea5e9;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s;
}

.feature-card:hover .icon-glow-wrapper {
  background: #0ea5e9;
  color: white;
  box-shadow: 0 8px 20px rgba(14, 165, 233, 0.4);
}

.feature-card-title {
  font-family: 'Poppins', sans-serif;
  font-size: 1.375rem;
  font-weight: 700;
  margin-bottom: 0.75rem;
  color: #0f172a;
}

.feature-card-desc {
  color: #64748b;
  line-height: 1.7;
  font-size: 0.9375rem;
  margin-bottom: 1.75rem;
  flex: 1;
}

.feature-points {
  display: flex;
  flex-wrap: wrap;
  gap: 0.625rem;
  padding-top: 1.25rem;
  border-top: 1px solid #f1f5f9;
}

.point-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8125rem;
  color: #475569;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  padding: 0.3rem 0.65rem;
  border-radius: 8px;
  font-weight: 500;
}

.point-bullet {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #0ea5e9;
}

/* Social Proof */
.social-proof {
  padding-bottom: 8rem;
}

.stat-banner {
  max-width: 900px;
  margin: 0 auto;
  background: white;
  border: 1px solid #f1f5f9;
  border-radius: 2rem;
  display: flex;
  justify-content: space-around;
  padding: 3rem;
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05);
}

.stat-item {
  text-align: center;
}

.stat-num {
  font-family: 'Poppins', sans-serif;
  font-size: 3rem;
  font-weight: 800;
  background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  display: block;
}

.stat-label {
  font-weight: 600;
  color: #64748b;
  font-size: 0.9375rem;
}

.stat-divider {
  width: 1px;
  height: 60px;
  background: #f1f5f9;
}

/* Footer */
.footer {
  background: #f8fafc;
  padding: 4rem;
  border-top: 1px solid #e2e8f0;
}

.footer-content {
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.logo-text-small {
  font-family: 'Poppins', sans-serif;
  font-size: 1.125rem;
  font-weight: 700;
  color: #1e3a8a;
}

.footer-brand p {
  font-size: 0.875rem;
  color: #64748b;
  margin-top: 0.25rem;
}

.footer-copy {
  font-size: 0.875rem;
  color: #94a3b8;
}

/* Animations */
.fade-in {
  opacity: 0;
  transform: translateY(30px);
  transition: all 0.8s cubic-bezier(0.16, 1, 0.3, 1);
}

.fade-in-visible {
  opacity: 1;
  transform: translateY(0);
}

@media (max-width: 1200px) {
  .bento-grid { grid-template-columns: repeat(2, 1fr); }
  .h-container { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .hero-title { font-size: 2.25rem; }
  .navbar { padding: 1rem 1.5rem; }
  .h-container { grid-template-columns: 1fr; }
  .bento-grid { grid-template-columns: 1fr; padding: 0 1rem; }
  .stat-banner { flex-direction: column; gap: 2rem; }
  .stat-divider { display: none; }
}
</style>
