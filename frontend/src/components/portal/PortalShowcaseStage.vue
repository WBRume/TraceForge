<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch, type CSSProperties } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Layers, FileText, MessageSquare, GitBranch,
  Check, Code, Bot, ChevronLeft, ChevronRight
} from '@/components/icons'

type StageCardId = 'sessionCollab' | 'docReview' | 'localCollab' | 'whiteboard'

const { t } = useI18n()
const CARD_ORDER: StageCardId[] = ['sessionCollab', 'docReview', 'localCollab', 'whiteboard']

const activeIndex = ref(0)
const isDeckPaused = ref(false)
const parallax = ref({ rx: 0, ry: 0 })
const reducedMotion = ref(false)

const sessionStep = ref(0)
const mayaJoined = ref(false)
const docStep = ref(0)
const localStep = ref(0)
const sessionManualHoldUntil = ref(0)
const docManualHoldUntil = ref(0)
const localManualHoldUntil = ref(0)

let deckTimerId: number | null = null
let stepTimerId: number | null = null
let mayaTimerId: number | null = null
let lastWheelAt = 0

const activeCardId = computed<StageCardId>(() => CARD_ORDER[activeIndex.value] ?? 'sessionCollab')

const cards = computed(() => [
  { id: 'sessionCollab' as StageCardId, num: '01', label: t('portal.stage.tabs.sessionCollab'), icon: MessageSquare },
  { id: 'docReview' as StageCardId, num: '02', label: t('portal.stage.tabs.docReview'), icon: FileText },
  { id: 'localCollab' as StageCardId, num: '03', label: t('portal.stage.tabs.localCollab'), icon: GitBranch },
  { id: 'whiteboard' as StageCardId, num: '04', label: t('portal.stage.tabs.whiteboard'), icon: Layers }
])

const sessionSteps = computed(() => [0, 1, 2, 3].map((i) => t(`portal.stage.sessionCollab.steps.${i}`)))
const docSteps = computed(() => [0, 1, 2, 3].map((i) => t(`portal.stage.docReview.steps.${i}`)))
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

const getRelativeOffset = (idx: number) => {
  const n = CARD_ORDER.length
  return ((idx - activeIndex.value) % n + n) % n
}

const selectCard = (idx: number) => {
  const safe = ((idx % CARD_ORDER.length) + CARD_ORDER.length) % CARD_ORDER.length
  activeIndex.value = safe
  if (!reducedMotion.value) {
    if (CARD_ORDER[safe] === 'sessionCollab') sessionStep.value = 0
    if (CARD_ORDER[safe] === 'docReview') docStep.value = 0
    if (CARD_ORDER[safe] === 'localCollab') localStep.value = 0
  }
}

const stepDeck = (delta: number) => {
  selectCard(activeIndex.value + delta)
}

const selectSessionStep = (idx: number) => {
  sessionStep.value = idx
  sessionManualHoldUntil.value = Date.now() + 6000
}

const selectDocStep = (idx: number) => {
  docStep.value = idx
  docManualHoldUntil.value = Date.now() + 6000
}

const selectLocalStep = (idx: number) => {
  localStep.value = idx
  localManualHoldUntil.value = Date.now() + 6000
}

// Keep front card (slot 0) strictly 1:1 non-rotated & non-scaled so text is razor-sharp,
// while stacked cards (slots 1..3) recede in true 3D perspective behind it.
const slotConfigs = [
  { x: 0, y: 0, z: 0, ry: 0, rx: 0, scale: 1, opacity: 1, zIndex: 40 },
  { x: 24, y: -31, z: -48, ry: -4.2, rx: 1.6, scale: 0.96, opacity: 0.97, zIndex: 30 },
  { x: 46, y: -60, z: -96, ry: -7.2, rx: 3.0, scale: 0.92, opacity: 0.9, zIndex: 20 },
  { x: 66, y: -87, z: -144, ry: -10.0, rx: 4.2, scale: 0.88, opacity: 0.82, zIndex: 10 }
]

const getCardStyle = (idx: number): CSSProperties => {
  const offset = getRelativeOffset(idx)
  if (offset === 0) {
    return {
      transform: 'none',
      zIndex: 40,
      opacity: 1
    }
  }
  const slot = slotConfigs[offset] ?? slotConfigs[3]
  const px = parallax.value.ry * (1 + offset * 0.25)
  const py = parallax.value.rx * (1 + offset * 0.25)
  return {
    transform: `translate3d(${slot.x}px, ${slot.y}px, ${slot.z}px) rotateY(${slot.ry + px}deg) rotateX(${slot.rx + py}deg) scale(${slot.scale})`,
    zIndex: slot.zIndex,
    opacity: slot.opacity
  }
}

const handleMouseMove = (e: MouseEvent) => {
  if (reducedMotion.value) return
  const el = e.currentTarget as HTMLElement | null
  if (!el) return
  const rect = el.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const nx = ((e.clientX - rect.left) / rect.width - 0.5) * 2
  const ny = ((e.clientY - rect.top) / rect.height - 0.5) * 2
  parallax.value = { rx: -ny * 2.2, ry: nx * 2.8 }
}

const handleMouseLeave = () => {
  isDeckPaused.value = false
  parallax.value = { rx: 0, ry: 0 }
}

const handleWheel = (e: WheelEvent) => {
  const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY
  if (Math.abs(delta) < 12) return
  const now = performance.now()
  if (now - lastWheelAt < 340) return
  lastWheelAt = now
  stepDeck(delta > 0 ? 1 : -1)
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

onMounted(() => {
  reducedMotion.value = typeof window !== 'undefined'
    && Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)

  if (reducedMotion.value) {
    sessionStep.value = 3
    mayaJoined.value = true
    docStep.value = 3
    localStep.value = 3
    return
  }

  stepTimerId = window.setInterval(() => {
    const now = Date.now()
    if (activeCardId.value === 'sessionCollab' && now >= sessionManualHoldUntil.value) {
      sessionStep.value = (sessionStep.value + 1) % 4
    } else if (activeCardId.value === 'docReview' && now >= docManualHoldUntil.value) {
      docStep.value = (docStep.value + 1) % 4
    } else if (activeCardId.value === 'localCollab' && now >= localManualHoldUntil.value) {
      localStep.value = (localStep.value + 1) % 4
    }
  }, 1950)

  deckTimerId = window.setInterval(() => {
    if (isDeckPaused.value) return
    stepDeck(1)
  }, 8400)
})

onBeforeUnmount(() => {
  if (deckTimerId !== null) window.clearInterval(deckTimerId)
  if (stepTimerId !== null) window.clearInterval(stepTimerId)
  if (mayaTimerId !== null) window.clearTimeout(mayaTimerId)
})
</script>

<template>
  <div
    class="deck-stage"
    @mouseenter="isDeckPaused = true"
    @mouseleave="handleMouseLeave"
    @mousemove="handleMouseMove"
    @wheel.passive="handleWheel"
  >
    <!-- 3D Perspective Card Stack Viewport -->
    <div class="deck-world">
      <div class="deck-floor-glow" aria-hidden="true"></div>

      <article
        v-for="(card, idx) in cards"
        :key="card.id"
        class="deck-card"
        :data-slot="getRelativeOffset(idx)"
        :class="{ 'is-front': idx === activeIndex, 'is-back': idx !== activeIndex }"
        :style="getCardStyle(idx)"
        :aria-hidden="idx !== activeIndex"
        @click="idx !== activeIndex && selectCard(idx)"
      >
        <!-- Crisp Minimal Cascade Header -->
        <header class="card-chrome">
          <div class="chrome-left">
            <span class="mini-dots" aria-hidden="true"><i></i><i></i><i></i></span>
            <span class="card-num">{{ card.num }}</span>
            <component :is="card.icon" class="w-3.5 h-3.5 chrome-icon" />
            <span class="card-title">{{ card.label }}</span>
          </div>
        </header>

        <!-- Card Body -->
        <div class="card-body">
          <!-- CARD 1: Session Collaboration -->
          <div v-if="card.id === 'sessionCollab'" class="scene scene-session">
            <div class="flow-tabs" role="group" aria-label="Session Collaboration Flow Steps">
              <button
                v-for="(label, sIdx) in sessionSteps"
                :key="sIdx"
                type="button"
                class="flow-tab"
                :class="{ active: sessionStep === sIdx, done: sessionStep > sIdx }"
                @click.stop="selectSessionStep(sIdx)"
              >
                {{ label }}
              </button>
            </div>

            <div class="preinput-card">
              <div class="preinput-head">
                <span class="preinput-title">{{ $t('portal.stage.sessionCollab.preinput.title') }}</span>
                <div class="member-chips">
                  <span class="m-tag m-alex done">
                    <i class="m-dot"></i>{{ $t('portal.stage.sessionCollab.preinput.tag_alex') }}
                  </span>
                  <span class="m-tag m-lin" :class="{ done: sessionStep >= 1 }">
                    <i class="m-dot"></i>{{ $t('portal.stage.sessionCollab.preinput.tag_lin') }}
                  </span>
                  <span class="m-tag m-maya" :class="{ done: sessionStep >= 1 && mayaJoined }">
                    <i class="m-dot"></i>{{ $t('portal.stage.sessionCollab.preinput.tag_maya') }}
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

            <div class="flow-stream-zone">
              <Transition name="batch-swap" mode="out-in">
                <div v-if="sessionStep < 2" :key="`wait-${sessionStep}`" class="preinput-wait-line">
                  <span class="wait-dot" :class="{ ready: sessionStep === 1 }"></span>
                  <span>
                    {{ sessionStep === 0
                      ? $t('portal.stage.sessionCollab.preinput.hint_wait')
                      : $t('portal.stage.sessionCollab.preinput.hint_ready') }}
                  </span>
                </div>

                <div v-else key="live-batches" class="chat-batches">
                  <div class="chat-row right">
                    <div class="role-bubble owner">
                      <div class="bubble-meta right">
                        <span class="role-name owner">{{ $t('portal.stage.sessionCollab.roles.merged') }}</span>
                      </div>
                      <div class="bubble-copy">{{ $t('portal.stage.sessionCollab.merged_msg') }}</div>
                    </div>
                    <span class="role-avatar owner">A+</span>
                  </div>

                  <div class="chat-row left">
                    <span class="role-avatar ai"><Bot class="w-3.5 h-3.5" /></span>
                    <div class="role-bubble ai">
                      <div class="bubble-meta">
                        <span class="role-name ai">{{ $t('portal.stage.sessionCollab.roles.ai') }}</span>
                        <span class="ai-live-dots" aria-hidden="true"><i></i><i></i><i></i></span>
                      </div>
                      <div class="bubble-copy">{{ $t('portal.stage.sessionCollab.ai_msg') }}</div>
                    </div>
                  </div>

                  <Transition name="batch-pop">
                    <div v-if="sessionStep >= 3" class="batch-2-pair">
                      <div class="chat-row left">
                        <span class="role-avatar collab">L</span>
                        <div class="role-bubble collab">
                          <div class="bubble-meta">
                            <span class="role-name">{{ $t('portal.stage.sessionCollab.roles.collaborator') }}</span>
                            <span class="diff-chip"><Code class="w-3 h-3" /> {{ $t('portal.stage.sessionCollab.annotation') }}</span>
                          </div>
                          <div class="bubble-copy">{{ $t('portal.stage.sessionCollab.collab_msg') }}</div>
                        </div>
                      </div>

                      <div class="chat-row right">
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

          <!-- CARD 2: Authentic DOCX / MD Canvas Annotation, Inline Discussion & In-Place Tracked Revision -->
          <div v-else-if="card.id === 'docReview'" class="scene scene-doc">
            <div class="flow-tabs" role="group" aria-label="Document Review Flow Steps">
              <button
                v-for="(label, sIdx) in docSteps"
                :key="sIdx"
                type="button"
                class="flow-tab"
                :class="{ active: docStep === sIdx, done: docStep > sIdx }"
                @click.stop="selectDocStep(sIdx)"
              >
                {{ label }}
              </button>
            </div>

            <!-- Rendered Original Document Sheet + Right Reviewer Gutter -->
            <div class="doc-sheet">
              <div class="doc-sheet-head">
                <span class="doc-file">
                  <FileText class="w-3 h-3 text-slate-500" />
                  <span>{{ $t('portal.stage.docReview.file_name') }}</span>
                </span>
                <span class="doc-ver" :class="{ published: docStep === 3 }">
                  {{ docStep === 3 ? $t('portal.stage.docReview.version_new') : $t('portal.stage.docReview.version_old') }}
                </span>
              </div>

              <div class="doc-sheet-body">
                <div class="doc-paper">
                  <div class="doc-sec-title">{{ $t('portal.stage.docReview.section_title') }}</div>
                  <p class="doc-paragraph">
                    <span>{{ $t('portal.stage.docReview.doc_prefix') }}</span>
                    <mark v-if="docStep === 0" class="doc-mark sweep">{{ $t('portal.stage.docReview.doc_target_old') }}</mark>
                    <mark v-else-if="docStep === 1" class="doc-mark anchored">{{ $t('portal.stage.docReview.doc_target_old') }}</mark>
                    <template v-else-if="docStep === 2">
                      <del class="inline-del">{{ $t('portal.stage.docReview.doc_target_old') }}</del>
                      <ins class="inline-ins">{{ $t('portal.stage.docReview.doc_target_new') }}</ins>
                    </template>
                    <span v-else class="inline-clean">{{ $t('portal.stage.docReview.doc_target_new') }}</span>
                    <span>{{ $t('portal.stage.docReview.doc_suffix') }}</span>
                  </p>
                </div>

                <!-- Right Annotation Avatar Rail (mirrors ReviewAnnotationRail.vue) -->
                <div class="doc-rail" aria-hidden="true">
                  <span class="rail-avatar l" :class="{ resolved: docStep >= 2 }">L</span>
                  <span v-if="docStep >= 1" class="rail-avatar a" :class="{ resolved: docStep >= 2 }">A</span>
                </div>
              </div>
            </div>

            <!-- Contextual Thread / Native Revision Acceptance Zone -->
            <div class="doc-thread-zone">
              <Transition name="batch-swap" mode="out-in">
                <div v-if="docStep === 0" key="doc-step-0" class="doc-thread-row muted">
                  <span class="t-dot sky"></span>
                  <span>{{ $t('portal.stage.docReview.thread_selected') }}</span>
                </div>

                <div v-else-if="docStep === 1" key="doc-step-1" class="doc-thread-card">
                  <div class="t-msg">
                    <span class="t-dot emerald"></span>
                    <span class="t-text">{{ $t('portal.stage.docReview.thread_lin') }}</span>
                  </div>
                  <div class="t-msg">
                    <span class="t-dot sky"></span>
                    <span class="t-text">{{ $t('portal.stage.docReview.thread_ai') }}</span>
                    <span class="t-status">
                      <Check class="w-3 h-3" />
                      {{ $t('portal.stage.docReview.thread_resolved') }}
                    </span>
                  </div>
                </div>

                <div v-else-if="docStep === 2" key="doc-step-2" class="doc-rev-bar">
                  <span class="rev-meta">{{ $t('portal.stage.docReview.rev_item') }}</span>
                  <span class="rev-accept-btn">
                    <Check class="w-3 h-3" />
                    {{ $t('portal.stage.docReview.rev_accept') }}
                  </span>
                </div>

                <div v-else key="doc-step-3" class="doc-thread-row success">
                  <Check class="w-3.5 h-3.5 text-emerald-600" />
                  <span>{{ $t('portal.stage.docReview.rev_published') }}</span>
                </div>
              </Transition>
            </div>
          </div>

          <!-- CARD 3: Cloud Server <-> Local IDE Live Code Sync -->
          <div v-else-if="card.id === 'localCollab'" class="scene scene-local">
            <div class="flow-tabs" role="group" aria-label="Local Collaboration Sync Steps">
              <button
                v-for="(label, sIdx) in localSteps"
                :key="sIdx"
                type="button"
                class="flow-tab"
                :class="{ active: localStep === sIdx, done: localStep > sIdx }"
                @click.stop="selectLocalStep(sIdx)"
              >
                {{ label }}
              </button>
            </div>

            <div class="local-arena">
              <div class="code-pane">
                <div class="pane-head">
                  <span class="pane-title">
                    <span class="pane-dot sky"></span>
                    {{ $t('portal.stage.localCollab.cloud_title') }}
                  </span>
                  <span class="pane-status" :class="`step-${localStep}`">{{ localCloudBadge }}</span>
                </div>
                <div class="pane-file">
                  <Code class="w-3 h-3 text-slate-500" />
                  <span>src/auth/guard.ts</span>
                  <span class="line-ref">Worktree</span>
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

              <div class="ipc-bridge">
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

              <div class="code-pane">
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
          </div>

          <!-- CARD 4 (Preserved): Asset Whiteboard & Live Presence -->
          <div v-else class="scene scene-whiteboard">
            <div class="wb-canvas">
              <div class="presence-avatars" aria-hidden="true">
                <span class="avatar-dot a1">A</span>
                <span class="avatar-dot a2">L</span>
              </div>

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
        </div>
      </article>
    </div>

    <!-- Borderless Minimal 3D Deck Stepper -->
    <div class="deck-nav">
      <button
        type="button"
        class="dock-arrow"
        :title="$t('portal.stage.deck_prev')"
        :aria-label="$t('portal.stage.deck_prev')"
        @click="stepDeck(-1)"
      >
        <ChevronLeft class="w-4 h-4" />
      </button>

      <div class="dock-bars" role="tablist" aria-label="3D Card Deck Selector">
        <button
          v-for="(card, idx) in cards"
          :key="card.id"
          type="button"
          role="tab"
          :aria-selected="idx === activeIndex"
          :title="card.label"
          :aria-label="card.label"
          class="dock-bar"
          :class="{ active: idx === activeIndex }"
          @click="selectCard(idx)"
        ></button>
      </div>

      <button
        type="button"
        class="dock-arrow"
        :title="$t('portal.stage.deck_next')"
        :aria-label="$t('portal.stage.deck_next')"
        @click="stepDeck(1)"
      >
        <ChevronRight class="w-4 h-4" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.deck-stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  user-select: none;
}

.deck-world {
  position: relative;
  width: 100%;
  height: 482px;
  perspective: 1450px;
}

.deck-floor-glow {
  position: absolute;
  left: 8%;
  right: 14%;
  bottom: 6px;
  height: 34px;
  background: radial-gradient(ellipse at center, rgba(15, 23, 42, 0.14) 0%, transparent 72%);
  filter: blur(14px);
  z-index: 1;
  pointer-events: none;
}

.deck-card {
  position: absolute;
  left: 0;
  top: 88px;
  width: calc(100% - 62px);
  height: 384px;
  background: #ffffff;
  border-radius: 1.25rem;
  border: 1px solid rgba(226, 232, 240, 0.95);
  box-shadow:
    0 18px 40px -18px rgba(15, 23, 42, 0.14),
    0 4px 12px -4px rgba(15, 23, 42, 0.06);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transform-origin: 50% 0%;
  transition:
    transform 0.58s cubic-bezier(0.22, 1, 0.36, 1),
    opacity 0.42s ease,
    background-color 0.4s ease,
    box-shadow 0.4s ease,
    border-color 0.35s ease;
}

.deck-card.is-front {
  border-color: rgba(203, 213, 225, 0.95);
  box-shadow:
    0 28px 56px -20px rgba(15, 23, 42, 0.18),
    0 10px 24px -10px rgba(15, 23, 42, 0.08);
  -webkit-font-smoothing: antialiased;
}

.deck-card.is-back { cursor: pointer; }
.deck-card[data-slot='1'] { background: #fbfcfe; border-color: #e2e8f0; }
.deck-card[data-slot='2'] { background: #f5f8fc; border-color: #dbe3ee; }
.deck-card[data-slot='3'] { background: #eef3f9; border-color: #d2dce9; }

.deck-card.is-back:hover {
  border-color: #94a3b8;
  box-shadow: 0 22px 44px -18px rgba(15, 23, 42, 0.18);
}

/* Minimal Cascade Header */
.card-chrome {
  height: 28px;
  padding: 0 0.9rem;
  display: flex;
  align-items: center;
  background: #f8fafc;
  border-bottom: 1px solid #eef2f6;
  flex-shrink: 0;
}

.chrome-left {
  display: inline-flex;
  align-items: center;
  gap: 0.38rem;
}

.mini-dots { display: inline-flex; gap: 4px; margin-right: 0.15rem; }
.mini-dots i { width: 6px; height: 6px; border-radius: 9999px; }
.mini-dots i:nth-child(1) { background: #fca5a5; }
.mini-dots i:nth-child(2) { background: #fcd34d; }
.mini-dots i:nth-child(3) { background: #86efac; }

.card-num { font-family: var(--font-mono, monospace); font-size: 0.62rem; font-weight: 700; color: #64748b; }
.chrome-icon { color: #0284c7; }
.card-title { font-size: 0.7rem; font-weight: 700; color: #0f172a; }
.deck-card.is-back .card-title { color: #475569; }

.card-body {
  flex: 1;
  padding: 0.85rem 1.05rem;
  background: #ffffff;
  overflow: hidden;
  transition: opacity 0.32s ease;
}

.deck-card[data-slot='1'] .card-body { opacity: 0.12; pointer-events: none; }
.deck-card[data-slot='2'] .card-body { opacity: 0.06; pointer-events: none; }
.deck-card[data-slot='3'] .card-body { opacity: 0.03; pointer-events: none; }

/* Borderless Minimal Deck Navigation */
.deck-nav {
  margin-top: 0.45rem;
  display: inline-flex;
  align-items: center;
  gap: 0.6rem;
}

.dock-arrow {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: #64748b;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: color 0.2s ease, background-color 0.2s ease;
}

.dock-arrow:hover {
  background: rgba(241, 245, 249, 0.9);
  color: #0f172a;
}

.dock-bars {
  display: inline-flex;
  align-items: center;
  gap: 0.36rem;
}

.dock-bar {
  width: 10px;
  height: 4px;
  padding: 0;
  border: none;
  border-radius: 2px;
  background: #cbd5e1;
  cursor: pointer;
  transition: width 0.28s cubic-bezier(0.22, 1, 0.36, 1), background-color 0.25s ease;
}

.dock-bar:hover { background: #94a3b8; }
.dock-bar.active { width: 24px; background: #0f172a; }

/* Inner Scene Styles */
.scene {
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 0.5rem;
}

.flow-tabs {
  display: flex;
  align-items: center;
  gap: 0.9rem;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 0.35rem;
}

.flow-tab {
  border: none;
  background: transparent;
  color: #94a3b8;
  font-size: 0.64rem;
  font-weight: 600;
  padding: 0.1rem 0 0.22rem;
  position: relative;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.2s ease;
}

.flow-tab.done { color: #059669; }
.flow-tab.active { color: #0f172a; }
.flow-tab.active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -0.36rem;
  height: 2px;
  background: #0ea5e9;
  border-radius: 1px;
}

/* Scene 1: Collaborative Pre-Input + Batched Business Flow */
.preinput-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 0.48rem 0.68rem;
}

.preinput-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.35rem;
}

.preinput-title { font-size: 0.64rem; font-weight: 700; color: #0f172a; white-space: nowrap; }
.member-chips { display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap; }

.m-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.24rem;
  font-size: 0.6rem;
  font-weight: 600;
  color: #94a3b8;
  transition: color 0.22s ease;
}

.m-dot { width: 6px; height: 6px; border-radius: 9999px; background: #cbd5e1; }
.m-alex.done { color: #0369a1; }
.m-alex.done .m-dot { background: #0284c7; }
.m-lin.done { color: #047857; }
.m-lin.done .m-dot { background: #10b981; }
.m-maya.done { color: #b45309; }
.m-maya.done .m-dot { background: #f59e0b; }

.preinput-timer {
  margin-left: auto;
  font-family: var(--font-mono, monospace);
  font-size: 0.6rem;
  font-weight: 600;
  color: #64748b;
  white-space: nowrap;
}
.preinput-timer.merged { font-family: inherit; color: #059669; }

.preinput-doc {
  font-size: 0.68rem;
  line-height: 1.56;
  color: #0f172a;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  padding: 0.36rem 0.54rem;
}

.doc-seg { display: inline; padding: 1px 2px; border-bottom: 2px solid transparent; margin-right: 2px; }
.seg-alex { background: rgba(14, 165, 233, 0.08); border-bottom-color: #0284c7; }
.seg-lin { background: rgba(16, 185, 129, 0.1); border-bottom-color: #10b981; }
.seg-maya { background: rgba(245, 158, 11, 0.1); border-bottom-color: #f59e0b; }

.typing-caret {
  display: inline-block;
  width: 2px;
  height: 0.8em;
  background: #0284c7;
  vertical-align: middle;
  margin-left: 2px;
  animation: blinkCaret 0.8s steps(2, start) infinite;
}
@keyframes blinkCaret { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } }

.flow-stream-zone { flex: 1; display: flex; flex-direction: column; justify-content: flex-start; min-height: 0; }

.preinput-wait-line {
  margin-top: 0.35rem;
  display: flex;
  align-items: center;
  gap: 0.42rem;
  padding: 0.2rem 0.25rem;
  font-size: 0.67rem;
  font-weight: 500;
  color: #64748b;
}

.wait-dot { width: 6px; height: 6px; border-radius: 9999px; background: #94a3b8; flex-shrink: 0; }
.wait-dot.ready { background: #10b981; }

.chat-batches,
.batch-2-pair {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.chat-row {
  display: flex;
  align-items: flex-end;
  gap: 0.38rem;
  animation: msgReveal 0.34s cubic-bezier(0.22, 1, 0.36, 1) both;
}
.chat-row.right { justify-content: flex-end; }
@keyframes msgReveal { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

.role-avatar {
  width: 19px;
  height: 19px;
  border-radius: 9999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.55rem;
  font-weight: 700;
  color: #ffffff;
  flex-shrink: 0;
}
.role-avatar.collab { background: #10b981; }
.role-avatar.owner { background: #0f172a; }
.role-avatar.ai { background: #0284c7; }

.role-bubble {
  max-width: 86%;
  padding: 0.28rem 0.58rem;
  border-radius: 8px;
  font-size: 0.64rem;
  line-height: 1.32;
}
.role-bubble.owner { background: #0f172a; color: #ffffff; border-bottom-right-radius: 3px; }
.role-bubble.steer { background: #f8fafc; border: 1px solid #e2e8f0; color: #0f172a; border-bottom-right-radius: 3px; }
.role-bubble.collab { background: #f0fdf4; border: 1px solid #d1fae5; color: #064e3b; border-bottom-left-radius: 3px; }
.role-bubble.ai { background: #ffffff; border: 1px solid #e2e8f0; color: #0f172a; border-bottom-left-radius: 3px; }

.bubble-meta { display: flex; align-items: center; gap: 0.35rem; margin-bottom: 0.05rem; }
.bubble-meta.right { justify-content: flex-end; }
.role-name { font-size: 0.56rem; font-weight: 700; color: #059669; }
.role-name.owner { color: rgba(255, 255, 255, 0.82); }
.role-name.steer { color: #334155; }
.role-name.ai { color: #0284c7; }

.diff-chip {
  font-family: var(--font-mono, monospace);
  font-size: 0.54rem;
  color: #475569;
  display: inline-flex;
  align-items: center;
  gap: 0.16rem;
}

.ai-live-dots { display: inline-flex; gap: 3px; margin-left: auto; }
.ai-live-dots i {
  width: 3.5px;
  height: 3.5px;
  border-radius: 9999px;
  background: #64748b;
  animation: dotBounce 1.2s ease-in-out infinite;
}
.ai-live-dots i:nth-child(2) { animation-delay: 0.2s; }
.ai-live-dots i:nth-child(3) { animation-delay: 0.4s; }
@keyframes dotBounce { 0%, 80%, 100% { opacity: 0.3; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-2px); } }
.bubble-copy { font-weight: 500; }

/* Scene 2: Authentic DOCX / MD Canvas Review & In-Place Tracked Revision */
.doc-sheet {
  flex: 1;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.doc-sheet-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.4rem 0.72rem;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}

.doc-file {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.65rem;
  font-weight: 700;
  color: #0f172a;
}

.doc-ver {
  font-family: var(--font-mono, monospace);
  font-size: 0.6rem;
  font-weight: 700;
  color: #64748b;
}

.doc-ver.published { color: #059669; }

.doc-sheet-body {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.75rem 0.85rem;
}

.doc-paper {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.doc-sec-title {
  font-size: 0.74rem;
  font-weight: 700;
  color: #0f172a;
}

.doc-paragraph {
  margin: 0;
  font-size: 0.72rem;
  line-height: 1.85;
  color: #334155;
}

.doc-mark {
  background: transparent;
  color: #0f172a;
  padding: 1px 4px;
  border-radius: 3px;
}

.doc-mark.sweep {
  border-bottom: 2px solid #0ea5e9;
  background: linear-gradient(90deg, rgba(186, 230, 253, 0.55) 50%, rgba(241, 245, 249, 0.3) 50%);
  background-size: 200% 100%;
  animation: selectSweep 2.6s ease-in-out infinite;
}

@keyframes selectSweep {
  0%, 15% { background-position: 100% 0; }
  55%, 85% { background-position: 0% 0; }
  100% { background-position: 100% 0; }
}

.doc-mark.anchored {
  background: rgba(254, 243, 199, 0.75);
  border-bottom: 2px solid #f59e0b;
}

.inline-del {
  background: #fef2f2;
  color: #b91c1c;
  padding: 1px 4px;
  border-radius: 3px;
  text-decoration: line-through;
  margin-right: 3px;
}

.inline-ins {
  background: #ecfdf5;
  color: #047857;
  font-weight: 600;
  padding: 1px 4px;
  border-radius: 3px;
  text-decoration: none;
  border-bottom: 2px solid #10b981;
}

.inline-clean {
  color: #047857;
  font-weight: 600;
  border-bottom: 1.5px solid #a7f3d0;
}

/* Right Reviewer Gutter */
.doc-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
  padding-left: 0.55rem;
  border-left: 1px solid #f1f5f9;
}

.rail-avatar {
  width: 21px;
  height: 21px;
  border-radius: 9999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.58rem;
  font-weight: 700;
  color: #ffffff;
  transition: opacity 0.25s ease;
}

.rail-avatar.l { background: #10b981; }
.rail-avatar.a { background: #0f172a; }
.rail-avatar.resolved { opacity: 0.45; }

/* Bottom Thread / Revision Zone */
.doc-thread-zone {
  min-height: 54px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.doc-thread-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.67rem;
  font-weight: 600;
  padding: 0.4rem 0.2rem;
}

.doc-thread-row.muted { color: #64748b; }
.doc-thread-row.success { color: #047857; }

.doc-thread-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0.36rem 0.65rem;
  display: flex;
  flex-direction: column;
  gap: 0.22rem;
}

.t-msg {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.65rem;
  color: #334155;
}

.t-dot {
  width: 6px;
  height: 6px;
  border-radius: 9999px;
  flex-shrink: 0;
}
.t-dot.emerald { background: #10b981; }
.t-dot.sky { background: #0ea5e9; }

.t-text { flex: 1; font-weight: 500; }

.t-status {
  display: inline-flex;
  align-items: center;
  gap: 0.18rem;
  font-size: 0.62rem;
  font-weight: 700;
  color: #059669;
}

.doc-rev-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.38rem 0.68rem;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.rev-meta { font-size: 0.66rem; font-weight: 600; color: #334155; }

.rev-accept-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.24rem;
  padding: 0.26rem 0.64rem;
  border-radius: 6px;
  background: #0ea5e9;
  color: #ffffff;
  font-size: 0.65rem;
  font-weight: 600;
}

/* Scene 3: Dual-Pane Local Collaboration */
.local-arena {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 64px minmax(0, 1fr);
  align-items: stretch;
  gap: 0.42rem;
  min-height: 0;
}

.code-pane {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.22rem;
  padding: 0.36rem 0.55rem;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}
.pane-title { display: inline-flex; align-items: center; gap: 0.28rem; font-size: 0.63rem; font-weight: 700; color: #0f172a; white-space: nowrap; }
.pane-dot { width: 6px; height: 6px; border-radius: 9999px; }
.pane-dot.sky { background: #0ea5e9; }
.pane-dot.emerald { background: #10b981; }

.pane-status { font-size: 0.56rem; font-weight: 600; color: #475569; white-space: nowrap; }
.pane-status.step-1.local { color: #b45309; }
.pane-status.step-2 { color: #0284c7; }
.pane-status.step-3 { color: #059669; }

.pane-file {
  display: flex;
  align-items: center;
  gap: 0.26rem;
  padding: 0.26rem 0.55rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.59rem;
  font-weight: 600;
  color: #334155;
  border-bottom: 1px solid #f1f5f9;
}
.line-ref { margin-left: auto; font-size: 0.53rem; color: #64748b; }

.pane-code {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  font-family: var(--font-mono, monospace);
  font-size: 0.58rem;
  line-height: 1.76;
  padding: 0.22rem 0;
}

.c-line { display: grid; grid-template-columns: 19px 10px 1fr; align-items: center; padding: 0.05rem 0.42rem; white-space: nowrap; }
.c-line .ln { color: #94a3b8; font-size: 0.52rem; }
.c-line .sg { font-weight: 700; font-size: 0.55rem; }
.c-line.ctx { color: #475569; }
.c-line.cloud-add { background: #f8fafc; color: #0369a1; font-weight: 600; }
.c-line.del { background: #fef2f2; color: #b91c1c; }
.c-line.del code { text-decoration: line-through; opacity: 0.85; }
.c-line.add { background: #ecfdf5; color: #047857; font-weight: 600; }
.c-line.synced-ok { background: #ecfdf5; color: #047857; font-weight: 600; animation: syncedFlash 1.2s ease both; }
@keyframes syncedFlash { 0% { background: #bbf7d0; } 100% { background: #ecfdf5; } }
.animated-insert { box-shadow: inset 2px 0 0 #10b981; animation: diffAppear 0.35s ease both; }
@keyframes diffAppear { from { opacity: 0; transform: translateX(-4px); } to { opacity: 1; transform: translateX(0); } }

.ipc-bridge { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0.22rem; }
.ipc-kicker { font-family: var(--font-mono, monospace); font-size: 0.56rem; font-weight: 700; color: #64748b; }
.ipc-rail { position: relative; width: 100%; height: 24px; display: flex; align-items: center; justify-content: center; }
.ipc-rail svg { width: 100%; height: 24px; }
.ipc-line { stroke: #cbd5e1; stroke-width: 1.8; stroke-dasharray: 4 3; }
.ipc-line.active { stroke: #64748b; }
.ipc-line.clean { stroke: #10b981; stroke-dasharray: none; }
.dir-arrow { position: absolute; top: -6px; font-size: 0.72rem; font-weight: 700; }
.dir-arrow.right { color: #0284c7; }
.dir-arrow.left { color: #059669; }
.ipc-check { position: absolute; background: #ffffff; border-radius: 9999px; }
.watch-pulse { position: absolute; width: 7px; height: 7px; border-radius: 9999px; background: #f59e0b; }
.ipc-caption { font-size: 0.54rem; font-weight: 600; color: #475569; text-align: center; line-height: 1.2; }

/* Scene 4: Whiteboard */
.presence-avatars {
  position: absolute;
  top: 0.65rem;
  right: 0.75rem;
  z-index: 3;
  display: flex;
}
.avatar-dot {
  width: 21px;
  height: 21px;
  border-radius: 9999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.62rem;
  font-weight: 700;
  color: #ffffff;
  border: 2px solid #ffffff;
}
.avatar-dot.a1 { background: #0ea5e9; }
.avatar-dot.a2 { background: #2563eb; margin-left: -6px; }

.wb-canvas {
  position: relative;
  flex: 1;
  border-radius: 10px;
  background-color: #ffffff;
  background-image: radial-gradient(#cbd5e1 1px, transparent 1px);
  background-size: 16px 16px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
}
.wb-svg { position: absolute; inset: 0; width: 100%; height: 100%; z-index: 1; }
.wb-edge { stroke: #cbd5e1; stroke-width: 2; stroke-dasharray: 5 4; fill: none; }
.wb-edge.edge-alt { stroke: #a7f3d0; }
.wb-node {
  position: absolute;
  z-index: 2;
  background: rgba(255, 255, 255, 0.98);
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  padding: 0.45rem 0.68rem;
  box-shadow: 0 6px 16px -6px rgba(15, 23, 42, 0.08);
  display: flex;
  flex-direction: column;
  gap: 0.08rem;
}
.wb-node.is-active { border-color: #cbd5e1; box-shadow: 0 10px 22px -6px rgba(15, 23, 42, 0.14); }
.node-kicker { font-family: var(--font-mono, monospace); font-size: 0.6rem; font-weight: 700; color: #64748b; }
.node-title { font-size: 0.74rem; font-weight: 700; color: #0f172a; white-space: nowrap; }
.node-1 { left: 6%; top: 15%; }
.node-2 { left: 55.5%; top: 13%; }
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
  background: #0f172a;
  color: #ffffff;
  font-size: 0.58rem;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
}
@keyframes cursorGlide { 0% { transform: translate(0, 0); } 100% { transform: translate(-38px, -22px); } }

/* Inner Transitions */
.batch-swap-enter-active,
.batch-swap-leave-active {
  transition: opacity 0.22s ease, transform 0.22s cubic-bezier(0.22, 1, 0.36, 1);
}
.batch-swap-enter-from { opacity: 0; transform: translateY(6px); }
.batch-swap-leave-to { opacity: 0; transform: translateY(-4px); }

.seg-pop-enter-active,
.batch-pop-enter-active {
  transition: opacity 0.28s ease, transform 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}
.seg-pop-leave-active,
.batch-pop-leave-active { transition: opacity 0.1s ease; }
.seg-pop-enter-from { opacity: 0; transform: translateX(-4px); }
.seg-pop-leave-to,
.batch-pop-leave-to { opacity: 0; }
.batch-pop-enter-from { opacity: 0; transform: translateY(6px); }

@media (max-width: 768px) {
  .deck-world { height: 454px; }
  .deck-card { top: 72px; width: calc(100% - 26px); height: 374px; }
}

@media (prefers-reduced-motion: reduce) {
  .deck-card,
  .typing-caret,
  .chat-row,
  .ai-live-dots i,
  .doc-mark.sweep,
  .animated-insert,
  .synced-ok,
  .wb-cursor {
    animation: none !important;
    transition: none !important;
  }
}
</style>
