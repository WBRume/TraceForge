import UPNG from '@adnsistemas/upng/cjs/UPNG.js'
import type { GifReader } from 'omggif'
import {
  AvatarImageError, MAX_AVATAR_ANIMATION_PIXELS, MAX_AVATAR_SIDE, MAX_AVATAR_UPLOAD_BYTES,
  avatarCropSide, drawAvatarCrop,
  type AvatarAnimationRequest, type AvatarAnimationResult, type AvatarDimensions, type AvatarFrame,
} from './avatarCrop'
import { readAvatarGif } from './avatarGif'
import { openAvatarAnimation } from './avatarNativeAnimation'

type VisitFrame = (image: AvatarFrame, delay: number) => void
type AnimationFrames = AvatarDimensions & {
  count: number
  plays: number
  read(visit: VisitFrame): void | Promise<void>
  close?(): void
}

function gifFrames(reader: GifReader): AnimationFrames {
  const repeats = reader.loopCount()
  const count = reader.numFrames()
  return {
    width: reader.width,
    height: reader.height,
    count,
    plays: repeats === 0 ? 0 : Math.min((repeats ?? 0) + 1, 65_535),
    read(visit) {
      const source = new OffscreenCanvas(reader.width, reader.height)
      const context = source.getContext('2d')!
      const composited = new ImageData(reader.width, reader.height)
      for (let index = 0; index < count; index++) {
        const frame = reader.frameInfo(index)
        const previous = frame.disposal === 3 ? composited.data.slice() : null
        reader.decodeAndBlitFrameRGBA(index, composited.data)
        context.putImageData(composited, 0, 0)
        visit(source, frame.delay < 2 ? 100 : frame.delay * 10)
        if (previous) {
          composited.data.set(previous)
        } else if (frame.disposal === 2) {
          for (let row = frame.y; row < frame.y + frame.height; row++) {
            const start = (row * reader.width + frame.x) * 4
            composited.data.fill(0, start, start + frame.width * 4)
          }
        }
      }
    },
  }
}

async function nativeFrames(source: Blob): Promise<AnimationFrames> {
  const { width, height, decoder, track } = await openAvatarAnimation(source.type, await source.arrayBuffer())
  const { frameCount, repetitionCount } = track
  return {
    width,
    height,
    count: frameCount,
    plays: Number.isFinite(repetitionCount) ? Math.min(Math.floor(repetitionCount) + 1, 65_535) : 0,
    async read(visit) {
      for (let index = 0; index < frameCount; index++) {
        const { image } = await decoder.decode({ frameIndex: index })
        try {
          const delay = Math.max(1, Math.round((image.duration ?? 100_000) / 1000))
          if (delay > 65_535) throw new AvatarImageError('animation_too_complex')
          visit(image, delay)
        } finally {
          image.close()
        }
      }
    },
    close: () => decoder.close(),
  }
}

async function encodeFrames(animation: AnimationFrames, crop: AvatarAnimationRequest['crop']): Promise<Blob> {
  const maximumSide = Math.min(MAX_AVATAR_SIDE, Math.floor(Math.sqrt(MAX_AVATAR_ANIMATION_PIXELS / animation.count)))
  let side = Math.max(1, Math.min(maximumSide, Math.floor(avatarCropSide(animation, crop))))
  const minimumSide = Math.min(side, 96)
  while (true) {
    const target = new OffscreenCanvas(side, side)
    const context = target.getContext('2d', { willReadFrequently: true })!
    const frames: ArrayBuffer[] = []
    const delays: number[] = []
    await animation.read((image, delay) => {
      drawAvatarCrop(target, image, crop)
      frames.push(context.getImageData(0, 0, side, side).data.buffer)
      delays.push(delay)
    })
    const bytes = UPNG.encode(frames, side, side, 0, delays, { loop: animation.plays })
    if (bytes.byteLength <= MAX_AVATAR_UPLOAD_BYTES) {
      return new Blob([bytes], { type: frames.length > 1 ? 'image/apng' : 'image/png' })
    }
    if (side === minimumSide) throw new AvatarImageError('animation_too_large')
    const scale = Math.min(0.75, Math.sqrt(MAX_AVATAR_UPLOAD_BYTES / bytes.byteLength) * 0.95)
    side = Math.max(minimumSide, Math.floor(side * scale))
  }
}

async function encodeAnimationCrop({ source, crop }: AvatarAnimationRequest): Promise<Blob> {
  if (typeof OffscreenCanvas === 'undefined') throw new AvatarImageError('animation_unavailable')
  const animation = source.type === 'image/gif' ? gifFrames(await readAvatarGif(source)) : await nativeFrames(source)
  try {
    return await encodeFrames(animation, crop)
  } finally {
    animation.close?.()
  }
}

self.addEventListener('message', async (event: MessageEvent<AvatarAnimationRequest>) => {
  let result: AvatarAnimationResult
  try {
    result = { image: await encodeAnimationCrop(event.data) }
  } catch (error) {
    result = { error: error instanceof AvatarImageError ? error.reason : 'invalid_image' }
  }
  self.postMessage(result)
})
