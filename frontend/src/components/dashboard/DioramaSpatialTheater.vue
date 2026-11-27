<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, shallowRef, useTemplateRef, watch, type CSSProperties } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import UserAvatar from '@/components/user/UserAvatar.vue'
import { ChevronLeft, ChevronRight, MessageSquare } from '@/components/icons'
import { isActiveTaskStatus, taskDisplayStatus, taskStatusKey } from '@/utils/taskStatus'
import { computeSpatialTheaterLayouts } from '@/utils/spatialTheaterLayout'
import type { DioramaMemberItem, DioramaTaskItem } from '@/types/dashboardDiorama'

const MAX_THEATER_CARDS = 6
const AUTOPLAY_INTERVAL_MS = 4500

const props = defineProps<{
  workspaceId: string
  tasks: DioramaTaskItem[]
  members: DioramaMemberItem[]
  activeMemberId: string | null
  pinnedTaskId: string | null
  hoveredTaskId: string | null
  autoplay: boolean
  hasRepos: boolean
}>()

const emit = defineEmits<{
  'toggle-pin-task': [taskId: string]
  'clear-task-focus': []
}>()

const { t, locale } = useI18n()
const router = useRouter()

const stageRef = useTemplateRef<HTMLDivElement>('stageRef')
const stageSize = shallowRef({ width: 920, height: 500 })
const selectedTaskId = shallowRef<string | null>(null)
const stageHovered = shallowRef(false)
const parallax = shallowRef({ x: 0, y: 0 })
let autoplayTimer: number | undefined
let resizeObserver: ResizeObserver | undefined
let lastWheelAt = Number.NEGATIVE_INFINITY

const memberById = computed(() => new Map(props.members.map(m => [m.id, m])))

const memberTasks = computed(() => props.activeMemberId
  ? props.tasks.filter(task => task.creator_id === props.activeMemberId)
  : props.tasks)
const pinnedTask = computed(() => props.tasks.find(task => task.id === props.pinnedTaskId))
const hoveredTask = computed(() => props.tasks.find(task => task.id === props.hoveredTaskId))
const focusedTask = computed(() => hoveredTask.value ?? pinnedTask.value)

const theaterTasks = computed(() => {
  const base = memberTasks.value.slice(0, MAX_THEATER_CARDS)
  const focused = focusedTask.value
  if (!focused || base.some(task => task.id === focused.id)) return base
  return [focused, ...base.slice(0, MAX_THEATER_CARDS - 1)]
})
const activeIndex = computed(() => {
  const taskId = focusedTask.value?.id ?? selectedTaskId.value
  return Math.max(0, theaterTasks.value.findIndex(task => task.id === taskId))
})

const isPaused = computed(() => (
  !props.autoplay
  || stageHovered.value
  || Boolean(focusedTask.value)
  || theaterTasks.value.length < 2
))

const pauseReasonLabel = computed(() => {
  if (hoveredTask.value) return t('dashboard.diorama.theater_paused_preview')
  if (pinnedTask.value) return t('dashboard.diorama.theater_paused_pinned')
  if (stageHovered.value) return t('dashboard.diorama.theater_paused_preview')
  if (!props.autoplay) return t('dashboard.diorama.theater_paused_manual')
  return ''
})

const frontTask = computed(() => theaterTasks.value[activeIndex.value] ?? null)

function statusTone(task: DioramaTaskItem): 'blocked' | 'running' | 'completed' | 'failed' | 'neutral' {
  const st = taskDisplayStatus(task.status, task.interrupt_kind)
  if (st === 'AWAITING_INPUT' || st === 'ABNORMAL_INTERRUPTED' || st === 'INTERRUPTED') return 'blocked'
  if (st === 'RUNNING' || st === 'ROUND_COMPLETED' || st === 'PROVISIONING') return 'running'
  if (st === 'COMPLETED') return 'completed'
  if (st === 'FAILED') return 'failed'
  return 'neutral'
}

const floorAuraStyle = computed<CSSProperties>(() => {
  const task = frontTask.value
  if (!task) return { opacity: 0 }
  const tone = statusTone(task)
  const gradients: Record<typeof tone, string> = {
    blocked: 'radial-gradient(circle, rgba(245,158,11,0.18) 0%, rgba(245,158,11,0.03) 55%, transparent 75%)',
    running: 'radial-gradient(circle, rgba(14,165,233,0.18) 0%, rgba(14,165,233,0.03) 55%, transparent 75%)',
    completed: 'radial-gradient(circle, rgba(16,185,129,0.16) 0%, rgba(16,185,129,0.03) 55%, transparent 75%)',
    failed: 'radial-gradient(circle, rgba(244,63,94,0.15) 0%, rgba(244,63,94,0.03) 55%, transparent 75%)',
    neutral: 'radial-gradient(circle, rgba(99,102,241,0.14) 0%, rgba(99,102,241,0.02) 55%, transparent 75%)',
  }
  return { background: gradients[tone], opacity: 1 }
})

const floorParallaxStyle = computed<CSSProperties>(() => ({
  transform: `rotateX(70deg) translate3d(${parallax.value.x * 0.9}px, ${parallax.value.y * 0.9}px, -140px)`,
}))

const spatialLayouts = computed(() => computeSpatialTheaterLayouts({
  ids: theaterTasks.value.map(task => task.id),
  activeIndex: activeIndex.value,
  stageWidth: stageSize.value.width,
  stageHeight: stageSize.value.height,
}))

const cardStyles = computed<CSSProperties[]>(() => spatialLayouts.value.map(item => {
  if (item.isFront) {
    return {
      zIndex: item.zIndex,
      transform: `translate3d(${item.x}px, ${item.y}px, 0px)`,
    }
  }
  const px = Math.round(item.x + parallax.value.x * (-item.z / 95))
  const py = Math.round(item.y + parallax.value.y * (-item.z / 95))
  return {
    zIndex: item.zIndex,
    '--card-content-opacity': item.opacity,
    transform: `translate3d(${px}px, ${py}px, ${item.z}px) rotateX(${item.rotX}deg) rotateY(${item.rotY}deg) rotateZ(${item.rotZ}deg) scale(${item.scale})`,
  }
}))

function formatTaskDate(task: DioramaTaskItem): string {
  const raw = task.last_activity_at
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const isSameDay = (a: Date, b: Date) => (
    a.getFullYear() === b.getFullYear()
    && a.getMonth() === b.getMonth()
    && a.getDate() === b.getDate()
  )
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  const isZh = String(locale.value || '').startsWith('zh')
  if (isSameDay(date, now)) return isZh ? `今天 ${hh}:${mm}` : `Today ${hh}:${mm}`
  if (isSameDay(date, yesterday)) return isZh ? `昨天 ${hh}:${mm}` : `Yesterday ${hh}:${mm}`
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${m}-${d} ${hh}:${mm}`
}

const taskDateLabels = computed(() => new Map(theaterTasks.value.map(task => [task.id, formatTaskDate(task)])))

function taskTypeLabel(taskType: string): string {
  return String(taskType || '').toUpperCase() === 'DIAGNOSIS'
    ? t('task_types.diagnosis_short')
    : t('task_types.development_short')
}

function selectTask(taskId: string) {
  selectedTaskId.value = taskId
  if (props.pinnedTaskId || props.hoveredTaskId) emit('clear-task-focus')
}

function step(delta: -1 | 1) {
  const tasks = theaterTasks.value
  if (tasks.length < 2) return false
  const nextIndex = (activeIndex.value + delta + tasks.length) % tasks.length
  selectTask(tasks[nextIndex].id)
  return true
}

function handleCardClick(taskId: string) {
  if (taskId !== frontTask.value?.id) {
    selectTask(taskId)
    return
  }
  selectedTaskId.value = taskId
  emit('toggle-pin-task', taskId)
}

function openTaskChat(taskId: string) {
  void router.push({ name: 'taskChat', params: { wsId: props.workspaceId, taskId } })
}

function openRequirement(reqId: string) {
  void router.push({
    name: 'workspaceAssetsRequirementDetail',
    params: { wsId: props.workspaceId, requirementId: reqId },
  })
}

function handleMouseMove(e: MouseEvent) {
  if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
    return
  }
  const el = e.currentTarget as HTMLElement | null
  if (!el) return
  const rect = el.getBoundingClientRect()
  if (!rect.width || !rect.height) return
  const nx = ((e.clientX - rect.left) / rect.width - 0.5) * 2
  const ny = ((e.clientY - rect.top) / rect.height - 0.5) * 2
  parallax.value = { x: -nx * 14, y: -ny * 9 }
}

function handleMouseLeave() {
  stageHovered.value = false
  parallax.value = { x: 0, y: 0 }
}

function handleWheel(e: WheelEvent) {
  if (e.ctrlKey || theaterTasks.value.length < 2) return
  const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY
  if (!delta) return
  e.preventDefault()
  const now = performance.now()
  if (now - lastWheelAt < 260) return
  lastWheelAt = now
  step(delta > 0 ? 1 : -1)
}

function syncAutoplayTimer() {
  if (autoplayTimer !== undefined) {
    window.clearInterval(autoplayTimer)
    autoplayTimer = undefined
  }
  if (isPaused.value) return
  autoplayTimer = window.setInterval(() => {
    if (!isPaused.value) step(1)
  }, AUTOPLAY_INTERVAL_MS)
}

watch(isPaused, () => {
  syncAutoplayTimer()
}, { immediate: true })

function measureStage() {
  const rect = stageRef.value?.getBoundingClientRect()
  if (rect && rect.width > 0 && rect.height > 0) {
    stageSize.value = { width: Math.round(rect.width), height: Math.round(rect.height) }
  }
}

onMounted(() => {
  measureStage()
  if (stageRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(measureStage)
    resizeObserver.observe(stageRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = undefined
  if (autoplayTimer !== undefined) {
    window.clearInterval(autoplayTimer)
    autoplayTimer = undefined
  }
})

defineExpose({ step })
</script>

<template>
  <div
    ref="stageRef"
    class="spatial-stage"
    @mouseenter="stageHovered = true"
    @mouseleave="handleMouseLeave"
    @mousemove="handleMouseMove"
    @wheel="handleWheel"
  >
    <div class="spatial-floor" :style="floorParallaxStyle" aria-hidden="true" />
    <div class="spatial-aura" :style="floorAuraStyle" aria-hidden="true" />

    <!-- Top-left HUD -->
    <div class="hud-top-left">
      <div class="hud-pill">
        <span class="hud-dot" />
        <span class="hud-title">{{ t('dashboard.diorama.theater_title') }}</span>
        <span class="hud-sep">·</span>
        <span class="hud-counter">
          {{ theaterTasks.length ? `${activeIndex + 1} / ${theaterTasks.length}` : '0 / 0' }}
        </span>
      </div>

      <div v-if="pauseReasonLabel && theaterTasks.length > 0" class="hud-pause-pill">
        {{ pauseReasonLabel }}
      </div>
    </div>

    <!-- Empty State -->
    <div v-if="!theaterTasks.length" class="empty-theater-card">
      <p class="empty-title">{{ t('dashboard.diorama.theater_empty') }}</p>
    </div>

    <!-- 3D Glass Carousel World -->
    <div v-else class="spatial-world">
      <article
        v-for="(task, index) in theaterTasks"
        :key="task.id"
        class="spatial-card"
        :class="[
          `tone-${statusTone(task)}`,
          {
            'is-front': index === activeIndex,
            'is-pinned': pinnedTaskId === task.id,
          },
        ]"
        :style="cardStyles[index]"
        @click="handleCardClick(task.id)"
      >
        <div class="card-sheen" aria-hidden="true" />
        <div class="card-inner">
          <header class="card-head">
            <span class="status-badge" :class="`tone-${statusTone(task)}`">
              <span
                class="status-dot"
                :class="{
                  'is-live': isActiveTaskStatus(task.status),
                  'is-blocked': statusTone(task) === 'blocked',
                }"
              />
              <span>{{ t(taskStatusKey(taskDisplayStatus(task.status, task.interrupt_kind))) }}</span>
            </span>
            <time
              v-if="taskDateLabels.get(task.id)"
              class="card-time"
              :datetime="task.last_activity_at ?? undefined"
            >
              {{ taskDateLabels.get(task.id) }}
            </time>
          </header>

          <div class="card-title-block">
            <h3 class="card-title" :title="task.name">{{ task.name }}</h3>
            <div class="card-tags">
              <span class="meta-chip">{{ taskTypeLabel(task.task_type) }}</span>
              <span v-if="hasRepos && task.repos.length" class="meta-chip is-repo">
                {{ t('dashboard.diorama.theater_repos_count', { count: task.repos.length }) }}
              </span>
              <button
                v-if="task.requirement_titles[0]"
                type="button"
                class="meta-chip is-req"
                :title="task.requirement_titles[0]"
                @click.stop="task.requirement_ids[0] && openRequirement(task.requirement_ids[0])"
              >
                {{ t('dashboard.diorama.theater_req_label') }}: {{ task.requirement_titles[0] }}
              </button>
            </div>
          </div>

          <p v-if="task.description" class="card-summary" :title="task.description">
            {{ task.description }}
          </p>

          <footer class="card-foot">
            <div class="creator-info">
              <UserAvatar
                :display-name="task.creator_name || ''"
                :email="memberById.get(task.creator_id)?.email"
                :user-id="task.creator_id"
                :avatar-url="memberById.get(task.creator_id)?.avatar_url"
                :avatar-svg="memberById.get(task.creator_id)?.avatar_svg"
                :accent-color="memberById.get(task.creator_id)?.color"
                size="xs"
              />
              <span class="creator-name">{{ task.creator_name || memberById.get(task.creator_id)?.display_name || '-' }}</span>
            </div>

            <button
              v-if="index === activeIndex"
              type="button"
              class="enter-chat-btn"
              @click.stop="openTaskChat(task.id)"
            >
              <MessageSquare class="btn-mini-icon" />
              <span>{{ t('dashboard.diorama.theater_enter_chat') }}</span>
            </button>
            <span v-else class="side-focus-label">
              {{ t('dashboard.diorama.theater_focus_card') }}
            </span>
          </footer>
        </div>
      </article>
    </div>

    <!-- Bottom Carousel Controls (dots + prev/next only, no timeline bar) -->
    <div v-if="theaterTasks.length > 1" class="carousel-nav-pill">
      <button
        type="button"
        class="nav-step-btn"
        :title="t('dashboard.diorama.theater_prev')"
        @click="step(-1)"
      >
        <ChevronLeft class="nav-icon" />
      </button>
      <div class="nav-dots" role="group" :aria-label="t('dashboard.diorama.theater_title')">
        <button
          v-for="(task, index) in theaterTasks"
          :key="task.id"
          type="button"
          class="nav-dot"
          :class="{ 'is-active': index === activeIndex }"
          :title="task.name"
          :aria-current="index === activeIndex ? 'true' : undefined"
          @click="selectTask(task.id)"
        />
      </div>
      <button
        type="button"
        class="nav-step-btn"
        :title="t('dashboard.diorama.theater_next')"
        @click="step(1)"
      >
        <ChevronRight class="nav-icon" />
      </button>
    </div>

    <div v-if="theaterTasks.length > 1" class="hud-hint">
      {{ t('dashboard.diorama.theater_hint') }}
    </div>
  </div>
</template>

<style scoped>
.spatial-stage {
  position: relative;
  flex: 1;
  min-height: 490px;
  background: radial-gradient(circle at 50% 42%, #fafdff 0%, #f1f5f9 64%, #e8eff7 100%);
  perspective: 1050px;
  perspective-origin: 50% 48%;
  overflow: hidden;
  user-select: none;
}

.spatial-floor {
  position: absolute;
  inset: -100px;
  pointer-events: none;
  transform: rotateX(70deg) translateZ(-140px);
  background-image:
    linear-gradient(to right, rgba(2, 132, 199, 0.1) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(2, 132, 199, 0.1) 1px, transparent 1px);
  background-size: 46px 46px;
  mask-image: radial-gradient(ellipse at center, black 28%, transparent 72%);
  -webkit-mask-image: radial-gradient(ellipse at center, black 28%, transparent 72%);
}

.spatial-aura {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 520px;
  height: 520px;
  margin-left: -260px;
  margin-top: -260px;
  border-radius: 9999px;
  pointer-events: none;
  transform: rotateX(70deg) translateZ(-136px);
  transition: background 0.6s ease, opacity 0.6s ease;
}

.hud-top-left {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 35;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  pointer-events: none;
}

.hud-pill,
.hud-pause-pill,
.carousel-nav-pill {
  pointer-events: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border-radius: var(--radius-full);
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(10px);
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
  font-size: 11.5px;
  color: var(--color-text-body);
}

.hud-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--color-primary-500);
}

.hud-title {
  font-weight: 600;
  color: var(--color-primary-900);
}

.hud-sep {
  color: #cbd5e1;
}

.hud-counter {
  font-family: var(--font-mono);
  color: #64748b;
  font-variant-numeric: tabular-nums;
}

.hud-pause-pill {
  border-color: #bae6fd;
  background: rgba(240, 249, 255, 0.94);
  color: var(--color-primary-700);
  font-weight: 500;
}

.empty-theater-card {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  z-index: 10;
  padding: 22px 28px;
  border-radius: 18px;
  border: 1px solid rgba(226, 232, 240, 0.95);
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(12px);
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
  text-align: center;
}

.empty-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-title);
}

.spatial-world {
  position: absolute;
  inset: 0;
  perspective: inherit;
  perspective-origin: inherit;
  /* Keep perspective on each card while z-index decides which whole card is in front. */
  transform-style: flat;
}

.spatial-card {
  position: absolute;
  inset: 0;
  margin: auto;
  width: min(352px, calc(100% - 40px));
  height: fit-content;
  border-radius: 18px;
  border: 1px solid rgba(226, 232, 240, 0.94);
  background: #fafcfe;
  box-shadow: 0 18px 36px rgba(15, 23, 42, 0.08);
  backface-visibility: hidden;
  -webkit-font-smoothing: antialiased;
  transition:
    transform 0.72s cubic-bezier(0.22, 1, 0.36, 1),
    box-shadow 0.52s ease,
    border-color 0.35s ease;
  cursor: pointer;
  overflow: hidden;
}

.spatial-card.is-front {
  background: #fff;
}

.spatial-card.is-front.tone-blocked {
  border-color: rgba(252, 211, 77, 0.95);
  box-shadow: 0 28px 60px rgba(245, 158, 11, 0.16);
}

.spatial-card.is-front.tone-running {
  border-color: rgba(125, 211, 252, 0.95);
  box-shadow: 0 28px 60px rgba(2, 132, 199, 0.16);
}

.spatial-card.is-front.tone-completed {
  border-color: rgba(110, 231, 183, 0.95);
  box-shadow: 0 28px 60px rgba(16, 185, 129, 0.14);
}

.spatial-card.is-front.tone-failed {
  border-color: rgba(253, 164, 175, 0.95);
  box-shadow: 0 28px 60px rgba(244, 63, 94, 0.14);
}

.spatial-card.is-front.tone-neutral,
.spatial-card.is-pinned {
  border-color: rgba(125, 211, 252, 0.95);
  box-shadow: 0 28px 60px rgba(2, 132, 199, 0.15);
}

.card-sheen {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    125deg,
    rgba(255, 255, 255, 0.68) 0%,
    rgba(255, 255, 255, 0.14) 34%,
    rgba(255, 255, 255, 0) 60%
  );
  pointer-events: none;
}

.card-inner {
  position: relative;
  z-index: 2;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 11px;
  opacity: var(--card-content-opacity, 1);
  transition: opacity 0.52s ease;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border-radius: var(--radius-full);
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  color: #475569;
  font-size: 11px;
  font-weight: 600;
}

.status-badge.tone-blocked {
  border-color: #fde68a;
  background: #fffbeb;
  color: #b45309;
}

.status-badge.tone-running {
  border-color: #bae6fd;
  background: #f0f9ff;
  color: #0369a1;
}

.status-badge.tone-completed {
  border-color: #a7f3d0;
  background: #ecfdf5;
  color: #047857;
}

.status-badge.tone-failed {
  border-color: #fecdd3;
  background: #fff1f2;
  color: #be123c;
}

.status-dot {
  position: relative;
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: #94a3b8;
}

.tone-blocked .status-dot { background: #f59e0b; }
.tone-running .status-dot { background: #0284c7; }
.tone-completed .status-dot { background: #10b981; }
.tone-failed .status-dot { background: #f43f5e; }

.status-dot.is-blocked::after,
.status-dot.is-live::after {
  content: "";
  position: absolute;
  inset: -3px;
  border-radius: 999px;
  border: 1.5px solid currentColor;
  animation: theater-pulse 1.9s cubic-bezier(0.22, 1, 0.36, 1) infinite;
}

.status-dot.is-blocked { color: #f59e0b; }
.status-dot.is-live { color: #0ea5e9; }

@keyframes theater-pulse {
  0% { transform: scale(0.95); opacity: 0.75; }
  70% { transform: scale(1.8); opacity: 0; }
  100% { transform: scale(1.8); opacity: 0; }
}

.card-time {
  font-family: var(--font-mono);
  font-size: 11px;
  color: #94a3b8;
}

.card-title-block {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.card-title {
  margin: 0;
  font-size: 15px;
  line-height: 1.38;
  font-weight: 600;
  color: var(--color-primary-900);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.meta-chip {
  max-width: 100%;
  padding: 2px 7px;
  border-radius: 6px;
  background: #f1f5f9;
  color: #475569;
  font-size: 11px;
  font-weight: 500;
}

.meta-chip.is-repo {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  font-family: var(--font-mono);
}

.meta-chip.is-req {
  border: 1px solid #e0f2fe;
  background: #f0f9ff;
  color: var(--color-primary-700);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}

.meta-chip.is-req:hover {
  border-color: var(--color-primary-500);
}

.card-summary {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: var(--color-text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-foot {
  padding-top: 10px;
  border-top: 1px solid rgba(226, 232, 240, 0.75);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.creator-info {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.creator-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--color-text-body);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.enter-chat-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: var(--radius-full);
  border: 1px solid #bae6fd;
  background: #f0f9ff;
  color: var(--color-primary-700);
  font-size: 11.5px;
  font-weight: 600;
  flex-shrink: 0;
  transition: all var(--transition-fast);
}

.enter-chat-btn:hover {
  background: var(--color-primary-500);
  border-color: var(--color-primary-500);
  color: #ffffff;
}

.btn-mini-icon {
  width: 12px;
  height: 12px;
}

.side-focus-label {
  font-size: 11px;
  color: #94a3b8;
  flex-shrink: 0;
}

.carousel-nav-pill {
  position: absolute;
  left: 50%;
  bottom: 16px;
  transform: translateX(-50%);
  z-index: 35;
  padding: 4px 8px;
  gap: 6px;
}

.nav-step-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: #64748b;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.nav-step-btn:hover {
  background: #f1f5f9;
  color: var(--color-primary-700);
}

.nav-icon {
  width: 14px;
  height: 14px;
}

.nav-dots {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 2px;
}

.nav-dot {
  width: 6px;
  height: 6px;
  padding: 0;
  border: none;
  border-radius: 999px;
  background: #cbd5e1;
  transition: width 0.25s ease, background 0.2s ease;
}

.nav-dot:hover {
  background: #94a3b8;
}

.nav-dot.is-active {
  width: 20px;
  background: var(--color-primary-600);
}

.hud-hint {
  position: absolute;
  left: 14px;
  bottom: 16px;
  z-index: 20;
  font-size: 11px;
  color: #94a3b8;
  pointer-events: none;
}

@media (max-width: 960px) {
  .hud-hint {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .spatial-world,
  .spatial-card,
  .card-inner,
  .nav-dot {
    transition: none;
  }

  .status-dot.is-blocked::after,
  .status-dot.is-live::after {
    animation: none;
  }
}
</style>
