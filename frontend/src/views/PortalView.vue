<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ArrowRight, Code, Zap, Shield, GitBranch } from 'lucide-vue-next'

const router = useRouter()

const navigateToLogin = () => {
  router.push('/login')
}

const features = [
  {
    icon: Code,
    title: 'Specs to Code',
    description: 'Transform System Engineering design documents into structured, working Python & Java code instantly.'
  },
  {
    icon: GitBranch,
    title: 'TDD Auto-Loop',
    description: 'Automatically plan nodes, write tests, code, and self-correct with the Red-Green-Refactor loop.'
  },
  {
    icon: Zap,
    title: 'wexpect PTY Bridge',
    description: 'Native seamless integration with Claude CLI on Windows. Real-time logging and execution state.'
  },
  {
    icon: Shield,
    title: 'HITL Control',
    description: 'When the AI encounters ambiguity or destructive operations, operation pauses for human-in-the-loop review.'
  }
]
</script>

<template>
  <div class="portal-container">
    <nav class="navbar glass-panel">
      <div class="logo">
        <span class="logo-text">SDD Native</span>
      </div>
      <div class="nav-actions">
        <button class="btn-secondary" @click="navigateToLogin">Login</button>
        <button class="btn-primary" @click="navigateToLogin">Start Building</button>
      </div>
    </nav>

    <main>
      <section class="hero-section">
        <div class="hero-content">
          <div class="badge glass-panel">🚀 Specification-Driven Development Platform</div>
          <h1 class="hero-title">From Specs to <span>Production</span> <br>in One Seamless Loop.</h1>
          <p class="hero-subtitle">
            Harness the power of AI Agents to automatically scaffold, implement, and verify your software architecture directly from your SE design documents.
          </p>
          <div class="hero-cta">
            <button class="btn-primary action-btn hero-btn" @click="navigateToLogin">
              Get Started <ArrowRight class="ml-2 w-5 h-5" />
            </button>
          </div>
        </div>
      </section>

      <section class="features-section">
        <h2 class="section-title">Core Capabilities</h2>
        <div class="bento-grid">
          <div v-for="(feat, index) in features" :key="index" class="feature-card glass-panel">
            <div class="icon-wrapper">
              <component :is="feat.icon" class="w-6 h-6" />
            </div>
            <h3>{{ feat.title }}</h3>
            <p>{{ feat.description }}</p>
          </div>
        </div>
      </section>
      
      <section class="social-proof">
        <div class="glass-panel stat-banner">
          <div class="stat-item">
            <span class="stat-num">10x</span>
            <span class="stat-label">Faster Prototyping</span>
          </div>
          <div class="stat-item divider"></div>
          <div class="stat-item">
            <span class="stat-num">100%</span>
            <span class="stat-label">Locally Secure Workspace</span>
          </div>
          <div class="stat-item divider"></div>
          <div class="stat-item">
            <span class="stat-num">TDD</span>
            <span class="stat-label">Built-in Philosophy</span>
          </div>
        </div>
      </section>
    </main>

    <footer class="glass-panel">
      <p>&copy; 2026 SDD Native Platform | Deepmind Team</p>
    </footer>
  </div>
</template>

<style scoped>
.portal-container {
  min-height: 100vh;
  background-color: var(--color-secondary-50);
  background-image: 
    radial-gradient(circle at top right, var(--color-primary-100), transparent 40%),
    radial-gradient(circle at bottom left, var(--color-secondary-100), transparent 40%);
  display: flex;
  flex-direction: column;
}

.navbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-4) var(--space-8);
  margin: var(--space-4) var(--space-8);
  border-radius: var(--radius-full);
}

.logo-text {
  font-family: var(--font-heading);
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--color-secondary-900);
  letter-spacing: -0.5px;
}

.nav-actions {
  display: flex;
  gap: var(--space-4);
}

/* Hero Section */
.hero-section {
  padding: var(--space-12) var(--space-8);
  text-align: center;
  display: flex;
  justify-content: center;
}

.hero-content {
  max-width: 800px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-6);
}

.badge {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-full);
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--color-secondary-900);
}

.hero-title {
  font-size: 4rem;
  line-height: 1.1;
  font-weight: 700;
  color: var(--color-text-title);
  margin: 0;
}

.hero-title span {
  color: transparent;
  background-clip: text;
  -webkit-background-clip: text;
  background-image: linear-gradient(90deg, var(--color-secondary-500), var(--color-primary-600));
}

.hero-subtitle {
  font-size: 1.25rem;
  color: var(--color-text-muted);
  max-width: 600px;
  line-height: 1.6;
}

.hero-cta {
  margin-top: var(--space-4);
}

.hero-btn {
  background-color: var(--color-cta);
  padding: 16px 32px;
  font-size: 1.125rem;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* Features */
.features-section {
  padding: var(--space-8) var(--space-8) var(--space-12);
  max-width: 1200px;
  margin: 0 auto;
}

.section-title {
  text-align: center;
  font-size: 2rem;
  margin-bottom: var(--space-8);
}

.bento-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: var(--space-6);
}

.feature-card {
  padding: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  background-color: var(--color-surface-white); /* Elevate from bg */
}

.icon-wrapper {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  background-color: var(--color-secondary-50);
  color: var(--color-secondary-500);
  display: flex;
  align-items: center;
  justify-content: center;
}

.feature-card h3 {
  font-size: 1.25rem;
  margin: 0;
}

.feature-card p {
  margin: 0;
  color: var(--color-text-body);
  line-height: 1.5;
}

/* Social Proof */
.social-proof {
  padding: 0 var(--space-8) var(--space-12);
  max-width: 900px;
  margin: 0 auto;
}

.stat-banner {
  display: flex;
  justify-content: space-around;
  padding: var(--space-6);
  align-items: center;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
}

.stat-num {
  font-size: 2.5rem;
  font-weight: 700;
  color: var(--color-primary-600);
  font-family: var(--font-heading);
}

.stat-label {
  font-weight: 500;
  color: var(--color-text-muted);
}

.divider {
  width: 1px;
  height: 60px;
  background-color: rgba(0,0,0,0.1);
}

footer {
  margin-top: auto;
  text-align: center;
  padding: var(--space-6);
  border-radius: var(--radius-xl) var(--radius-xl) 0 0;
  background-color: var(--color-surface-white);
}
</style>
