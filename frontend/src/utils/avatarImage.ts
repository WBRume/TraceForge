import {
  AvatarImageError, MAX_AVATAR_SIDE, MAX_SOURCE_PIXELS, avatarCropSide, drawAvatarCrop, type AvatarCrop,
  type AnimatedAvatarImage, type AvatarAnimationRequest, type AvatarAnimationResult,
} from './avatarCrop'
import { encodeAvatarSvgCrop, readAnimatedAvatarSvg } from './avatarVector'

const imageMimeTypes: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  apng: 'image/apng',
  webp: 'image/webp',
  gif: 'image/gif',
  bmp: 'image/bmp',
  avif: 'image/avif',
  avifs: 'image/avif',
  svg: 'image/svg+xml',
}
const supportedTypes = new Set(Object.values(imageMimeTypes))
export const AVATAR_SOURCE_LIMIT_MB = 20
export const AVATAR_FILE_ACCEPT = [
  ...Object.keys(imageMimeTypes).map(extension => `.${extension}`),
  ...supportedTypes,
].join(',')

export type AvatarImage = ImageBitmap | AnimatedAvatarImage

export function isAnimatedAvatar(image: AvatarImage): image is AnimatedAvatarImage {
  return 'previewUrl' in image
}
export function releaseAvatarImage(image: AvatarImage) {
  if (isAnimatedAvatar(image)) URL.revokeObjectURL(image.previewUrl)
  else image.close()
}

function canvasContext(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas is unavailable')
  return context
}

async function rasterizeSvg(file: Blob): Promise<ImageBitmap> {
  const url = URL.createObjectURL(file)
  try {
    const image = new Image()
    image.src = url
    await image.decode()
    const scale = 2048 / Math.max(image.naturalWidth, image.naturalHeight)
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
    // An image element keeps SVGs in image mode, including ones with only a viewBox.
    canvasContext(canvas).drawImage(image, 0, 0, canvas.width, canvas.height)
    return await createImageBitmap(canvas)
  } finally {
    URL.revokeObjectURL(url)
  }
}

export async function decodeAvatarImage(file: File): Promise<AvatarImage> {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  const mimeType = supportedTypes.has(file.type) ? file.type : imageMimeTypes[extension]
  if (!supportedTypes.has(mimeType)) throw new AvatarImageError('invalid_file')
  if (file.size > AVATAR_SOURCE_LIMIT_MB * 1024 * 1024) {
    throw new AvatarImageError('file_too_large')
  }

  const blob = file.slice(0, file.size, mimeType === 'image/apng' ? 'image/png' : mimeType)
  const signature = await blob.slice(0, 6).text()
  if (signature === 'GIF87a' || signature === 'GIF89a') {
    const source = blob.slice(0, blob.size, 'image/gif')
    const { readAvatarGif } = await import('./avatarGif')
    const gif = await readAvatarGif(source)
    if (gif.numFrames() > 1) {
      return { width: gif.width, height: gif.height, source, previewUrl: URL.createObjectURL(source) }
    }
  }
  if (blob.type === 'image/svg+xml') {
    const animation = await readAnimatedAvatarSvg(blob)
    if (animation) return animation
  } else if (blob.type === 'image/png' || blob.type === 'image/webp' || blob.type === 'image/avif') {
    const { hasNativeAvatarAnimation, openAvatarAnimation } = await import('./avatarNativeAnimation')
    const bytes = await blob.arrayBuffer()
    if (hasNativeAvatarAnimation(blob.type, bytes)) {
      const { width, height, decoder } = await openAvatarAnimation(blob.type, bytes)
      decoder.close()
      return { width, height, source: blob, previewUrl: URL.createObjectURL(blob) }
    }
  }
  const image = mimeType === 'image/svg+xml'
    ? await rasterizeSvg(blob)
    : await createImageBitmap(blob, { imageOrientation: 'from-image' })
  if (image.width * image.height > MAX_SOURCE_PIXELS) {
    image.close()
    throw new AvatarImageError('image_too_large')
  }
  return image
}

async function encodeAnimatedAvatarCrop(source: Blob, crop: AvatarCrop, signal?: AbortSignal): Promise<Blob> {
  const { default: AvatarAnimationWorker } = await import('./avatarAnimation.worker?worker&inline')
  return new Promise((resolve, reject) => {
    signal?.throwIfAborted()
    const worker = new AvatarAnimationWorker()
    const cleanup = () => {
      signal?.removeEventListener('abort', abort)
      worker.terminate()
    }
    const abort = () => {
      cleanup()
      reject(signal?.reason)
    }
    worker.onmessage = (event: MessageEvent<AvatarAnimationResult>) => {
      cleanup()
      if ('image' in event.data) resolve(event.data.image)
      else reject(new AvatarImageError(event.data.error))
    }
    worker.onerror = () => {
      cleanup()
      reject(new AvatarImageError('animation_unavailable'))
    }
    signal?.addEventListener('abort', abort, { once: true })
    worker.postMessage({ source, crop } satisfies AvatarAnimationRequest)
  })
}

export function encodeAvatarCrop(image: AvatarImage, crop: AvatarCrop, signal?: AbortSignal): Promise<Blob> {
  if (isAnimatedAvatar(image)) {
    if (image.source.type === 'image/svg+xml') {
      return encodeAvatarSvgCrop(image, crop)
    }
    return encodeAnimatedAvatarCrop(image.source, crop, signal)
  }
  const canvas = document.createElement('canvas')
  const side = Math.max(1, Math.min(MAX_AVATAR_SIDE, Math.floor(avatarCropSide(image, crop))))
  canvas.width = side
  canvas.height = side
  drawAvatarCrop(canvas, image, crop)
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) resolve(blob)
      else reject(new Error('Avatar encoding failed'))
    }, 'image/png')
  })
}
