import { AvatarImageError, MAX_AVATAR_ANIMATION_FRAMES, validateAvatarAnimation } from './avatarCrop'

function textAt(bytes: DataView, offset: number): string {
  return String.fromCharCode(
    bytes.getUint8(offset), bytes.getUint8(offset + 1), bytes.getUint8(offset + 2), bytes.getUint8(offset + 3),
  )
}

function hasPngAnimation(bytes: DataView): boolean {
  if (bytes.byteLength < 8 || bytes.getUint32(0) !== 0x89504e47 || bytes.getUint32(4) !== 0x0d0a1a0a) return false
  for (let offset = 8; offset + 12 <= bytes.byteLength;) {
    const chunk = textAt(bytes, offset + 4)
    if (chunk === 'acTL') return true
    if (chunk === 'IDAT' || chunk === 'IEND') break
    offset += bytes.getUint32(offset) + 12
  }
  return false
}

function hasAvifSequence(bytes: DataView): boolean {
  for (let offset = 0; offset + 8 <= bytes.byteLength;) {
    const box = textAt(bytes, offset + 4)
    let size = bytes.getUint32(offset)
    let header = 8
    if (size === 1) {
      if (offset + 16 > bytes.byteLength) return false
      size = Number(bytes.getBigUint64(offset + 8))
      header = 16
    } else if (size === 0) {
      size = bytes.byteLength - offset
    }
    if (size < header || offset + size > bytes.byteLength) return false
    if (box === 'ftyp' && size >= header + 8) {
      const content = offset + header
      if (textAt(bytes, content) === 'avis') return true
      for (let brand = content + 8; brand + 4 <= offset + size; brand += 4) {
        if (textAt(bytes, brand) === 'avis') return true
      }
      return false
    }
    offset += size
  }
  return false
}

export function hasNativeAvatarAnimation(type: string, data: ArrayBuffer): boolean {
  const bytes = new DataView(data)
  if (type === 'image/png') return hasPngAnimation(bytes)
  if (type === 'image/avif') return hasAvifSequence(bytes)
  return type === 'image/webp' && bytes.byteLength >= 30 &&
    textAt(bytes, 0) === 'RIFF' && textAt(bytes, 8) === 'WEBP' && textAt(bytes, 12) === 'VP8X' &&
    (bytes.getUint8(20) & 2) !== 0
}

export async function openAvatarAnimation(type: string, data: ArrayBuffer) {
  if (typeof ImageDecoder === 'undefined' || !await ImageDecoder.isTypeSupported(type)) {
    throw new AvatarImageError('animation_unavailable')
  }
  const decoder = new ImageDecoder({ type, data, preferAnimation: true })
  try {
    await decoder.tracks.ready
    await decoder.completed
    const track = decoder.tracks.selectedTrack
    if (!track?.animated || !track.frameCount) throw new AvatarImageError('invalid_image')
    if (track.frameCount > MAX_AVATAR_ANIMATION_FRAMES) throw new AvatarImageError('animation_too_complex')
    const { image } = await decoder.decode({ frameIndex: 0 })
    try {
      const dimensions = { width: image.displayWidth, height: image.displayHeight }
      validateAvatarAnimation(dimensions, track.frameCount)
      return { decoder, track, ...dimensions }
    } finally {
      image.close()
    }
  } catch (error) {
    decoder.close()
    throw error
  }
}
