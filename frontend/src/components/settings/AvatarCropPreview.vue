<script setup lang="ts">
import { computed, useTemplateRef, watchPostEffect } from 'vue'
import { avatarCropPlacement, drawAvatarCrop, type AvatarCrop } from '@/utils/avatarCrop'
import { isAnimatedAvatar, type AvatarImage } from '@/utils/avatarImage'

const props = withDefaults(defineProps<{
  image: AvatarImage
  crop: AvatarCrop
  side: number
  inset?: number
}>(), { inset: 0 })
const canvas = useTemplateRef<HTMLCanvasElement>('canvas')
const animation = computed(() => isAnimatedAvatar(props.image) ? props.image : null)
const position = computed(() => {
  const { x, y, width, height } = avatarCropPlacement(props.image, props.crop, 100, props.inset / props.side * 100)
  return { left: `${x}%`, top: `${y}%`, width: `${width}%`, height: `${height}%` }
})

watchPostEffect(() => {
  if (canvas.value && !isAnimatedAvatar(props.image)) {
    drawAvatarCrop(canvas.value, props.image, props.crop, props.inset)
  }
})
</script>

<template>
  <div class="avatar-crop-preview" aria-hidden="true">
    <img
      v-if="animation"
      :src="animation.previewUrl"
      :style="position"
      class="animated-preview"
      alt=""
      draggable="false"
    >
    <canvas v-else ref="canvas" class="static-preview" :width="side" :height="side" />
  </div>
</template>

<style scoped>
.avatar-crop-preview {
  position: relative;
  overflow: hidden;
  pointer-events: none;
}

.animated-preview {
  position: absolute;
  max-width: none;
  max-height: none;
}

.static-preview {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
