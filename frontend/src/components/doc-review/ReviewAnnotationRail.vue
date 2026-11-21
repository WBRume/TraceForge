<script setup lang="ts">
import { computed, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import UserAvatar from '@/components/user/UserAvatar.vue'
import type { AssetThread } from '@/composables/asset-discussion/types'
import { reviewerColor } from '@/utils/skillReview'
import { groupByReviewAuthor, type ReviewAnnotationGroup, type ReviewAnnotationTarget } from './reviewAnnotationRanges'

const props = defineProps<{
  groups: ReviewAnnotationGroup[]
  threads?: AssetThread[]
  content?: HTMLElement
  frame?: HTMLIFrameElement
  selectedThreadId: string
}>()
const emit = defineEmits<{ 'open-threads': [target: ReviewAnnotationTarget] }>()
const { t } = useI18n()
const rail = useTemplateRef<HTMLElement>('rail')
const placedRows = shallowRef<Array<{ center: number; height: number; groups: ReviewAnnotationGroup[] }>>([])
const threadsById = computed(() => new Map(props.threads?.map(thread => [thread.id, thread])))

function firstVisibleRect(group: ReviewAnnotationGroup, left: number, right: number, top: number, bottom: number) {
  for (const { ranges } of group.entries) {
    for (const range of ranges) {
      for (const rect of range.getClientRects()) {
        if (rect.width > 0 && rect.height > 0
          && rect.right > left && rect.left < right && rect.bottom > top && rect.top < bottom) return rect
      }
    }
  }
}

watch(() => [rail.value, props.content, props.frame, props.groups] as const, ([element, content, frame, groups], _, cleanup) => {
  if (!element || !content || !groups.length) {
    placedRows.value = []
    return
  }
  const scrollShell = element.closest('.canvas-shell')
  const events = new AbortController()
  let pending = 0
  const schedule = () => {
    if (pending) return
    pending = requestAnimationFrame(() => {
      pending = 0
      const railTop = element.getBoundingClientRect().top
      const viewport = (scrollShell || content).getBoundingClientRect()
      const frameTop = frame?.getBoundingClientRect().top ?? 0
      const frameView = frame?.contentDocument?.documentElement
      const anchors = groups.flatMap(group => {
        const rect = frameView
          ? firstVisibleRect(group, 0, frameView.clientWidth, 0, frameView.clientHeight)
          : firstVisibleRect(group, viewport.left, viewport.right, viewport.top, viewport.bottom)
        return rect ? [{ group, height: rect.height, center: rect.top + rect.height / 2 + frameTop - railTop }] : []
      }).sort((a, b) => a.center - b.center)
      const rows: typeof placedRows.value = []
      for (const { group, center, height } of anchors) {
        const previous = rows.at(-1)
        // Independent marks on one rendered line share its avatar stack.
        if (previous && center - previous.center < Math.min(height, previous.height) / 2) previous.groups.push(group)
        else rows.push({ center, height, groups: [group] })
      }
      placedRows.value = rows
    })
  }
  const resize = new ResizeObserver(schedule)
  resize.observe(element)
  resize.observe(content)
  if (frame) resize.observe(frame)
  scrollShell?.addEventListener('scroll', schedule, { capture: true, passive: true, signal: events.signal })
  if (frame) content.ownerDocument.addEventListener('scroll', schedule, { capture: true, passive: true, signal: events.signal })
  content.addEventListener('load', schedule, { capture: true, signal: events.signal })
  content.ownerDocument.fonts?.addEventListener('loadingdone', schedule, { signal: events.signal })
  schedule()
  cleanup(() => {
    events.abort()
    resize.disconnect()
    cancelAnimationFrame(pending)
  })
}, { flush: 'post' })

const rows = computed(() => placedRows.value.map(({ center, groups }) => {
  const threadIds = groups.flatMap(group => group.threadIds)
  const reviewers = groupByReviewAuthor(groups.flatMap(group => group.entries.map(entry => entry.marker)))
    .slice(0, 3).map(([marker]) => {
      const thread = threadsById.value.get(marker!.thread_id)
      return {
        id: marker!.creator_id,
        name: thread?.creator_display_name || t('doc_review.unknown_initiator'),
        svg: thread?.creator_avatar_svg,
        url: thread?.creator_avatar_url,
      }
    })
  const title = groups.map(group => {
    const quote = group.entries[0]?.marker.selected_text
    const count = t('doc_review.thread_count', { count: group.threadIds.length })
    return quote ? `${quote} · ${count}` : count
  }).join('\n')
  return { threadIds, reviewers, title, top: Math.max(0, center - 10), multipleAnchors: groups.length > 1 }
}))

function openRow(row: typeof rows.value[number], event: MouseEvent) {
  const trigger = event.currentTarget as HTMLElement
  const bounds = trigger.getBoundingClientRect()
  emit('open-threads', {
    threadIds: row.threadIds, multipleAnchors: row.multipleAnchors,
    left: bounds.right + 8, top: bounds.top, trigger, frame: props.frame,
  })
}
</script>

<template>
  <div v-if="groups.length" ref="rail" class="review-avatar-rail">
    <div
      v-for="row in rows"
      :key="row.threadIds[0]"
      class="line-avatar-row"
      :style="{ top: `${row.top}px` }"
    >
      <button
        type="button"
        class="line-avatar-stack-btn"
        :class="{ 'is-selected': row.threadIds.includes(selectedThreadId) }"
        :title="row.title"
        :aria-label="row.title"
        aria-haspopup="dialog"
        @click.stop="openRow(row, $event)"
      >
        <span class="line-avatar-stack-group" aria-hidden="true">
          <span
            v-for="(reviewer, index) in row.reviewers"
            :key="reviewer.id"
            class="line-avatar-stack-item"
            :style="{ zIndex: row.reviewers.length - index }"
          >
            <UserAvatar
              :display-name="reviewer.name"
              :avatar-svg="reviewer.svg"
              :avatar-url="reviewer.url"
              :accent-color="reviewerColor(reviewer.id)"
              size="xs"
            />
          </span>
        </span>
        <span class="line-avatar-more" aria-hidden="true">{{ row.threadIds.length }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped src="@/styles/review-annotations.css"></style>
<style scoped>
.review-avatar-rail {
  position: relative;
  flex: 0 0 68px;
  border-inline-end: 1px solid #e2e8f0;
  background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
}
.line-avatar-row { inset-inline-start: 50%; transform: translateX(-50%); }
.line-avatar-stack-item + .line-avatar-stack-item { margin-inline-start: -6px; }
.line-avatar-stack-btn:is(:hover, .is-selected) .line-avatar-more { background: #bae6fd; }
.line-avatar-stack-btn:focus-visible { outline: 2px solid #0ea5e9; outline-offset: 2px; }
</style>
