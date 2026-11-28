<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Layers, FileText, MessageSquare, GitBranch, Check, Code, Bot } from '@/components/icons'

type StageTab = 'sessionCollab' | 'docReview' | 'localCollab' | 'whiteboard'

const { t } = useI18n()
const activeTab = ref<StageTab>('sessionCollab')
const isTabPaused = ref(false)
const sessionStep = ref(0)
const mayaJoined = ref(false)
const localStep = ref(0)
const sessionManualHoldUntil = ref(0)
const localManualHoldUntil = ref(0)

let tabTimerId: number | null = null
let stepTimerId: number | null = null
let mayaTimerId: number | null = null

const tabs = computed<{ id: StageTab; label: string; icon: any }[]>(() => [
  { id: 'sessionCollab', label: t('portal.stage.tabs.sessionCollab'), icon: MessageSquare },
  { id: 'docReview', label: t('portal.stage.tabs.docReview'), icon: FileText },
  { id: 'localCollab', label: t('portal.stage.tabs.localCollab'), icon: GitBranch },
  { id: 'whiteboard', label: t('portal.stage.tabs.whiteboard'), icon: Layers }
])

const sessionSteps = computed(() => [0, 1, 2, 3].map((i) => t(`portal.stage.sessionCollab.steps.${i}`)))
const localSteps = computed(() => [0, 1, 2, 3].map((i) => t(`portal.stage.localCollab.steps.${i}`)))

watch(sessionStep, (step) => {
  if (mayaTimerId !== null) {
    window.clearTimeout(mayaTimerId)
    mayaTimerId = null
  }
  if (step === 0) {
    mayaJoined.value = false
  } else if (step === 1) {
    mayaTimerId = window.setTimeout(() => {
      mayaJoined.value = true
    }, 340)
  } else {
    mayaJoined.value = true
  }
})

const selectTab = (tab: StageTab) => {
  activeTab.value = tab
  if (tab === 'sessionCollab') sessionStep.value = 0
  if (tab === 'localCollab') localStep.value = 0
}

const selectSessionStep = (idx: number) => {
  sessionStep.value = idx
  sessionManualHoldUntil.value = Date.now() + 6000
}

const selectLocalStep = (idx: number) => {
  localStep.value = idx
  localManualHoldUntil.value = Date.now() + 6000
}

const localCloudBadge = computed(() => {
  const keys = ['v1', 'wait', 'merging', 'synced'] as const
  return t(`portal.stage.localCollab.cloud_states.${keys[localStep.value]}`)
})

const localClientBadge = computed(() => {
  const keys = ['recv', 'dirty', 'pushing', 'synced'] as const
  return t(`portal.stage.localCollab.local_states.${keys[localStep.value]}`)
})

const localIpcLabel = computed(() => {
  const keys = ['down', 'idle', 'up', 'clean'] as const
  return t(`portal.stage.localCollab.ipc_labels.${keys[localStep.value]}`)
})

const localFooterCopy = computed(() => t(`portal.stage.localCollab.footer_labels.${localStep.value}`))

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

onMounted(() => {
  if (prefersReducedMotion()) {
    sessionStep.value = 3
    mayaJoined.value = true
    localStep.value = 3
    return
  }

  stepTimerId = window.setInterval(() => {
    const now = Date.now()
    if (activeTab.value === 'sessionCollab' && now >= sessionManualHoldUntil.value) {
      sessionStep.value = (sessionStep.value + 1) % 4
    } else if (activeTab.value === 'localCollab' && now >= localManualHoldUntil.value) {
      localStep.value = (localStep.value + 1) % 4
    }
  }, 1950)

  const order: StageTab[] = ['sessionCollab', 'docReview', 'localCollab', 'whiteboard']
  tabTimerId = window.setInterval(() => {
    if (isTabPaused.value) return
    const nextIdx = (order.indexOf(activeTab.value) + 1) % order.length
    selectTab(order[nextIdx] as StageTab)
  }, 8400)
})

onBeforeUnmount(() => {
  if (tabTimerId !== null) window.clearInterval(tabTimerId)
  if (stepTimerId !== null) window.clearInterval(stepTimerId)
  if (mayaTimerId !== null) window.clearTimeout(mayaTimerId)
})
</script>

<template>
  <div
    class="stage-shell"
    @mouseenter="isTabPaused = true"
    @mouseleave="isTabPaused = false"
  >
    <!-- Top Chrome & Tab Pills -->
    <div class="stage-chrome">
      <div class="chrome-dots" aria-hidden="true">
        <span></span><span></span><span></span>
      </div>
      <div class="chrome-tabs" role="tablist" aria-label="Collaboration Showcase">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          type="button"
          role="tab"
          :aria-selected="activeTab === tab.id"
          class="chrome-tab"
          :class="{ active: activeTab === tab.id }"
          @click="selectTab(tab.id)"
        >
          <component :is="tab.icon" class="w-3.5 h-3.5" />
          <span>{{ tab.label }}</span>
        </button>
      </div>
    </div>

    <!-- Interactive Viewport -->
    <div class="stage-viewport">
      <Transition name="stage-fade" mode="out-in">
        <!-- Scene 1: Collaborative Pre-Input -> Staged Business Flow -->
        <div v-if="activeTab === 'sessionCollab'" key="sessionCollab" class="scene scene-session">
          <div class="scene-top-row">
            <div class="scene-meta-pill">
              <span class="meta-dot"></span>
              <span>{{ $t('portal.stage.sessionCollab.badge') }}</span>
            </div>
            <div class="flow-steps" role="group" aria-label="Session Collaboration Flow Steps">
              <button
                v-for="(label, idx) in sessionSteps"
                :key="idx"
                type="button"
                class="flow-step-pill"
                :class="{ active: sessionStep === idx, done: sessionStep > idx }"
                @click="selectSessionStep(idx)"
              >
                {{ label }}
              </button>
            </div>
          </div>

          <!-- Shared Pre-Input Composer: Alex drafts first, Lin & Maya append sequentially -->
          <div class="preinput-card" :class="{ merged: sessionStep >= 2 }">
            <div class="preinput-head">
              <span class="preinput-title">{{ $t('portal.stage.sessionCollab.preinput.title') }}</span>
              <div class="member-chips">
                <span class="m-chip m-alex done">
                  <i>A</i>{{ $t('portal.stage.sessionCollab.preinput.tag_alex') }}
                  <Check class="w-2.5 h-2.5" />
                </span>
                <span class="m-chip m-lin" :class="{ done: sessionStep >= 1 }">
                  <i>L</i>{{ $t('portal.stage.sessionCollab.preinput.tag_lin') }}
                  <Check v-if="sessionStep >= 1" class="w-2.5 h-2.5" />
                  <span v-else class="pending-o"></span>
                </span>
                <span class="m-chip m-maya" :class="{ done: sessionStep >= 1 && mayaJoined }">
                  <i>M</i>{{ $t('portal.stage.sessionCollab.preinput.tag_maya') }}
                  <Check v-if="sessionStep >= 1 && mayaJoined" class="w-2.5 h-2.5" />
                  <span v-else class="pending-o"></span>
                </span>
              </div>
              <span class="preinput-timer" :class="{ merged: sessionStep >= 2 }">
                {{ sessionStep >= 2
                  ? $t('portal.stage.sessionCollab.preinput.status_merged')
                  : $t('portal.stage.sessionCollab.preinput.countdown') }}
              </span>
            </div>

            <div class="preinput-doc">
              <span class="doc-seg seg-alex">
                {{ $t('portal.stage.sessionCollab.preinput.seg_alex') }}
                <span v-if="sessionStep === 0" class="typing-caret" aria-hidden="true"></span>
              </span>
              <Transition name="seg-pop">
                <span v-if="sessionStep >= 1" class="doc-seg seg-lin">
                  {{ $t('portal.stage.sessionCollab.preinput.seg_lin') }}
                </span>
              </Transition>
              <Transition name="seg-pop">
                <span v-if="sessionStep >= 1 && mayaJoined" class="doc-seg seg-maya">
                  {{ $t('portal.stage.sessionCollab.preinput.seg_maya') }}
                </span>
              </Transition>
            </div>
          </div>

          <!-- Staged Downstream Flow: Waiting -> Merged Submit + AI -> Diff Note & Steering -->
          <div class="flow-stream-zone">
            <Transition name="batch-swap" mode="out-in">
              <div v-if="sessionStep < 2" :key="`wait-${sessionStep}`" class="preinput-wait-banner">
                <span class="wait-pulse" :class="{ ready: sessionStep === 1 }"></span>
                <span>
                  {{ sessionStep === 0
                    ? $t('portal.stage.sessionCollab.preinput.hint_wait')
                    : $t('portal.stage.sessionCollab.preinput.hint_ready') }}
                </span>
              </div>

              <div v-else key="live-batches" class="chat-batches">
                <!-- Batch 1: Combined Collaborative Prompt & AI Execution -->
                <div class="chat-row right role-merged">
                  <div class="role-bubble owner">
                    <div class="bubble-meta right">
                      <span class="role-name owner">{{ $t('portal.stage.sessionCollab.roles.merged') }}</span>
                    </div>
                    <div class="bubble-copy">{{ $t('portal.stage.sessionCollab.merged_msg') }}</div>
                  </div>
                  <span class="role-avatar owner">A+</span>
                </div>

                <div class="chat-row left role-ai">
                  <span class="role-avatar ai"><Bot class="w-3.5 h-3.5" /></span>
                  <div class="role-bubble ai">
                    <div class="bubble-meta">
                      <span class="role-name ai">{{ $t('portal.stage.sessionCollab.roles.ai') }}</span>
                      <span class="ai-live-dots" aria-hidden="true"><i></i><i></i><i></i></span>
                    </div>
                    <div class="bubble-copy">{{ $t('portal.stage.sessionCollab.ai_msg') }}</div>
                  </div>
                </div>

                <!-- Batch 2 (Step 3): Collaborator Diff Annotation + Owner Running Steer -->
                <Transition name="batch-pop">
                  <div v-if="sessionStep >= 3" class="batch-2-pair">
                    <div class="chat-row left role-collab">
                      <span class="role-avatar collab">L</span>
                      <div class="role-bubble collab">
                        <div class="bubble-meta">
                          <span class="role-name">{{ $t('portal.stage.sessionCollab.roles.collaborator') }}</span>
                          <span class="diff-chip"><Code class="w-3 h-3" /> {{ $t('portal.stage.sessionCollab.annotation') }}</span>
                        </div>
                        <div class="bubble-copy">{{ $t('portal.stage.sessionCollab.collab_msg') }}</div>
                      </div>
                    </div>

                    <div class="chat-row right role-steer">
                      <div class="role-bubble steer">
                        <div class="bubble-meta right">
                          <span class="role-name steer">{{ $t('portal.stage.sessionCollab.roles.owner') }}</span>
                        </div>
                        <div class="bubble-copy">{{ $t('portal.stage.sessionCollab.owner_msg') }}</div>
                      </div>
                      <span class="role-avatar owner">A</span>
                    </div>
                  </div>
                </Transition>
              </div>
            </Transition>
          </div>
        </div>

        <!-- Scene 2: DOCX / MD Native Canvas Review & Animated Itemized Revision -->
        <div v-else-if="activeTab === 'docReview'" key="docReview" class="scene scene-doc">
          <div class="scene-meta-pill">
            <span class="meta-dot indigo"></span>
            <span>{{ $t('portal.stage.docReview.badge') }}</span>
          </div>

          <div class="doc-canvas-box">
            <div class="doc-header-row">
              <span class="doc-heading">{{ $t('portal.stage.docReview.doc_title') }}</span>
              <span class="thread-badge">
                <Check class="w-3 h-3" />
                {{ $t('portal.stage.docReview.resolved') }}
              </span>
            </div>

            <div class="doc-orig-line">
              <span class="doc-selection-sweep">{{ $t('portal.stage.docReview.doc_before') }}</span>
              <span class="doc-comment-tag">{{ $t('portal.stage.docReview.comment_author') }}</span>
            </div>

            <div class="doc-diff-patch">
              <div class="patch-line del">{{ $t('portal.stage.docReview.doc_del') }}</div>
              <div class="patch-line add">{{ $t('portal.stage.docReview.doc_add') }}</div>
            </div>
          </div>

          <div class="proposal-bar">
            <span class="proposal-label">{{ $t('portal.stage.docReview.comment_text') }}</span>
            <span class="proposal-btn">
              <Check class="w-3 h-3" />
              {{ $t('portal.stage.docReview.proposal_btn') }}
            </span>
          </div>
        </div>

        <!-- Scene 3: Cloud Server <-> Local IDE Real Animated Code Sync Flow -->
        <div v-else-if="activeTab === 'localCollab'" key="localCollab" class="scene scene-local">
          <div class="scene-top-row">
            <div class="scene-meta-pill">
              <span class="meta-dot emerald"></span>
              <span>{{ $t('portal.stage.localCollab.badge') }}</span>
            </div>
            <div class="flow-steps" role="group" aria-label="Local Collaboration Sync Steps">
              <button
                v-for="(label, idx) in localSteps"
                :key="idx"
                type="button"
                class="flow-step-pill"
                :class="{ active: localStep === idx, done: localStep > idx }"
                @click="selectLocalStep(idx)"
              >
                {{ label }}
              </button>
            </div>
          </div>

          <!-- Server Worktree <-> Pure IPC Bus <-> Local VS Code IDE -->
          <div class="local-arena">
            <!-- Left Pane: Cloud Server Worktree -->
            <div
              class="code-pane cloud-pane"
              :class="{
                'is-pushing': localStep === 0,
                'is-merging': localStep === 2,
                'is-synced': localStep === 3
              }"
            >
              <div class="pane-head">
                <span class="pane-title">
                  <span class="pane-dot sky"></span>
                  {{ $t('portal.stage.localCollab.cloud_title') }}
                </span>
                <span class="pane-status" :class="`step-${localStep}`">{{ localCloudBadge }}</span>
              </div>
              <div class="pane-file">
                <Code class="w-3 h-3 text-sky-600" />
                <span>src/auth/guard.ts</span>
                <span class="line-ref cloud">Worktree</span>
              </div>
              <div class="pane-code">
                <div class="c-line ctx"><span class="ln">39</span><span class="sg">&nbsp;</span><code>const k = env.AUTH_KEY</code></div>
                <div class="c-line ctx"><span class="ln">40</span><span class="sg">&nbsp;</span><code>export function guard(tk) &#123;</code></div>
                <template v-if="localStep <= 1">
                  <div class="c-line" :class="localStep === 0 ? 'cloud-add' : 'ctx'">
                    <span class="ln">41</span><span class="sg">{{ localStep === 0 ? '+' : ' ' }}</span><code>&nbsp;&nbsp;if (!tk)</code>
                  </div>
                  <div class="c-line" :class="localStep === 0 ? 'cloud-add' : 'ctx'">
                    <span class="ln">42</span><span class="sg">{{ localStep === 0 ? '+' : ' ' }}</span><code>&nbsp;&nbsp;&nbsp;&nbsp;return deny(403)</code>
                  </div>
                </template>
                <template v-else-if="localStep === 2">
                  <div class="c-line del">
                    <span class="ln">41</span><span class="sg">-</span><code>if (!tk) return deny(403)</code>
                  </div>
                  <div class="c-line add animated-insert">
                    <span class="ln">41</span><span class="sg">+</span><code>&nbsp;&nbsp;if (!tk || expired)</code>
                  </div>
                  <div class="c-line add animated-insert">
                    <span class="ln">42</span><span class="sg">+</span><code>&nbsp;&nbsp;&nbsp;&nbsp;return reject(401)</code>
                  </div>
                </template>
                <template v-else>
                  <div class="c-line synced-ok">
                    <span class="ln">41</span><span class="sg">✓</span><code>&nbsp;&nbsp;if (!tk || expired)</code>
                  </div>
                  <div class="c-line synced-ok">
                    <span class="ln">42</span><span class="sg">✓</span><code>&nbsp;&nbsp;&nbsp;&nbsp;return reject(401)</code>
                  </div>
                </template>
                <div class="c-line ctx"><span class="ln">43</span><span class="sg">&nbsp;</span><code>&nbsp;&nbsp;return allowScope(tk)</code></div>
                <div class="c-line ctx"><span class="ln">44</span><span class="sg">&nbsp;</span><code>&#125;</code></div>
              </div>
            </div>

            <!-- Center IPC Transfer Wire -->
            <div class="ipc-bridge" :class="`mode-${localStep}`">
              <span class="ipc-kicker">IPC</span>
              <div class="ipc-rail" aria-hidden="true">
                <svg viewBox="0 0 64 26" fill="none">
                  <path d="M4 13 H60" class="ipc-line" :class="{ active: localStep === 0 || localStep === 2, clean: localStep === 3 }" />
                  <circle v-if="localStep === 0" r="3.5" fill="#0ea5e9">
                    <animateMotion dur="1.1s" repeatCount="indefinite" path="M4 13 H60" />
                  </circle>
                  <circle v-if="localStep === 2" r="3.5" fill="#10b981">
                    <animateMotion dur="1.1s" repeatCount="indefinite" path="M60 13 H4" />
                  </circle>
                </svg>
                <span v-if="localStep === 0" class="dir-arrow right">→</span>
                <span v-else-if="localStep === 2" class="dir-arrow left">←</span>
                <Check v-else-if="localStep === 3" class="w-3.5 h-3.5 text-emerald-600 ipc-check" />
                <span v-else class="watch-pulse"></span>
              </div>
              <span class="ipc-caption">{{ localIpcLabel }}</span>
            </div>

            <!-- Right Pane: Local Desktop IDE -->
            <div
              class="code-pane local-pane"
              :class="{
                'is-editing': localStep === 1,
                'is-pushing': localStep === 2,
                'is-synced': localStep === 3
              }"
            >
              <div class="pane-head">
                <span class="pane-title">
                  <span class="pane-dot emerald"></span>
                  {{ $t('portal.stage.localCollab.local_title') }}
                </span>
                <span class="pane-status local" :class="`step-${localStep}`">{{ localClientBadge }}</span>
              </div>
              <div class="pane-file">
                <Code class="w-3 h-3 text-emerald-600" />
                <span>src/auth/guard.ts</span>
                <span class="line-ref">L42</span>
              </div>
              <div class="pane-code">
                <div class="c-line ctx"><span class="ln">39</span><span class="sg">&nbsp;</span><code>const k = env.AUTH_KEY</code></div>
                <div class="c-line ctx"><span class="ln">40</span><span class="sg">&nbsp;</span><code>export function guard(tk) &#123;</code></div>
                <template v-if="localStep === 0">
                  <div class="c-line cloud-add">
                    <span class="ln">41</span><span class="sg">+</span><code>&nbsp;&nbsp;if (!tk)</code>
                  </div>
                  <div class="c-line cloud-add">
                    <span class="ln">42</span><span class="sg">+</span><code>&nbsp;&nbsp;&nbsp;&nbsp;return deny(403)</code>
                  </div>
                </template>
                <template v-else-if="localStep === 1 || localStep === 2">
                  <div class="c-line del">
                    <span class="ln">41</span><span class="sg">-</span><code>if (!tk) return deny(403)</code>
                  </div>
                  <div class="c-line add animated-insert">
                    <span class="ln">41</span><span class="sg">+</span><code>&nbsp;&nbsp;if (!tk || expired)</code>
                  </div>
                  <div class="c-line add animated-insert">
                    <span class="ln">42</span><span class="sg">+</span><code>&nbsp;&nbsp;&nbsp;&nbsp;return reject(401)</code>
                  </div>
                </template>
                <template v-else>
                  <div class="c-line synced-ok">
                    <span class="ln">41</span><span class="sg">✓</span><code>&nbsp;&nbsp;if (!tk || expired)</code>
                  </div>
                  <div class="c-line synced-ok">
                    <span class="ln">42</span><span class="sg">✓</span><code>&nbsp;&nbsp;&nbsp;&nbsp;return reject(401)</code>
                  </div>
                </template>
                <div class="c-line ctx"><span class="ln">43</span><span class="sg">&nbsp;</span><code>&nbsp;&nbsp;return allowScope(tk)</code></div>
                <div class="c-line ctx"><span class="ln">44</span><span class="sg">&nbsp;</span><code>&#125;</code></div>
              </div>
            </div>
          </div>

          <!-- Bottom Step Explanation Strip -->
          <div class="local-narrative-bar" :class="{ synced: localStep === 3 }">
            <span class="status-dot" :class="{ sky: localStep === 0, amber: localStep === 1 }"></span>
            <span class="narrative-text">{{ localFooterCopy }}</span>
            <span class="step-fraction">{{ localStep + 1 }}/4</span>
          </div>
        </div>

        <!-- Scene 4 (Preserved): Asset Whiteboard & Live Presence -->
        <div v-else key="whiteboard" class="scene scene-whiteboard">
          <div class="scene-top-row">
            <div class="scene-meta-pill">
              <span class="meta-dot emerald"></span>
              <span>{{ $t('portal.stage.whiteboard.badge') }}</span>
            </div>
            <div class="presence-avatars" aria-hidden="true">
              <span class="avatar-dot a1">A</span>
              <span class="avatar-dot a2">L</span>
            </div>
          </div>

          <div class="wb-canvas">
            <svg class="wb-svg" viewBox="0 0 400 180" fill="none" preserveAspectRatio="none" aria-hidden="true">
              <path d="M78 46 C148 46, 174 44, 242 44" class="wb-edge edge-alt" />
              <path d="M60 56 C60 128, 102 132, 158 132" class="wb-edge" />
              <path d="M198 132 L308 132" class="wb-edge" />
              <circle r="3.5" fill="#10b981">
                <animateMotion dur="2.6s" repeatCount="indefinite" path="M78 46 C148 46, 174 44, 242 44" />
              </circle>
              <circle r="3.5" fill="#0ea5e9">
                <animateMotion dur="2.8s" repeatCount="indefinite" path="M60 56 C60 128, 102 132, 158 132" />
              </circle>
              <circle r="3.5" fill="#2563eb">
                <animateMotion dur="2.2s" repeatCount="indefinite" path="M198 132 L308 132" />
              </circle>
            </svg>

            <div class="wb-node node-1">
              <span class="node-kicker">REQ-04</span>
              <span class="node-title">{{ $t('portal.stage.whiteboard.nodes.0') }}</span>
            </div>
            <div class="wb-node node-2">
              <span class="node-kicker">DOCX · §3.2</span>
              <span class="node-title">{{ $t('portal.stage.whiteboard.nodes.1') }}</span>
            </div>
            <div class="wb-node node-3 is-active">
              <span class="node-kicker">TASK · MCP</span>
              <span class="node-title">{{ $t('portal.stage.whiteboard.nodes.2') }}</span>
            </div>
            <div class="wb-node node-4">
              <span class="node-kicker">SOP · RAG</span>
              <span class="node-title">{{ $t('portal.stage.whiteboard.nodes.3') }}</span>
            </div>

            <div class="wb-cursor" aria-hidden="true">
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <path d="M2 1.5L13.5 7.5L8 9L6 14.5L2 1.5Z" fill="#0ea5e9" stroke="#ffffff" stroke-width="1.2" />
              </svg>
              <span>Alex</span>
            </div>
          </div>
        </div>
      </Transition>
    </div>
  </div>
</template>

<style scoped>
.stage-shell {
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(203, 213, 225, 0.85);
  border-radius: 1.5rem;
  box-shadow:
    0 28px 60px -18px rgba(15, 23, 42, 0.14),
    0 10px 24px -10px rgba(14, 165, 233, 0.18),
    inset 0 1px 0 rgba(255, 255, 255, 0.96);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  width: 100%;
  transition: transform 0.45s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.45s ease;
}

.stage-shell:hover {
  transform: translateY(-4px);
  box-shadow:
    0 34px 70px -18px rgba(15, 23, 42, 0.16),
    0 16px 32px -10px rgba(14, 165, 233, 0.24),
    inset 0 1px 0 rgba(255, 255, 255, 0.96);
}

.stage-chrome {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.82rem 1.1rem;
  background: rgba(248, 250, 252, 0.88);
  border-bottom: 1px solid rgba(226, 232, 240, 0.85);
}

.chrome-dots { display: flex; gap: 6px; }
.chrome-dots span { width: 9px; height: 9px; border-radius: 9999px; }
.chrome-dots span:nth-child(1) { background: #fca5a5; }
.chrome-dots span:nth-child(2) { background: #fcd34d; }
.chrome-dots span:nth-child(3) { background: #86efac; }

.chrome-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  background: #eef2f6;
  padding: 0.2rem;
  border-radius: 10px;
}

.chrome-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 0.74rem;
  font-weight: 600;
  padding: 0.34rem 0.62rem;
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.22s ease;
}

.chrome-tab:hover { color: #0284c7; }
.chrome-tab.active {
  background: #ffffff;
  color: #0f172a;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08);
}
.chrome-tab.active :deep(svg) { color: #0ea5e9; }

.stage-viewport {
  position: relative;
  height: 368px;
  padding: 0.9rem 1.15rem;
  background:
    radial-gradient(circle at 80% 15%, rgba(224, 242, 254, 0.52) 0%, transparent 55%),
    linear-gradient(to bottom, #ffffff 0%, #f8fafc 100%);
  overflow: hidden;
}

.scene {
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 0.45rem;
}

.scene-top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
  flex-wrap: nowrap;
}

.scene-meta-pill {
  display: inline-flex;
  align-items: center;
  align-self: flex-start;
  gap: 0.38rem;
  padding: 0.18rem 0.54rem;
  border-radius: 9999px;
  background: rgba(240, 249, 255, 0.9);
  border: 1px solid #bae6fd;
  font-size: 0.65rem;
  font-weight: 600;
  color: #0369a1;
  white-space: nowrap;
  flex-shrink: 0;
}

.meta-dot {
  width: 6px;
  height: 6px;
  border-radius: 9999px;
  background: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.2);
}

.meta-dot.emerald { background: #10b981; box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2); }
.meta-dot.indigo { background: #3b82f6; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2); }

/* Clickable Flow Steps Strip */
.flow-steps {
  display: inline-flex;
  align-items: center;
  gap: 0.16rem;
  background: #f1f5f9;
  padding: 0.15rem;
  border-radius: 8px;
}

.flow-step-pill {
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 0.6rem;
  font-weight: 600;
  padding: 0.16rem 0.4rem;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s ease;
}

.flow-step-pill.done { color: #059669; }
.flow-step-pill.active {
  background: #ffffff;
  color: #0284c7;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.08);
}

/* Scene 1: Collaborative Pre-Input + Batched Business Flow */
.preinput-card {
  background: #ffffff;
  border: 1px solid #bae6fd;
  border-radius: 11px;
  padding: 0.44rem 0.68rem;
  box-shadow: 0 8px 20px -12px rgba(14, 165, 233, 0.22);
  transition: border-color 0.3s ease, background 0.3s ease;
}

.preinput-card.merged {
  border-color: #a7f3d0;
  background: rgba(248, 250, 252, 0.92);
}

.preinput-head {
  display: flex;
  align-items: center;
  gap: 0.38rem;
  margin-bottom: 0.34rem;
}

.preinput-title {
  font-size: 0.65rem;
  font-weight: 700;
  color: #0f172a;
  white-space: nowrap;
}

.member-chips {
  display: flex;
  align-items: center;
  gap: 0.26rem;
  flex-wrap: wrap;
}

.m-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.18rem;
  font-size: 0.59rem;
  font-weight: 600;
  padding: 0.07rem 0.34rem 0.07rem 0.16rem;
  border-radius: 9999px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  color: #64748b;
  transition: all 0.24s ease;
}

.m-chip i {
  width: 14px;
  height: 14px;
  border-radius: 9999px;
  font-style: normal;
  font-size: 0.54rem;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
}

.m-alex i { background: #0284c7; }
.m-lin i { background: #10b981; }
.m-maya i { background: #f59e0b; }

.m-alex.done { background: #f0f9ff; border-color: #7dd3fc; color: #0369a1; }
.m-lin.done { background: #ecfdf5; border-color: #6ee7b7; color: #047857; }
.m-maya.done { background: #fffbeb; border-color: #fcd34d; color: #b45309; }

.pending-o {
  width: 7px;
  height: 7px;
  border-radius: 9999px;
  border: 1.5px solid #cbd5e1;
}

.preinput-timer {
  margin-left: auto;
  font-family: var(--font-mono, monospace);
  font-size: 0.59rem;
  font-weight: 700;
  padding: 0.08rem 0.4rem;
  border-radius: 9999px;
  background: #e0f2fe;
  color: #0369a1;
  white-space: nowrap;
}

.preinput-timer.merged {
  font-family: inherit;
  background: #ecfdf5;
  color: #059669;
}

.preinput-doc {
  font-size: 0.69rem;
  line-height: 1.56;
  color: #0f172a;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.34rem 0.52rem;
}

.doc-seg {
  display: inline;
  padding: 1px 3px;
  border-radius: 3px;
  border-bottom: 2px solid transparent;
  margin-right: 2px;
}

.seg-alex {
  background: rgba(14, 165, 233, 0.1);
  border-bottom-color: #0284c7;
}

.seg-lin {
  background: rgba(16, 185, 129, 0.12);
  border-bottom-color: #10b981;
}

.seg-maya {
  background: rgba(245, 158, 11, 0.12);
  border-bottom-color: #f59e0b;
}

.typing-caret {
  display: inline-block;
  width: 2px;
  height: 0.82em;
  background: #0284c7;
  vertical-align: middle;
  margin-left: 2px;
  animation: blinkCaret 0.8s steps(2, start) infinite;
}

@keyframes blinkCaret {
  0%, 49% { opacity: 1; }
  50%, 100% { opacity: 0; }
}

.flow-stream-zone {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  min-height: 0;
}

.preinput-wait-banner {
  margin-top: 0.35rem;
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.5rem 0.75rem;
  border-radius: 10px;
  border: 1px dashed #cbd5e1;
  background: rgba(255, 255, 255, 0.7);
  font-size: 0.68rem;
  font-weight: 600;
  color: #475569;
}

.wait-pulse {
  width: 7px;
  height: 7px;
  border-radius: 9999px;
  background: #0ea5e9;
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.18);
  flex-shrink: 0;
}

.wait-pulse.ready {
  background: #10b981;
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.22);
}

.chat-batches {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.batch-2-pair {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.chat-row {
  display: flex;
  align-items: flex-end;
  gap: 0.38rem;
  animation: msgReveal 0.36s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.chat-row.right { justify-content: flex-end; }

@keyframes msgReveal {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

.role-avatar {
  width: 19px;
  height: 19px;
  border-radius: 9999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.56rem;
  font-weight: 700;
  color: #ffffff;
  flex-shrink: 0;
}

.role-avatar.collab { background: #10b981; }
.role-avatar.owner { background: #0284c7; }
.role-avatar.ai {
  background: linear-gradient(135deg, #0ea5e9, #2563eb);
  box-shadow: 0 2px 8px -2px rgba(14, 165, 233, 0.45);
}

.role-bubble {
  max-width: 86%;
  padding: 0.26rem 0.55rem;
  border-radius: 9px;
  font-size: 0.65rem;
  line-height: 1.32;
}

.role-bubble.owner {
  background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
  color: #ffffff;
  border-bottom-right-radius: 3px;
}

.role-bubble.steer {
  background: #eff6ff;
  border: 1px solid #93c5fd;
  color: #1e3a8a;
  border-bottom-right-radius: 3px;
}

.role-bubble.collab {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-bottom-left-radius: 3px;
  color: #064e3b;
}

.role-bubble.ai {
  background: #ffffff;
  border: 1px solid #bae6fd;
  border-bottom-left-radius: 3px;
  color: #0f172a;
}

.bubble-meta {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin-bottom: 0.06rem;
}
.bubble-meta.right { justify-content: flex-end; }

.role-name { font-size: 0.56rem; font-weight: 700; color: #059669; }
.role-name.owner { color: rgba(255, 255, 255, 0.9); }
.role-name.steer { color: #1d4ed8; }
.role-name.ai { color: #0284c7; }

.diff-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.18rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.55rem;
  padding: 0 0.28rem;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.85);
  color: #334155;
  border: 1px solid #cbd5e1;
}

.ai-live-dots { display: inline-flex; gap: 3px; margin-left: auto; }
.ai-live-dots i {
  width: 4px;
  height: 4px;
  border-radius: 9999px;
  background: #0ea5e9;
  animation: dotBounce 1.2s ease-in-out infinite;
}
.ai-live-dots i:nth-child(2) { animation-delay: 0.2s; }
.ai-live-dots i:nth-child(3) { animation-delay: 0.4s; }

@keyframes dotBounce {
  0%, 80%, 100% { opacity: 0.3; transform: translateY(0); }
  40% { opacity: 1; transform: translateY(-2px); }
}

.bubble-copy { font-weight: 500; }

/* Scene 2: Doc Review */
.doc-canvas-box {
  flex: 1;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 0.85rem 0.95rem;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  box-shadow: 0 6px 18px -10px rgba(15, 23, 42, 0.08);
}

.doc-header-row { display: flex; align-items: center; justify-content: space-between; }
.doc-heading { font-size: 0.78rem; font-weight: 700; color: #0f172a; }
.thread-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  font-size: 0.65rem;
  font-weight: 700;
  color: #059669;
  background: #ecfdf5;
  padding: 0.14rem 0.5rem;
  border-radius: 9999px;
}

.doc-orig-line { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; font-size: 0.73rem; }
.doc-selection-sweep {
  padding: 2px 6px;
  border-radius: 4px;
  color: #0c4a6e;
  border-bottom: 2px solid #0ea5e9;
  background: linear-gradient(90deg, rgba(186, 230, 253, 0.75) 50%, rgba(241, 245, 249, 0.4) 50%);
  background-size: 200% 100%;
  animation: selectSweep 3.8s ease-in-out infinite;
}

@keyframes selectSweep {
  0%, 15% { background-position: 100% 0; }
  45%, 85% { background-position: 0% 0; }
  100% { background-position: 100% 0; }
}

.doc-comment-tag {
  font-size: 0.64rem;
  font-weight: 700;
  color: #1d4ed8;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  padding: 0.12rem 0.45rem;
  border-radius: 6px;
  white-space: nowrap;
}

.doc-diff-patch { border-radius: 8px; overflow: hidden; border: 1px solid #e2e8f0; font-size: 0.7rem; }
.patch-line { padding: 0.34rem 0.65rem; font-weight: 500; }
.patch-line.del { background: #fef2f2; color: #b91c1c; text-decoration: line-through; opacity: 0.8; }
.patch-line.add {
  background: #ecfdf5;
  color: #047857;
  font-weight: 600;
  animation: lineGlow 2.8s ease-in-out infinite alternate;
}

@keyframes lineGlow {
  0% { background: #ecfdf5; }
  100% { background: #d1fae5; }
}

.proposal-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.85rem;
  border-radius: 10px;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
}
.proposal-label { font-size: 0.72rem; font-weight: 700; color: #0369a1; }
.proposal-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.62rem;
  border-radius: 7px;
  background: #0ea5e9;
  color: #ffffff;
  font-size: 0.69rem;
  font-weight: 600;
}

/* Scene 3: Dual-Pane Server <-> IPC <-> Local Code Sync Flow */
.local-arena {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 70px minmax(0, 1fr);
  align-items: stretch;
  gap: 0.42rem;
  min-height: 0;
}

.code-pane {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 11px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 8px 20px -14px rgba(15, 23, 42, 0.14);
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
}

.code-pane.is-pushing {
  border-color: #38bdf8;
  box-shadow: 0 8px 22px -10px rgba(14, 165, 233, 0.28);
}

.code-pane.is-editing {
  border-color: #f59e0b;
  box-shadow: 0 8px 22px -10px rgba(245, 158, 11, 0.24);
}

.code-pane.is-merging {
  border-color: #60a5fa;
  box-shadow: 0 8px 22px -10px rgba(37, 99, 235, 0.26);
}

.code-pane.is-synced {
  border-color: #6ee7b7;
  box-shadow: 0 8px 22px -10px rgba(16, 185, 129, 0.26);
}

.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.25rem;
  padding: 0.36rem 0.55rem;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

.pane-title {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.64rem;
  font-weight: 700;
  color: #0f172a;
  white-space: nowrap;
}

.pane-dot { width: 6px; height: 6px; border-radius: 9999px; }
.pane-dot.sky { background: #0ea5e9; }
.pane-dot.emerald { background: #10b981; }

.pane-status {
  font-size: 0.55rem;
  font-weight: 700;
  padding: 0.08rem 0.34rem;
  border-radius: 9999px;
  background: #e0f2fe;
  color: #0369a1;
  white-space: nowrap;
}

.pane-status.step-1.local { background: #fef3c7; color: #b45309; }
.pane-status.step-2 { background: #dbeafe; color: #1d4ed8; }
.pane-status.step-3 { background: #ecfdf5; color: #059669; }

.pane-file {
  display: flex;
  align-items: center;
  gap: 0.28rem;
  padding: 0.24rem 0.55rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.6rem;
  font-weight: 600;
  color: #334155;
  border-bottom: 1px solid #f1f5f9;
}

.line-ref {
  margin-left: auto;
  font-size: 0.54rem;
  color: #059669;
  background: #ecfdf5;
  padding: 0 0.28rem;
  border-radius: 4px;
}

.line-ref.cloud {
  color: #0369a1;
  background: #f0f9ff;
}

.pane-code {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  font-family: var(--font-mono, monospace);
  font-size: 0.58rem;
  line-height: 1.72;
  padding: 0.2rem 0;
}

.c-line {
  display: grid;
  grid-template-columns: 19px 11px 1fr;
  align-items: center;
  padding: 0.05rem 0.42rem;
  white-space: nowrap;
}

.c-line .ln { color: #94a3b8; font-size: 0.53rem; }
.c-line .sg { font-weight: 700; font-size: 0.56rem; }
.c-line.ctx { color: #475569; }
.c-line.cloud-add { background: #f0f9ff; color: #0369a1; font-weight: 600; }
.c-line.del { background: #fef2f2; color: #b91c1c; }
.c-line.del code { text-decoration: line-through; opacity: 0.85; }
.c-line.add { background: #ecfdf5; color: #047857; font-weight: 600; }
.c-line.synced-ok {
  background: #ecfdf5;
  color: #047857;
  font-weight: 600;
  animation: syncedFlash 1.2s ease both;
}

@keyframes syncedFlash {
  0% { background: #bbf7d0; }
  100% { background: #ecfdf5; }
}

.animated-insert {
  box-shadow: inset 2.5px 0 0 #10b981;
  animation: diffAppear 0.35s ease both;
}

@keyframes diffAppear {
  from { opacity: 0; transform: translateX(-4px); }
  to { opacity: 1; transform: translateX(0); }
}

/* Center IPC Bridge */
.ipc-bridge {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.22rem;
}

.ipc-kicker {
  font-family: var(--font-mono, monospace);
  font-size: 0.56rem;
  font-weight: 700;
  color: #64748b;
  letter-spacing: 0.06em;
}

.ipc-rail {
  position: relative;
  width: 100%;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ipc-rail svg { width: 100%; height: 26px; }
.ipc-line { stroke: #cbd5e1; stroke-width: 1.8; stroke-dasharray: 4 3; transition: stroke 0.25s ease; }
.ipc-line.active { stroke: #38bdf8; }
.ipc-line.clean { stroke: #10b981; stroke-dasharray: none; }

.dir-arrow { position: absolute; top: -6px; font-size: 0.72rem; font-weight: 700; }
.dir-arrow.right { color: #0284c7; }
.dir-arrow.left { color: #059669; }
.ipc-check { position: absolute; background: #ffffff; border-radius: 9999px; }

.watch-pulse {
  position: absolute;
  width: 7px;
  height: 7px;
  border-radius: 9999px;
  background: #f59e0b;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.22);
}

.ipc-caption {
  font-size: 0.55rem;
  font-weight: 700;
  color: #0369a1;
  text-align: center;
  line-height: 1.25;
}

.local-narrative-bar {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.4rem 0.7rem;
  border-radius: 9px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  font-size: 0.65rem;
  font-weight: 600;
  color: #334155;
  transition: border-color 0.25s ease, background 0.25s ease;
}

.local-narrative-bar.synced {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #065f46;
}

.status-dot { width: 7px; height: 7px; border-radius: 9999px; background: #10b981; flex-shrink: 0; }
.status-dot.sky { background: #0ea5e9; }
.status-dot.amber { background: #f59e0b; }

.narrative-text { flex: 1; }
.step-fraction { font-family: var(--font-mono, monospace); font-size: 0.59rem; color: #64748b; }

/* Scene 4: Whiteboard (Preserved) */
.presence-avatars { display: flex; }
.avatar-dot {
  width: 22px;
  height: 22px;
  border-radius: 9999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.65rem;
  font-weight: 700;
  color: #ffffff;
  border: 2px solid #ffffff;
}
.avatar-dot.a1 { background: #0ea5e9; }
.avatar-dot.a2 { background: #2563eb; margin-left: -6px; }

.wb-canvas {
  position: relative;
  flex: 1;
  border-radius: 14px;
  background-color: #ffffff;
  background-image: radial-gradient(#cbd5e1 1px, transparent 1px);
  background-size: 16px 16px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
}

.wb-svg { position: absolute; inset: 0; width: 100%; height: 100%; z-index: 1; }
.wb-edge { stroke: #93c5fd; stroke-width: 2; stroke-dasharray: 5 4; fill: none; }
.wb-edge.edge-alt { stroke: #6ee7b7; }

.wb-node {
  position: absolute;
  z-index: 2;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 0.45rem 0.7rem;
  box-shadow: 0 6px 16px -6px rgba(15, 23, 42, 0.1);
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.wb-node.is-active {
  border-color: #38bdf8;
  box-shadow: 0 8px 20px -6px rgba(14, 165, 233, 0.25);
}

.node-kicker { font-family: var(--font-mono, monospace); font-size: 0.625rem; font-weight: 700; color: #0284c7; }
.node-title { font-size: 0.76rem; font-weight: 700; color: #0f172a; white-space: nowrap; }
.node-1 { left: 6%; top: 13%; }
.node-2 { left: 55.5%; top: 11%; }
.node-3 { left: 33.5%; top: 59%; }
.node-4 { left: 70.5%; top: 59%; }

.wb-cursor {
  position: absolute;
  z-index: 3;
  left: 62%;
  top: 56%;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  pointer-events: none;
  animation: cursorGlide 5s ease-in-out infinite alternate;
}

.wb-cursor span {
  background: #0ea5e9;
  color: #ffffff;
  font-size: 0.625rem;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 9999px;
}

@keyframes cursorGlide {
  0% { transform: translate(0, 0); }
  100% { transform: translate(-38px, -22px); }
}

/* Transitions */
.stage-fade-enter-active,
.stage-fade-leave-active,
.batch-swap-enter-active,
.batch-swap-leave-active {
  transition: opacity 0.22s ease, transform 0.22s cubic-bezier(0.22, 1, 0.36, 1);
}

.stage-fade-enter-from,
.batch-swap-enter-from { opacity: 0; transform: translateY(6px); }
.stage-fade-leave-to,
.batch-swap-leave-to { opacity: 0; transform: translateY(-4px); }

.seg-pop-enter-active,
.batch-pop-enter-active {
  transition: opacity 0.28s ease, transform 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}
.seg-pop-leave-active,
.batch-pop-leave-active {
  transition: opacity 0.1s ease;
}
.seg-pop-enter-from { opacity: 0; transform: translateX(-4px); }
.seg-pop-leave-to,
.batch-pop-leave-to { opacity: 0; }
.batch-pop-enter-from { opacity: 0; transform: translateY(6px); }

@media (prefers-reduced-motion: reduce) {
  .typing-caret,
  .chat-row,
  .ai-live-dots i,
  .doc-selection-sweep,
  .patch-line.add,
  .animated-insert,
  .synced-ok,
  .wb-cursor {
    animation: none !important;
  }
}
</style>
