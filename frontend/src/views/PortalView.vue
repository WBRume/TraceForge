<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowRight, Code, Zap, Shield, GitBranch, ExternalLink, User as UserIcon, Loader2, Languages } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import api from '@/utils/api'

const { locale, t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()

const toggleLanguage = () => {
  const newLang = locale.value === 'zh' ? 'en' : 'zh'
  locale.value = newLang
  localStorage.setItem('sdd_lang', newLang)
}
const observer = ref<IntersectionObserver | null>(null)

// --- Auth Modal State ---
const showAuthModal = ref(false)
const isLoginMode = ref(true)
const authLoading = ref(false)
const authError = ref('')
const authForm = ref({
  email: '',
  password: '',
  displayName: ''
})

const openAuthModal = (mode = 'login') => {
  isLoginMode.value = mode === 'login'
  showAuthModal.value = true
  authError.value = ''
}

const toggleAuthMode = () => {
  isLoginMode.value = !isLoginMode.value
  authError.value = ''
}

const handleAuthSubmit = async () => {
  authLoading.value = true
  authError.value = ''
  
  try {
    if (isLoginMode.value) {
      const params = new URLSearchParams()
      params.append('username', authForm.value.email)
      params.append('password', authForm.value.password)
      
      const res = await api.post('/auth/login', params)
      authStore.setToken(res.data.access_token)
      await authStore.fetchCurrentUser()
      showAuthModal.value = false
    } else {
      await api.post('/auth/register', {
        email: authForm.value.email,
        password: authForm.value.password,
        display_name: authForm.value.displayName || authForm.value.email.split('@')[0]
      })
      // Auto login after register
      const params = new URLSearchParams()
      params.append('username', authForm.value.email)
      params.append('password', authForm.value.password)
      const res = await api.post('/auth/login', params)
      authStore.setToken(res.data.access_token)
      await authStore.fetchCurrentUser()
      showAuthModal.value = false
    }
  } catch (error: any) {
    authError.value = error.response?.data?.detail || 'Authentication failed'
  } finally {
    authLoading.value = false
  }
}

const handleLogout = () => {
  authStore.logout()
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
    icon: Code,
    title: t('portal.features.automation'),
    description: t('portal.features.automation_desc')
  },
  {
    icon: GitBranch,
    title: t('portal.features.evolutionary'),
    description: t('portal.features.evolutionary_desc')
  },
  {
    icon: Zap,
    title: t('portal.features.realtime'),
    description: t('portal.features.realtime_desc')
  },
  {
    icon: Shield,
    title: t('portal.features.safety'),
    description: t('portal.features.safety_desc')
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
</script>

<template>
  <div class="portal-container">
    <nav class="navbar">
      <div class="logo">
        <div class="logo-icon"></div>
        <span class="logo-text">{{ $t('portal.title') }}</span>
      </div>
      <div class="nav-links">
        <router-link to="/docs" class="nav-link">{{ $t('portal.documentation') }}</router-link>
        <router-link to="/architecture" class="nav-link">{{ $t('portal.architecture') }}</router-link>
        <div class="v-divider"></div>
        <template v-if="authStore.isAuthenticated">
          <div class="user-profile">
            <UserIcon class="w-4 h-4 text-sky-500" />
            <span class="user-name">{{ authStore.user?.display_name }}</span>
          </div>
          <button class="btn-ghost" @click="handleLogout">{{ $t('common.logout') }}</button>
          <button class="btn-primary" @click="router.push('/workspaces')">{{ $t('portal.enter_workspace') }}</button>
        </template>
        <template v-else>
          <button class="btn-ghost" @click="openAuthModal('login')">{{ $t('common.login') }}</button>
          <button class="btn-primary" @click="openAuthModal('register')">{{ $t('portal.start_building') }}</button>
        </template>
        
        <!-- Language Switcher -->
        <button class="lang-switch-btn" @click="toggleLanguage" :title="$t('portal.switch_lang_title')">
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
            <button class="btn-outline">
              {{ $t('portal.show_demo') }} <ExternalLink class="ml-2 w-4 h-4" />
            </button>
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
            <div class="icon-glow-wrapper">
              <component :is="feat.icon" class="w-6 h-6" />
            </div>
            <h3>{{ feat.title }}</h3>
            <p>{{ feat.description }}</p>
          </div>
        </div>
      </section>
      
      <section class="social-proof fade-in">
        <div class="stat-banner">
          <div class="stat-item">
            <span class="stat-num">10x</span>
            <span class="stat-label">{{ $t('portal.stats.productivity') }}</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-num">100%</span>
            <span class="stat-label">{{ $t('portal.stats.security') }}</span>
          </div>
          <div class="stat-divider"></div>
          <div class="stat-item">
            <span class="stat-num">AI+TDD</span>
            <span class="stat-label">{{ $t('portal.stats.quality') }}</span>
          </div>
        </div>
      </section>
    </main>

    <footer class="footer">
      <div class="footer-content">
        <div class="footer-brand">
          <span class="logo-text-small">SDD Native</span>
          <p>{{ $t('portal.footer_tagline') }}</p>
        </div>
        <div class="footer-copy">
          &copy; 2026 Native SDD. Built for Professionals.
        </div>
      </div>
    </footer>

    <!-- Auth Modal -->
    <div v-if="showAuthModal" class="modal-overlay" @click.self="showAuthModal = false">
      <div class="auth-modal glass-panel fade-in-visible">
        <div class="auth-modal-header">
          <h2>{{ isLoginMode ? $t('portal.login_welcome') : $t('portal.register_start') }}</h2>
          <p class="auth-subtitle">{{ $t('portal.auth_subtitle') }}</p>
        </div>

        <form @submit.prevent="handleAuthSubmit" class="auth-form-content">
          <div v-if="!isLoginMode" class="form-group">
            <label>{{ $t('portal.display_name') }}</label>
            <input v-model="authForm.displayName" type="text" class="modal-input" :placeholder="$t('portal.display_name')">
          </div>
          <div class="form-group">
            <label>{{ $t('portal.email') }}</label>
            <input v-model="authForm.email" type="email" required class="modal-input" :placeholder="$t('portal.email_placeholder')">
          </div>
          <div class="form-group">
            <label>{{ $t('portal.password') }}</label>
            <input v-model="authForm.password" type="password" required class="modal-input" :placeholder="$t('portal.password_placeholder')">
          </div>

          <div v-if="authError" class="auth-error-msg">
            {{ authError }}
          </div>

          <button type="submit" class="btn-primary auth-modal-submit" :disabled="authLoading">
            <Loader2 v-if="authLoading" class="w-4 h-4 animate-spin" />
            {{ authLoading ? $t('common.loading') : (isLoginMode ? $t('common.login') : $t('common.register')) }}
          </button>
        </form>

        <div class="auth-modal-footer">
          <p>
            {{ isLoginMode ? $t('portal.no_account') : $t('portal.has_account') }}
            <a href="#" @click.prevent="toggleAuthMode">
              {{ isLoginMode ? $t('portal.switch_to_register') : $t('portal.switch_to_login') }}
            </a>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

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

.logo {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, #0ea5e9, #3b82f6);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(14, 165, 233, 0.3);
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
.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  background-color: var(--color-primary-500);
  color: white;
  border: none;
  padding: 0.625rem 1.25rem;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 4px 6px -1px rgba(14, 165, 233, 0.2);
}

.btn-primary:hover {
  background-color: var(--color-primary-600);
  transform: translateY(-1px);
  box-shadow: 0 10px 15px -3px rgba(14, 165, 233, 0.3), 0 4px 6px -2px rgba(14, 165, 233, 0.1);
  text-shadow: 0 0 8px rgba(255, 255, 255, 0.5);
}

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
  border: 1px solid #bae6fd;
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
  max-width: 1100px;
  margin: 0 auto;
}

.feature-card {
  padding: 2.5rem;
  background: white;
  border: 1px solid #f1f5f9;
  border-radius: 1.5rem;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.feature-card:hover {
  transform: translateY(-8px);
  border-color: #0ea5e966;
  box-shadow: 0 20px 25px -5px rgba(14, 165, 233, 0.1), 0 10px 10px -5px rgba(14, 165, 233, 0.04);
}

.icon-glow-wrapper {
  width: 56px;
  height: 56px;
  background: #f0f9ff;
  color: #0ea5e9;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 1.5rem;
  transition: all 0.3s;
}

.feature-card:hover .icon-glow-wrapper {
  background: #0ea5e9;
  color: white;
  box-shadow: 0 8px 20px rgba(14, 165, 233, 0.4);
}

.feature-card h3 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.5rem;
  font-weight: 600;
  margin-bottom: 1rem;
}

.feature-card p {
  color: #475569;
  line-height: 1.6;
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

@media (max-width: 1024px) {
  .hero-title { font-size: 3rem; }
  .navbar { padding: 1.5rem 2rem; }
  .bento-grid { grid-template-columns: 1fr; padding: 0 2rem; }
  .stat-banner { flex-direction: column; gap: 2rem; }
  .stat-divider { display: none; }
}

/* Auth Modal Styles */
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.auth-modal {
  width: 100%;
  max-width: 400px;
  background: white;
  padding: 2.5rem;
  border-radius: 1.5rem;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);
  border: 1px solid #f1f5f9;
}

.auth-modal-header {
  text-align: center;
  margin-bottom: 2rem;
}

.auth-modal-header h2 {
  font-family: 'Poppins', sans-serif;
  font-size: 1.5rem;
  font-weight: 700;
  margin-bottom: 0.5rem;
}

.auth-subtitle {
  font-size: 0.875rem;
  color: #64748b;
}

.auth-form-content {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-group label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: #475569;
}

.modal-input {
  padding: 0.75rem 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.9375rem;
  transition: all 0.2s;
  font-family: inherit;
}

.modal-input:focus {
  border-color: #0ea5e9;
  outline: none;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.1);
}

.auth-modal-submit {
  padding: 0.875rem;
  font-size: 1rem;
  margin-top: 0.5rem;
}

.auth-error-msg {
  padding: 0.75rem;
  background: #fef2f2;
  color: #ef4444;
  border-radius: 8px;
  font-size: 0.8125rem;
  text-align: center;
}

.auth-modal-footer {
  margin-top: 1.5rem;
  text-align: center;
  font-size: 0.875rem;
  color: #64748b;
}

.auth-modal-footer a {
  color: #0ea5e9;
  font-weight: 600;
  text-decoration: none;
}

.user-profile {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: #f0f9ff;
  border-radius: 9999px;
  border: 1px solid #bae6fd;
}

.user-name {
  font-size: 0.875rem;
  font-weight: 600;
  color: #0369a1;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.animate-spin {
  animation: spin 1s linear infinite;
}
</style>
