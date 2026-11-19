import {
  AvatarImageError, MAX_AVATAR_UPLOAD_BYTES, avatarCropSide, validateAvatarAnimation,
  type AnimatedAvatarImage, type AvatarCrop,
} from './avatarCrop'

const SVG_NS = 'http://www.w3.org/2000/svg'
const DECLARATIVE_MOTION = /<(?:[\w.-]+:)?(?:animate(?:Motion|Transform|Color)?|set)(?:\s|\/|>)|(?:animation(?:-[\w-]+)?\s*:|@(?:-webkit-)?keyframes\b)/

function svgRoot(markup: string): Element {
  const root = new DOMParser().parseFromString(markup, 'image/svg+xml').documentElement
  if (root.namespaceURI !== SVG_NS || root.localName !== 'svg') {
    throw new AvatarImageError('invalid_image')
  }
  return root
}

export async function readAnimatedAvatarSvg(source: Blob): Promise<AnimatedAvatarImage | null> {
  if (!DECLARATIVE_MOTION.test(await source.text())) return null
  const previewUrl = URL.createObjectURL(source)
  try {
    const preview = new Image()
    preview.src = previewUrl
    await preview.decode()
    const dimensions = { width: preview.naturalWidth, height: preview.naturalHeight }
    validateAvatarAnimation(dimensions, 1)
    return { source, previewUrl, ...dimensions }
  } catch (error) {
    URL.revokeObjectURL(previewUrl)
    throw error
  }
}

export async function encodeAvatarSvgCrop(image: AnimatedAvatarImage, crop: AvatarCrop): Promise<Blob> {
  const inner = svgRoot(await image.source.text())
  const side = avatarCropSide(image, crop)
  const left = Math.max(0, crop.x - side / 2)
  const top = Math.max(0, crop.y - side / 2)
  const viewport = [image.width, image.height, left, top, side].join(' ')
  const source = new XMLSerializer().serializeToString(inner)
  const body = new Blob([`<svg xmlns="${SVG_NS}" data-avatar-crop="${viewport}">${source}</svg>`], { type: 'image/svg+xml' })
  if (body.size > MAX_AVATAR_UPLOAD_BYTES) throw new AvatarImageError('animation_too_large')
  return body
}

export function avatarSvgView(url: string) {
  const marker = '.svg#crop='
  const index = url.lastIndexOf(marker)
  if (index < 0) return null
  const values = url.slice(index + marker.length).split(',').map(Number)
  if (values.length !== 5 || values.some(value => !Number.isFinite(value))) return null
  const [width, height, left, top, side] = values
  if (width <= 0 || height <= 0 || side <= 0 || left < 0 || top < 0) return null
  return {
    src: url.slice(0, index + 4),
    style: {
      width: `${width / side * 100}%`,
      height: `${height / side * 100}%`,
      left: `${-left / side * 100}%`,
      top: `${-top / side * 100}%`,
    },
  }
}
