const imageMimeTypes: Record<string, string> = {
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  png: 'image/png',
  webp: 'image/webp',
  gif: 'image/gif',
  bmp: 'image/bmp',
  avif: 'image/avif',
  svg: 'image/svg+xml',
}
const supportedTypes = new Set(Object.values(imageMimeTypes))
const MAX_SOURCE_PIXELS = 32_000_000
const MAX_AVATAR_SIDE = 512
export const AVATAR_SOURCE_LIMIT_MB = 20
export const AVATAR_FILE_ACCEPT = [
  ...Object.keys(imageMimeTypes).map(extension => `.${extension}`),
  ...supportedTypes,
].join(',')

export class AvatarImageError extends Error {
  readonly reason: 'invalid_file' | 'file_too_large' | 'image_too_large'

  constructor(reason: AvatarImageError['reason']) {
    super(reason)
    this.reason = reason
  }
}

export type AvatarCrop = {
  x: number
  y: number
  zoom: number
}

export function centeredAvatarCrop(image: ImageBitmap): AvatarCrop {
  return { x: image.width / 2, y: image.height / 2, zoom: 1 }
}

export function avatarCropSide(image: ImageBitmap, crop: AvatarCrop): number {
  return Math.min(image.width, image.height) / crop.zoom
}

export function constrainAvatarCrop(image: ImageBitmap, crop: AvatarCrop): AvatarCrop {
  const halfSide = avatarCropSide(image, crop) / 2
  return {
    x: Math.max(halfSide, Math.min(image.width - halfSide, crop.x)),
    y: Math.max(halfSide, Math.min(image.height - halfSide, crop.y)),
    zoom: crop.zoom,
  }
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

export async function decodeAvatarImage(file: File): Promise<ImageBitmap> {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  const mimeType = supportedTypes.has(file.type) ? file.type : imageMimeTypes[extension]
  if (!supportedTypes.has(mimeType)) throw new AvatarImageError('invalid_file')
  if (file.size > AVATAR_SOURCE_LIMIT_MB * 1024 * 1024) {
    throw new AvatarImageError('file_too_large')
  }

  const blob = file.slice(0, file.size, mimeType)
  const image = mimeType === 'image/svg+xml'
    ? await rasterizeSvg(blob)
    : await createImageBitmap(blob, { imageOrientation: 'from-image' })
  if (image.width * image.height > MAX_SOURCE_PIXELS) {
    image.close()
    throw new AvatarImageError('image_too_large')
  }
  return image
}

// The editor, preview and upload use the same crop in source-image coordinates.
export function drawAvatarCrop(canvas: HTMLCanvasElement, image: ImageBitmap, crop: AvatarCrop, inset = 0) {
  const context = canvasContext(canvas)
  const scale = (canvas.width - inset * 2) / avatarCropSide(image, crop)
  context.clearRect(0, 0, canvas.width, canvas.height)
  context.imageSmoothingQuality = 'high'
  context.drawImage(
    image,
    canvas.width / 2 - crop.x * scale,
    canvas.height / 2 - crop.y * scale,
    image.width * scale,
    image.height * scale,
  )
}

export function encodeAvatarCrop(image: ImageBitmap, crop: AvatarCrop): Promise<Blob> {
  const canvas = document.createElement('canvas')
  const side = Math.max(1, Math.min(MAX_AVATAR_SIDE, Math.floor(avatarCropSide(image, crop))))
  canvas.width = side
  canvas.height = side
  drawAvatarCrop(canvas, image, crop)
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) resolve(blob)
      else reject(new Error('Avatar encoding failed'))
    }, 'image/webp', 0.88)
  })
}
