import { GifReader } from 'omggif'
import { AvatarImageError, validateAvatarAnimation } from './avatarCrop'

export async function readAvatarGif(source: Blob) {
  const reader = new GifReader(new Uint8Array(await source.arrayBuffer()))
  const count = reader.numFrames()
  validateAvatarAnimation(reader, count)
  for (let i = 0; i < count; i++) {
    const frame = reader.frameInfo(i)
    if (!frame.width || !frame.height || frame.x + frame.width > reader.width || frame.y + frame.height > reader.height) {
      throw new AvatarImageError('invalid_image')
    }
    // The APNG writer stores the delay as a 16-bit millisecond value.
    if (count > 1 && frame.delay * 10 > 65_535) {
      throw new AvatarImageError('animation_too_complex')
    }
  }
  return reader
}
