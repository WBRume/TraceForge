export const MAX_AVATAR_SIDE = 512
export const MAX_SOURCE_PIXELS = 32_000_000
export const MAX_AVATAR_ANIMATION_FRAMES = 120
export const MAX_AVATAR_ANIMATION_PIXELS = 8_388_608
export const MAX_AVATAR_UPLOAD_BYTES = 1100 * 1024

export type AvatarDimensions = { width: number; height: number }
export type AvatarCrop = { x: number; y: number; zoom: number }
export type AnimatedAvatarImage = AvatarDimensions & { source: Blob; previewUrl: string }
export type AvatarAnimationRequest = { source: Blob; crop: AvatarCrop }
export type AvatarAnimationResult = { image: Blob } | { error: AvatarImageErrorReason }
export type AvatarFrame = ImageBitmap | OffscreenCanvas | VideoFrame
export type AvatarImageErrorReason =
  | 'invalid_file'
  | 'invalid_image'
  | 'file_too_large'
  | 'image_too_large'
  | 'animation_too_complex'
  | 'animation_too_large'
  | 'animation_unavailable'

export class AvatarImageError extends Error {
  readonly reason: AvatarImageErrorReason

  constructor(reason: AvatarImageErrorReason) {
    super(reason)
    this.reason = reason
  }
}

export function validateAvatarAnimation({ width, height }: AvatarDimensions, frames: number) {
  if (!width || !height || !frames) throw new AvatarImageError('invalid_image')
  const area = width * height
  if (area > MAX_SOURCE_PIXELS) throw new AvatarImageError('image_too_large')
  if (frames > 1 && (
    frames > MAX_AVATAR_ANIMATION_FRAMES ||
    area > 4_194_304 ||
    area * frames > MAX_SOURCE_PIXELS
  )) {
    throw new AvatarImageError('animation_too_complex')
  }
}

export function centeredAvatarCrop(image: AvatarDimensions): AvatarCrop {
  return { x: image.width / 2, y: image.height / 2, zoom: 1 }
}

export function avatarCropSide(image: AvatarDimensions, crop: AvatarCrop): number {
  return Math.min(image.width, image.height) / crop.zoom
}

export function constrainAvatarCrop(image: AvatarDimensions, crop: AvatarCrop): AvatarCrop {
  const halfSide = avatarCropSide(image, crop) / 2
  return {
    x: Math.max(halfSide, Math.min(image.width - halfSide, crop.x)),
    y: Math.max(halfSide, Math.min(image.height - halfSide, crop.y)),
    zoom: crop.zoom,
  }
}

export function avatarCropPlacement(image: AvatarDimensions, crop: AvatarCrop, side: number, inset = 0) {
  const scale = (side - inset * 2) / avatarCropSide(image, crop)
  return {
    x: side / 2 - crop.x * scale,
    y: side / 2 - crop.y * scale,
    width: image.width * scale,
    height: image.height * scale,
  }
}

export function drawAvatarCrop(
  canvas: HTMLCanvasElement | OffscreenCanvas,
  image: AvatarFrame,
  crop: AvatarCrop,
  inset = 0,
) {
  const context = canvas.getContext('2d')
  if (!context || !('drawImage' in context)) throw new Error('Canvas is unavailable')
  const dimensions = 'displayWidth' in image ? { width: image.displayWidth, height: image.displayHeight } : image
  const { x, y, width, height } = avatarCropPlacement(dimensions, crop, canvas.width, inset)
  context.clearRect(0, 0, canvas.width, canvas.height)
  context.imageSmoothingQuality = 'high'
  context.drawImage(image, x, y, width, height)
}
