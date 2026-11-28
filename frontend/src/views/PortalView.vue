<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowRight, GitBranch, Languages, Layers,
  MessageSquare, FileText
} from '@/components/icons'
import { useAuthStore } from '@/stores/auth'
import { isDesktop } from '@/utils/runtime'
import UserMenu from '@/components/user/UserMenu.vue'
import PortalAuthDialog from '@/components/auth/PortalAuthDialog.vue'
import PortalShowcaseStage from '@/components/portal/PortalShowcaseStage.vue'
import PortalTraceabilityRail from '@/components/portal/PortalTraceabilityRail.vue'
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

const authMode = shallowRef<PortalAuthMode | null>(null)
const scrolled = ref(false)

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

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

const heroMetrics = computed(() => [
  { value: t('portal.hero_metrics.0.value'), label: t('portal.hero_metrics.0.label') },
  { value: t('portal.hero_metrics.1.value'), label: t('portal.hero_metrics.1.label') },
  { value: t('portal.hero_metrics.2.value'), label: t('portal.hero_metrics.2.label') }
])

const bentoCards = computed(() => [
  {
    key: 'sessionCollab',
    span: 'span-7',
    icon: MessageSquare,
    tag: t('portal.bento.cards.sessionCollab.tag'),
    title: t('portal.bento.cards.sessionCollab.title'),
    desc: t('portal.bento.cards.sessionCollab.desc'),
    meta: t('portal.bento.cards.sessionCollab.meta')
  },
  {
    key: 'docReview',
    span: 'span-5',
    icon: FileText,
    tag: t('portal.bento.cards.docReview.tag'),
    title: t('portal.bento.cards.docReview.title'),
    desc: t('portal.bento.cards.docReview.desc'),
    meta: t('portal.bento.cards.docReview.meta')
  },
  {
    key: 'localCollab',
    span: 'span-5',
    icon: GitBranch,
    tag: t('portal.bento.cards.localCollab.tag'),
    title: t('portal.bento.cards.localCollab.title'),
    desc: t('portal.bento.cards.localCollab.desc'),
    meta: t('portal.bento.cards.localCollab.meta')
  },
  {
    key: 'assets',
    span: 'span-7',
    icon: Layers,
    tag: t('portal.bento.cards.assets.tag'),
    title: t('portal.bento.cards.assets.title'),
    desc: t('portal.bento.cards.assets.desc'),
    meta: t('portal.bento.cards.assets.meta')
  }
])

function handleCardPointerMove(event: MouseEvent) {
  if (prefersReducedMotion()) return
  const card = event.currentTarget as HTMLElement | null
  if (!card) return
  const rect = card.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const x = event.clientX - rect.left
  const y = event.clientY - rect.top
  card.style.setProperty('--mx', `${x.toFixed(1)}px`)
  card.style.setProperty('--my', `${y.toFixed(1)}px`)
  card.style.setProperty('--spot-opacity', '1')
}

function handleCardPointerLeave(event: MouseEvent) {
  const card = event.currentTarget as HTMLElement | null
  if (!card) return
  card.style.setProperty('--spot-opacity', '0')
}

const onScroll = () => {
  scrolled.value = window.scrollY > 12
}

onMounted(() => {
  window.addEventListener('scroll', onScroll, { passive: true })
  onScroll()
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', onScroll)
})
</script>

<template>
  <div class="portal-container">
    <!-- Subtle Atmospheric Backdrop -->
    <div class="ambient-backdrop" aria-hidden="true">
      <div class="ambient-grid"></div>
      <div class="aurora-glow glow-left"></div>
      <div class="aurora-glow glow-right"></div>
    </div>

    <nav class="navbar" :class="{ 'desktop-navbar': desktop, 'is-scrolled': scrolled }">
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

        <button v-if="!authStore.isAuthenticated" class="lang-switch-btn" @click="toggleLanguage" :title="$t('portal.switch_lang_title')">
          <Languages class="w-4 h-4" />
          <span>{{ locale === 'zh' ? 'EN' : 'ZH' }}</span>
        </button>
      </div>
    </nav>

    <main class="portal-main">
      <!-- Split Hero: Crisp Narrative Left + Live Interactive Showcase Right -->
      <section class="hero-section">
        <div class="hero-grid">
          <div class="hero-copy">
            <div class="badge-tag hero-reveal" style="--reveal-delay: 0ms;">
              <span class="pulse-dot"></span>
              <span>{{ $t('portal.version_badge') }}</span>
            </div>

            <h1 class="hero-title hero-reveal" style="--reveal-delay: 70ms;">
              <span class="title-line">{{ $t('portal.hero_title_top') }}</span><br>
              <span class="text-gradient">{{ $t('portal.hero_title_accent') }}</span>
            </h1>

            <p class="hero-subtitle hero-reveal" style="--reveal-delay: 140ms;">
              {{ $t('portal.hero_desc') }}
            </p>

            <div class="hero-cta hero-reveal" style="--reveal-delay: 210ms;">
              <button class="btn-primary hero-btn btn-shimmer" @click="handleStartBuilding">
                <span>{{ $t('portal.start_building') }}</span>
                <ArrowRight class="cta-arrow w-4 h-4" />
              </button>
              <button class="btn-outline" @click="router.push('/architecture')">
                <span>{{ $t('portal.show_demo') }}</span>
                <ArrowRight class="cta-arrow w-4 h-4" />
              </button>
            </div>

            <div class="hero-metrics hero-reveal" style="--reveal-delay: 280ms;">
              <div v-for="(m, idx) in heroMetrics" :key="idx" class="metric-item">
                <span class="metric-val">{{ m.value }}</span>
                <span class="metric-lbl">{{ m.label }}</span>
              </div>
            </div>
          </div>

          <div class="hero-visual hero-reveal" style="--reveal-delay: 180ms;">
            <PortalShowcaseStage />
          </div>
        </div>
      </section>

      <!-- Focused Asymmetric Bento Grid (4 Pillars, No Clutter) -->
      <section class="bento-section reveal-section">
        <div class="section-header">
          <div class="section-eyebrow">{{ $t('portal.bento.eyebrow') }}</div>
          <h2 class="section-title">{{ $t('portal.bento.title') }}</h2>
          <p>{{ $t('portal.bento.desc') }}</p>
        </div>

        <div class="bento-grid">
          <article
            v-for="(card, index) in bentoCards"
            :key="card.key"
            class="bento-card"
            :class="card.span"
            :style="{ '--stagger': `${index * 80}ms` }"
            @mousemove="handleCardPointerMove"
            @mouseleave="handleCardPointerLeave"
          >
            <div class="bento-top">
              <div class="bento-icon">
                <component :is="card.icon" class="w-5 h-5" />
              </div>
              <span class="bento-tag">{{ card.tag }}</span>
            </div>

            <h3 class="bento-title">{{ card.title }}</h3>
            <p class="bento-desc">{{ card.desc }}</p>

            <div class="bento-meta">
              <span class="meta-pulse"></span>
              <span>{{ card.meta }}</span>
            </div>
          </article>
        </div>
      </section>

      <!-- Interactive End-to-End Traceability Rail -->
      <section class="trace-section reveal-section">
        <PortalTraceabilityRail />
      </section>
    </main>

    <footer class="footer">
      <div class="footer-content">
        <div class="footer-brand">
          <span class="logo-text-small">TraceForge</span>
          <span class="footer-sep">·</span>
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
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Poppins:wght@600;700;800&display=swap');

.portal-container {
  min-height: 100vh;
  background-color: #ffffff;
  display: flex;
  flex-direction: column;
  font-family: 'Inter', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  color: #0f172a;
  position: relative;
  overflow-x: hidden;
}

/* Atmospheric Ambient Layer */
.ambient-backdrop {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  overflow: hidden;
}

.ambient-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(to right, rgba(14, 165, 233, 0.04) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(14, 165, 233, 0.04) 1px, transparent 1px);
  background-size: 56px 56px;
  mask-image: radial-gradient(ellipse 82% 58% at 55% 18%, #000 28%, transparent 100%);
  -webkit-mask-image: radial-gradient(ellipse 82% 58% at 55% 18%, #000 28%, transparent 100%);
}

.aurora-glow {
  position: absolute;
  border-radius: 9999px;
  filter: blur(80px);
  will-change: transform;
}

.glow-left {
  width: 520px;
  height: 520px;
  top: -160px;
  left: -120px;
  background: radial-gradient(circle, rgba(14, 165, 233, 0.16) 0%, transparent 70%);
  animation: driftLeft 20s ease-in-out infinite alternate;
}

.glow-right {
  width: 580px;
  height: 580px;
  top: 40px;
  right: -140px;
  background: radial-gradient(circle, rgba(37, 99, 235, 0.13) 0%, transparent 72%);
  animation: driftRight 24s ease-in-out infinite alternate;
}

@keyframes driftLeft {
  0% { transform: translate3d(0, 0, 0); }
  100% { transform: translate3d(70px, 45px, 0); }
}

@keyframes driftRight {
  0% { transform: translate3d(0, 0, 0); }
  100% { transform: translate3d(-65px, 35px, 0); }
}

.portal-main,
.footer {
  position: relative;
  z-index: 1;
}

/* Navbar */
.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.15rem 4rem;
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  position: sticky;
  top: 0;
  z-index: 100;
  border-bottom: 1px solid rgba(226, 232, 240, 0.65);
  transition: background-color 0.28s ease, border-color 0.28s ease, box-shadow 0.28s ease;
}

.navbar.is-scrolled {
  background: rgba(255, 255, 255, 0.92);
  border-bottom-color: rgba(186, 230, 253, 0.85);
  box-shadow: 0 8px 28px -14px rgba(14, 165, 233, 0.18);
}

.desktop-navbar { justify-content: flex-end; }

.logo {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.logo-icon {
  width: 30px;
  height: 30px;
  background: url('/favicon.svg') center / contain no-repeat;
  transition: transform 0.35s cubic-bezier(0.22, 1, 0.36, 1);
}

.logo:hover .logo-icon {
  transform: rotate(-6deg) scale(1.06);
}

.logo-text {
  font-family: 'Poppins', 'PingFang SC', sans-serif;
  font-size: 1.2rem;
  font-weight: 700;
  letter-spacing: -0.4px;
  color: #1e3a8a;
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 1.85rem;
}

.nav-link {
  text-decoration: none;
  color: #475569;
  font-weight: 500;
  font-size: 0.9375rem;
  position: relative;
  padding: 0.25rem 0;
  transition: color 0.2s ease;
}

.nav-link::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -2px;
  height: 2px;
  border-radius: 9999px;
  background: linear-gradient(90deg, #0ea5e9, #2563eb);
  transform: scaleX(0);
  transform-origin: center;
  transition: transform 0.26s cubic-bezier(0.22, 1, 0.36, 1);
}

.nav-link:hover { color: #0284c7; }
.nav-link:hover::after { transform: scaleX(1); }

.v-divider {
  width: 1px;
  height: 20px;
  background-color: #e2e8f0;
}

.lang-switch-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  padding: 0.45rem 0.8rem;
  border-radius: 8px;
  color: #475569;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 0.8125rem;
}

.lang-switch-btn:hover {
  background: #ffffff;
  border-color: #0ea5e9;
  color: #0284c7;
}

/* Shared Buttons */
.btn-ghost {
  background: none;
  border: none;
  color: #475569;
  font-weight: 600;
  cursor: pointer;
  padding: 0.55rem 0.9rem;
  transition: color 0.2s;
}

.btn-ghost:hover { color: #0284c7; }

.btn-outline {
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(8px);
  border: 1px solid #e2e8f0;
  color: #1e3a8a;
  padding: 0.82rem 1.4rem;
  border-radius: 8px;
  font-weight: 600;
  font-size: 0.95rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  transition: all 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}

.btn-outline.compact {
  padding: 0.625rem 1.1rem;
  font-size: 0.875rem;
}

.btn-outline:hover {
  background: #ffffff;
  border-color: #38bdf8;
  color: #0284c7;
  transform: translateY(-1px);
  box-shadow: 0 10px 22px -10px rgba(14, 165, 233, 0.28);
}

.cta-arrow {
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}

.btn-shimmer:hover .cta-arrow,
.btn-outline:hover .cta-arrow {
  transform: translateX(3px);
}

.btn-shimmer {
  position: relative;
  overflow: hidden;
  border-radius: 8px;
}

.btn-shimmer::after {
  content: '';
  position: absolute;
  inset: -40% auto -40% -110%;
  width: 60%;
  background: linear-gradient(110deg, transparent 20%, rgba(255, 255, 255, 0.36) 50%, transparent 80%);
  transform: skewX(-20deg);
  transition: left 0.6s cubic-bezier(0.22, 1, 0.36, 1);
  pointer-events: none;
}

.btn-shimmer:hover::after { left: 145%; }

/* Split Hero Section */
.hero-section {
  padding: 4.5rem 4rem 4.25rem;
}

.hero-grid {
  max-width: 1220px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1.02fr) minmax(0, 1.08fr);
  gap: 3.5rem;
  align-items: center;
}

.hero-copy {
  text-align: left;
}

.hero-reveal {
  animation: heroEnter 0.55s cubic-bezier(0.22, 1, 0.36, 1) var(--reveal-delay, 0ms) both;
}

@keyframes heroEnter {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.badge-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.55rem;
  background: rgba(240, 249, 255, 0.9);
  color: #0369a1;
  padding: 0.42rem 0.95rem;
  border-radius: 9999px;
  font-size: 0.8rem;
  font-weight: 600;
  border: 1px solid rgba(186, 230, 253, 0.9);
  box-shadow: 0 4px 12px -6px rgba(14, 165, 233, 0.2);
  margin-bottom: 1.5rem;
}

.pulse-dot {
  width: 7px;
  height: 7px;
  background-color: var(--color-primary-500, #0ea5e9);
  border-radius: 50%;
  position: relative;
}

.pulse-dot::after {
  content: '';
  position: absolute;
  inset: 0;
  background: #0ea5e9;
  border-radius: 50%;
  animation: pulseRing 2.2s cubic-bezier(0.22, 1, 0.36, 1) infinite;
}

@keyframes pulseRing {
  0% { transform: scale(1); opacity: 0.9; }
  100% { transform: scale(3.1); opacity: 0; }
}

.hero-title {
  font-family: 'Poppins', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  font-size: clamp(2.35rem, 3.6vw, 3.35rem);
  line-height: 1.18;
  font-weight: 800;
  letter-spacing: -1px;
  margin-bottom: 1.25rem;
  color: #0f172a;
}

.title-line {
  color: #1e3a8a;
}

.text-gradient {
  display: inline-block;
  background: linear-gradient(125deg, #0ea5e9 0%, #2563eb 52%, #0284c7 100%);
  background-size: 200% auto;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: textShimmer 10s ease-in-out infinite;
}

@keyframes textShimmer {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}

.hero-subtitle {
  font-size: 1.075rem;
  color: #475569;
  line-height: 1.72;
  margin-bottom: 2rem;
  max-width: 500px;
}

.hero-cta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.875rem;
  margin-bottom: 2.5rem;
}

.hero-btn {
  padding: 0.85rem 1.75rem;
  font-size: 0.98rem;
}

.hero-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 2rem;
  padding-top: 1.5rem;
  border-top: 1px solid rgba(226, 232, 240, 0.85);
}

.metric-item {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.metric-val {
  font-family: 'Poppins', sans-serif;
  font-size: 1.125rem;
  font-weight: 700;
  color: #0f172a;
}

.metric-lbl {
  font-size: 0.78rem;
  color: #64748b;
  font-weight: 500;
}

/* Asymmetric 4-Card Bento Section */
.bento-section {
  padding: 3.5rem 4rem 4.5rem;
}

.section-header {
  max-width: 1220px;
  margin: 0 auto 2.75rem;
  text-align: center;
}

.section-eyebrow {
  font-family: var(--font-mono, monospace);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  color: #0284c7;
  margin-bottom: 0.5rem;
}

.section-title {
  font-family: 'Poppins', 'PingFang SC', sans-serif;
  font-size: 2.1rem;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 0.5rem;
  letter-spacing: -0.4px;
}

.section-header p {
  color: #64748b;
  font-size: 1rem;
}

.bento-grid {
  max-width: 1220px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 1.35rem;
}

.bento-card {
  --mx: 50%;
  --my: 50%;
  --spot-opacity: 0;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 1.25rem;
  padding: 1.85rem 2rem;
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition:
    transform 0.3s cubic-bezier(0.22, 1, 0.36, 1),
    border-color 0.3s ease,
    box-shadow 0.3s ease,
    opacity 0.65s cubic-bezier(0.22, 1, 0.36, 1);
  box-shadow: 0 6px 20px -10px rgba(15, 23, 42, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.95);
}

.span-7 { grid-column: span 7; }
.span-5 { grid-column: span 5; }

.bento-card::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(380px circle at var(--mx) var(--my), rgba(14, 165, 233, 0.075), transparent 65%);
  opacity: var(--spot-opacity);
  transition: opacity 0.25s ease;
  pointer-events: none;
}

.bento-card::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: 1px;
  background: radial-gradient(240px circle at var(--mx) var(--my), rgba(14, 165, 233, 0.5), transparent 70%);
  -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
  -webkit-mask-composite: xor;
  mask-composite: exclude;
  opacity: var(--spot-opacity);
  transition: opacity 0.25s ease;
  pointer-events: none;
}

.bento-card:hover {
  transform: translateY(-4px);
  border-color: rgba(125, 211, 252, 0.75);
  box-shadow: 0 22px 36px -16px rgba(14, 165, 233, 0.16), 0 8px 16px -8px rgba(15, 23, 42, 0.05);
}

.bento-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.15rem;
}

.bento-icon {
  width: 44px;
  height: 44px;
  border-radius: 11px;
  background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
  color: #0284c7;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(186, 230, 253, 0.7);
  transition: all 0.3s cubic-bezier(0.22, 1, 0.36, 1);
}

.bento-card:hover .bento-icon {
  background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%);
  color: #ffffff;
  transform: scale(1.06);
  box-shadow: 0 8px 18px -6px rgba(14, 165, 233, 0.45);
}

.bento-tag {
  font-size: 0.75rem;
  font-weight: 600;
  color: #0369a1;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  padding: 0.22rem 0.68rem;
  border-radius: 9999px;
}

.bento-title {
  font-family: 'Poppins', 'PingFang SC', sans-serif;
  font-size: 1.2rem;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 0.55rem;
}

.bento-desc {
  font-size: 0.925rem;
  color: #475569;
  line-height: 1.68;
  margin-bottom: 1.35rem;
  flex: 1;
}

.bento-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
  font-weight: 600;
  color: #64748b;
  padding-top: 0.95rem;
  border-top: 1px solid #f1f5f9;
}

.meta-pulse {
  width: 6px;
  height: 6px;
  border-radius: 9999px;
  background: #0ea5e9;
  flex-shrink: 0;
  transition: box-shadow 0.25s ease;
}

.bento-card:hover .meta-pulse {
  box-shadow: 0 0 8px rgba(14, 165, 233, 0.7);
}

/* Traceability Rail Section */
.trace-section {
  padding: 0 4rem 5rem;
}

/* Footer */
.footer {
  background: #f8fafc;
  padding: 2rem 4rem;
  border-top: 1px solid #e2e8f0;
  margin-top: auto;
}

.footer-content {
  max-width: 1220px;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.footer-brand {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.logo-text-small {
  font-family: 'Poppins', sans-serif;
  font-size: 1rem;
  font-weight: 700;
  color: #1e3a8a;
}

.footer-sep { color: #cbd5e1; }

.footer-brand p {
  font-size: 0.85rem;
  color: #64748b;
  margin: 0;
}

.footer-copy {
  font-size: 0.825rem;
  color: #94a3b8;
}

/* Section Entrance (always visible fallback-safe) */
.reveal-section {
  animation: sectionEnter 0.6s cubic-bezier(0.22, 1, 0.36, 1) 0.15s both;
}

@keyframes sectionEnter {
  from {
    opacity: 0;
    transform: translateY(16px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.bento-card:hover {
  transform: translateY(-4px);
}

@media (prefers-reduced-motion: reduce) {
  .aurora-glow,
  .pulse-dot::after,
  .text-gradient,
  .cta-band::before,
  .hero-reveal,
  .reveal-section {
    animation: none !important;
  }

  .hero-reveal,
  .reveal-section,
  .bento-card {
    opacity: 1 !important;
    transform: none !important;
    filter: none !important;
    transition: none !important;
  }
}

@media (max-width: 1080px) {
  .hero-section,
  .bento-section,
  .trace-section,
  .navbar,
  .footer {
    padding-inline: 2rem;
  }

  .hero-grid {
    grid-template-columns: 1fr;
    gap: 2.5rem;
  }

  .hero-copy {
    text-align: center;
  }

  .hero-subtitle {
    margin-inline: auto;
  }

  .hero-cta,
  .hero-metrics {
    justify-content: center;
  }

  .span-7,
  .span-5 {
    grid-column: span 6;
  }
}

@media (max-width: 768px) {
  .hero-section { padding-top: 3rem; }
  .bento-grid { grid-template-columns: 1fr; }
  .span-7,
  .span-5 { grid-column: span 1; }
  .footer-content { flex-direction: column; gap: 0.75rem; text-align: center; }
  .footer-brand { flex-direction: column; gap: 0.25rem; }
  .footer-sep { display: none; }
}
</style>
