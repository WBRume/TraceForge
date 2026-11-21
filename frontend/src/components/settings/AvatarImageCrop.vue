<script setup lang="ts">
import { shallowRef, useId } from 'vue'
import AvatarCropPreview from '@/components/settings/AvatarCropPreview.vue'
import {
  avatarCropSide, centeredAvatarCrop, constrainAvatarCrop, type AvatarCrop,
} from '@/utils/avatarCrop'
import type { AvatarImage } from '@/utils/avatarImage'
import type { AvatarShape } from '@/utils/avatar'

const props = withDefaults(defineProps<{ image: AvatarImage; disabled: boolean; shape?: AvatarShape }>(), { shape: 'circle' })
const crop = defineModel<AvatarCrop>({ required: true })

const stageSize = 384
const stageInset = 32
const cropFraction = (stageSize - 2 * stageInset) / stageSize
const hintId = useId()
const zoomId = useId()
const drag = shallowRef<{ id: number; x: number; y: number } | null>(null)
const arrowOffsets: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0],
  ArrowRight: [1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1],
}

function startDrag(event: PointerEvent) {
  if (props.disabled || event.button !== 0 || drag.value) return
  const stage = event.currentTarget as HTMLElement
  stage.setPointerCapture(event.pointerId)
  drag.value = { id: event.pointerId, x: event.clientX, y: event.clientY }
}

function moveImage(dx: number, dy: number) {
  crop.value = constrainAvatarCrop(props.image, { ...crop.value, x: crop.value.x - dx, y: crop.value.y - dy })
}

function moveDrag(event: PointerEvent) {
  const active = drag.value
  if (!active || active.id !== event.pointerId || props.disabled) return
  const width = (event.currentTarget as HTMLElement).getBoundingClientRect().width
  if (!width) return
  const imageUnitsPerPixel = avatarCropSide(props.image, crop.value) / (width * cropFraction)
  moveImage((event.clientX - active.x) * imageUnitsPerPixel, (event.clientY - active.y) * imageUnitsPerPixel)
  active.x = event.clientX
  active.y = event.clientY
}

function endDrag(event: PointerEvent) {
  if (drag.value?.id === event.pointerId) drag.value = null
}

function moveWithKeyboard(event: KeyboardEvent) {
  const offset = arrowOffsets[event.key]
  if (props.disabled || !offset) return
  event.preventDefault()
  const step = avatarCropSide(props.image, crop.value) * 0.025
  moveImage(offset[0] * step, offset[1] * step)
}

function setZoom(event: Event) {
  const zoom = (event.currentTarget as HTMLInputElement).valueAsNumber
  crop.value = constrainAvatarCrop(props.image, { ...crop.value, zoom })
}
</script>

<template>
  <div
    class="avatar-crop-stage"
    :class="{ dragging: drag }"
    role="group"
    :tabindex="disabled ? -1 : 0"
    :aria-label="$t(shape === 'square' ? 'settings.workspace_avatar.crop_label' : 'settings.appearance.crop_label')"
    :aria-describedby="hintId"
    :aria-disabled="disabled"
    @pointerdown="startDrag"
    @pointermove="moveDrag"
    @pointerup="endDrag"
    @pointercancel="endDrag"
    @lostpointercapture="endDrag"
    @keydown="moveWithKeyboard"
  >
    <AvatarCropPreview class="crop-image" :image="image" :crop="crop" :side="stageSize" :inset="stageInset" />
    <div
      class="crop-outline"
      :class="{ 'is-square': shape === 'square' }"
      :style="{ inset: `${stageInset / stageSize * 100}%` }"
      aria-hidden="true"
    ></div>
  </div>
  <p :id="hintId" class="crop-hint">{{ $t('settings.appearance.crop_hint') }}</p>
  <div class="crop-controls">
    <label :for="zoomId">{{ $t('settings.appearance.zoom') }}</label>
    <input
      :id="zoomId"
      class="zoom-slider"
      type="range"
      min="1"
      max="4"
      step="0.01"
      :value="crop.zoom"
      :aria-valuetext="`${Math.round(crop.zoom * 100)}%`"
      :disabled="disabled"
      @input="setZoom"
    >
    <button class="crop-reset" type="button" :disabled="disabled" @click="crop = centeredAvatarCrop(image)">
      {{ $t('settings.appearance.reset_crop') }}
    </button>
  </div>
</template>

<style scoped>
.avatar-crop-stage {
  position: relative;
  width: min(100%, 17rem);
  aspect-ratio: 1;
  margin: 0 auto;
  overflow: hidden;
  isolation: isolate;
  border-radius: 0.875rem;
  box-shadow: 0 0 0 1px #cbd5e1;
  background: #dbe5ef;
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.avatar-crop-stage:focus-visible {
  outline: 2px solid #0284c7;
  outline-offset: 3px;
}

.avatar-crop-stage.dragging {
  cursor: grabbing;
}

.avatar-crop-stage[aria-disabled="true"] {
  cursor: default;
}

.crop-image {
  display: block;
  width: 100%;
  height: 100%;
}

.crop-outline {
  position: absolute;
  border-radius: 50%;
  box-shadow: 0 0 0 20rem rgba(15, 23, 42, 0.62), inset 0 0 0 2px rgba(255, 255, 255, 0.95);
  pointer-events: none;
}

.crop-outline.is-square {
  border-radius: 0;
}

.crop-hint {
  margin: 0;
  text-align: center;
  font-size: 0.8125rem;
  color: #475569;
}

.crop-controls {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 0.8125rem;
  color: #334155;
}

.zoom-slider {
  flex: 1;
  min-width: 3rem;
  accent-color: #0284c7;
}

.crop-reset {
  flex-shrink: 0;
  border: 0;
  border-radius: 0.375rem;
  padding: 0.375rem 0.5rem;
  background: transparent;
  color: #0369a1;
  font: inherit;
  cursor: pointer;
}

.crop-reset:hover:not(:disabled) {
  background: #e0f2fe;
}

.crop-reset:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
