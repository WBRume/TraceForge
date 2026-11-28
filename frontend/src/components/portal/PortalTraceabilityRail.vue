<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  MessageSquare, FileText, GitBranch,
  Target, Layers, LibraryBig
} from '@/components/icons'

const { t } = useI18n()
const activeIndex = ref(0)
const isPaused = ref(false)
let timerId: number | null = null

const icons = [MessageSquare, FileText, GitBranch, Target, Layers, LibraryBig]

const nodes = computed(() =>
  icons.map((icon, idx) => ({
    icon,
    code: t(`portal.trace_rail.nodes.${idx}.code`),
    label: t(`portal.trace_rail.nodes.${idx}.label`),
    artifact: t(`portal.trace_rail.nodes.${idx}.artifact`)
  }))
)

const activeNode = computed(() => nodes.value[activeIndex.value] ?? nodes.value[0])

const selectNode = (idx: number) => {
  activeIndex.value = idx
}

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

onMounted(() => {
  if (prefersReducedMotion()) return
  timerId = window.setInterval(() => {
    if (isPaused.value) return
    activeIndex.value = (activeIndex.value + 1) % icons.length
  }, 3200)
})

onBeforeUnmount(() => {
  if (timerId !== null) window.clearInterval(timerId)
})
</script>

<template>
  <div
    class="trace-rail-shell"
    @mouseenter="isPaused = true"
    @mouseleave="isPaused = false"
  >
    <div class="rail-header">
      <span class="rail-eyebrow">{{ $t('portal.trace_rail.eyebrow') }}</span>
      <h3 class="rail-title">{{ $t('portal.trace_rail.title') }}</h3>
      <p class="rail-desc">{{ $t('portal.trace_rail.desc') }}</p>
    </div>

    <div class="rail-track-wrap">
      <div class="rail-line-bg" aria-hidden="true">
        <div
          class="rail-line-fill"
          :style="{ width: `${(activeIndex / Math.max(1, nodes.length - 1)) * 100}%` }"
        ></div>
      </div>

      <div class="rail-nodes">
        <button
          v-for="(node, idx) in nodes"
          :key="node.code"
          type="button"
          class="rail-node"
          :class="{ active: idx === activeIndex, passed: idx < activeIndex }"
          @click="selectNode(idx)"
          @mouseenter="selectNode(idx)"
        >
          <span class="node-icon-box">
            <component :is="node.icon" class="w-4 h-4" />
          </span>
          <span class="node-code">{{ node.code }}</span>
          <span class="node-name">{{ node.label }}</span>
        </button>
      </div>
    </div>

    <div class="rail-evidence-bar" aria-live="polite">
      <Transition name="evidence-slide" mode="out-in">
        <div :key="activeIndex" class="evidence-content">
          <span class="evidence-tag">{{ activeNode?.code }}</span>
          <span class="evidence-text">{{ activeNode?.artifact }}</span>
        </div>
      </Transition>
    </div>
  </div>
</template>

<style scoped>
.trace-rail-shell {
  max-width: 1220px;
  margin: 0 auto;
  padding: 2.25rem 2.5rem;
  border-radius: 1.35rem;
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(203, 213, 225, 0.85);
  box-shadow: 0 18px 40px -18px rgba(14, 165, 233, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.96);
}

.rail-header {
  text-align: center;
  margin-bottom: 2rem;
}

.rail-eyebrow {
  display: inline-block;
  font-family: var(--font-mono, monospace);
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  color: #0284c7;
  margin-bottom: 0.35rem;
}

.rail-title {
  font-family: 'Poppins', 'PingFang SC', sans-serif;
  font-size: 1.45rem;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 0.3rem;
}

.rail-desc {
  font-size: 0.9rem;
  color: #64748b;
  margin: 0;
}

.rail-track-wrap {
  position: relative;
  padding: 0.25rem 0;
}

.rail-line-bg {
  position: absolute;
  top: 24px;
  left: 7%;
  right: 7%;
  height: 2px;
  background: #e2e8f0;
  border-radius: 9999px;
  overflow: hidden;
  z-index: 0;
}

.rail-line-fill {
  height: 100%;
  background: linear-gradient(90deg, #38bdf8, #2563eb);
  transition: width 0.45s cubic-bezier(0.22, 1, 0.36, 1);
}

.rail-nodes {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 0.75rem;
}

.rail-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 0;
  transition: transform 0.22s ease;
}

.rail-node:hover {
  transform: translateY(-2px);
}

.node-icon-box {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 10px -4px rgba(15, 23, 42, 0.08);
  transition: all 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}

.rail-node.passed .node-icon-box {
  border-color: #7dd3fc;
  color: #0284c7;
  background: #f0f9ff;
}

.rail-node.active .node-icon-box {
  background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 100%);
  border-color: transparent;
  color: #ffffff;
  transform: scale(1.08);
  box-shadow: 0 10px 22px -6px rgba(14, 165, 233, 0.5);
}

.node-code {
  font-family: var(--font-mono, monospace);
  font-size: 0.65rem;
  font-weight: 700;
  color: #94a3b8;
  transition: color 0.25s ease;
}

.rail-node.active .node-code { color: #0284c7; }

.node-name {
  font-size: 0.82rem;
  font-weight: 600;
  color: #475569;
  transition: color 0.25s ease;
}

.rail-node.active .node-name {
  color: #0f172a;
  font-weight: 700;
}

.rail-evidence-bar {
  margin-top: 1.65rem;
  padding: 0.75rem 1.25rem;
  border-radius: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  display: flex;
  justify-content: center;
  min-height: 44px;
  align-items: center;
}

.evidence-content {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.evidence-tag {
  font-family: var(--font-mono, monospace);
  font-size: 0.7rem;
  font-weight: 700;
  color: #0369a1;
  background: #e0f2fe;
  padding: 0.16rem 0.55rem;
  border-radius: 6px;
}

.evidence-text {
  font-size: 0.875rem;
  font-weight: 600;
  color: #1e293b;
}

.evidence-slide-enter-active,
.evidence-slide-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}

.evidence-slide-enter-from { opacity: 0; transform: translateY(4px); }
.evidence-slide-leave-to { opacity: 0; transform: translateY(-4px); }

@media (max-width: 900px) {
  .rail-line-bg { display: none; }
  .rail-nodes { grid-template-columns: repeat(3, 1fr); gap: 1rem; }
}

@media (max-width: 560px) {
  .trace-rail-shell { padding: 1.5rem 1.25rem; }
  .rail-nodes { grid-template-columns: repeat(2, 1fr); }
  .evidence-content { flex-direction: column; text-align: center; gap: 0.35rem; }
}
</style>
