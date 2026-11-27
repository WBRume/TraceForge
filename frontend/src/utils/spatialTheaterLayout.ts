export interface SpatialCardLayout {
  x: number
  y: number
  z: number
  rotX: number
  rotY: number
  rotZ: number
  scale: number
  opacity: number
  zIndex: number
  isFront: boolean
}

export interface SpatialLayoutInput {
  ids: string[]
  activeIndex: number
  stageWidth: number
  stageHeight: number
}

const STAGE_PERSPECTIVE = 1050
const FRONT_CARD_Z_INDEX = 40
const CARD_BASE_W = 352
const CARD_BASE_H = 192

function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v
}

/** FNV-1a 32-bit string hash for stable task-seeded placement. */
export function hashSpatialSeed(text: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return h >>> 0
}

/** Deterministic [0, 1) float from integer seed + salt. */
function unitRandom(seed: number, salt: number): number {
  let x = (seed ^ Math.imul(salt + 1, 0x9e3779b1)) >>> 0
  x = Math.imul(x ^ (x >>> 16), 0x85ebca6b) >>> 0
  x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35) >>> 0
  x = (x ^ (x >>> 16)) >>> 0
  return x / 0x100000000
}

function signedRandom(seed: number, salt: number): number {
  return unitRandom(seed, salt) * 2 - 1
}

function perspectiveScale(z: number): number {
  return STAGE_PERSPECTIVE / Math.max(240, STAGE_PERSPECTIVE - z)
}

/**
 * Compute an explosive 3D radial scatter layout around the focal front card.
 * Solves positions in real screen pixels (compensating for CSS perspective
 * foreshortening on negative-Z cards) so scattered cards burst outward across
 * the full stage instead of bunching behind the center hero card.
 */
export function computeSpatialTheaterLayouts({
  ids,
  activeIndex,
  stageWidth,
  stageHeight,
}: SpatialLayoutInput): SpatialCardLayout[] {
  const n = ids.length
  if (!n) return []

  const safeActive = ((activeIndex % n) + n) % n
  const frontSeed = hashSpatialSeed(ids[safeActive])

  const heroZ = 0
  const heroScreenW = CARD_BASE_W
  const heroScreenH = CARD_BASE_H

  const heroSx = Math.round(signedRandom(frontSeed, 1) * Math.min(18, stageWidth * 0.02))
  const heroSy = Math.round(-8 + signedRandom(frontSeed, 2) * 8)

  const layouts: SpatialCardLayout[] = new Array(n)
  layouts[safeActive] = {
    x: heroSx,
    y: heroSy,
    z: heroZ,
    rotX: 0,
    rotY: 0,
    rotZ: 0,
    scale: 1,
    opacity: 1,
    zIndex: FRONT_CARD_Z_INDEX,
    isFront: true,
  }

  if (n === 1) return layouts

  const bgEntries: Array<{ idx: number; offset: number; abs: number; seed: number }> = []
  for (let i = 0; i < n; i++) {
    if (i === safeActive) continue
    let offset = i - safeActive
    if (n > 2) {
      if (offset > n / 2) offset -= n
      if (offset < -n / 2) offset += n
    }
    const seed = hashSpatialSeed(`${ids[safeActive]}::${ids[i]}`)
    bgEntries.push({ idx: i, offset, abs: Math.abs(offset), seed })
  }
  bgEntries.sort((a, b) => a.abs - b.abs || b.offset - a.offset)

  // Screen-space stage bounds for scattered cards (leaving margin for HUD & dot controls)
  const avgBgScreenScale = 0.78
  const bgHalfW = (CARD_BASE_W * avgBgScreenScale) / 2
  const bgHalfH = (CARD_BASE_H * avgBgScreenScale) / 2
  const boundX = Math.max(140, stageWidth / 2 - bgHalfW - 18)
  const boundY = Math.max(82, stageHeight / 2 - bgHalfH - 42)

  // Keep-out ellipse around center hero card so background cards burst cleanly outward
  const keepOutX = Math.min(heroScreenW * 0.72, boundX * 0.84)
  const keepOutY = Math.min(heroScreenH * 0.76, boundY * 0.88)

  // Distribute burst rays across the 360° circle with organic angular jitter
  const baseAngle = unitRandom(frontSeed, 7) * Math.PI * 2
  const sectorStep = (Math.PI * 2) / bgEntries.length

  const bgNodes = bgEntries.map((entry, k) => {
    const jitter = signedRandom(entry.seed, 10) * Math.min(0.42, sectorStep * 0.34)
    const angle = baseAngle + k * sectorStep + jitter

    // Push toward the outer 72%..100% burst ring of the viewport
    const burstFactor = 0.74 + unitRandom(entry.seed, 11) * 0.28
    const dirX = Math.cos(angle)
    const dirY = Math.sin(angle)

    let sx = heroSx + dirX * boundX * burstFactor
    let sy = heroSy + dirY * boundY * burstFactor

    // Enforce radial escape past the center keep-out ellipse
    const normDist = Math.hypot((sx - heroSx) / Math.max(1, keepOutX), (sy - heroSy) / Math.max(1, keepOutY))
    if (normDist < 1.04) {
      const push = 1.06 / Math.max(0.15, normDist)
      sx = heroSx + (sx - heroSx) * push
      sy = heroSy + (sy - heroSy) * push
    }

    const tier = entry.abs
    const z = -(52 + (tier - 1) * 44 + unitRandom(entry.seed, 12) * 34)
    const scale = clamp(0.89 - (tier - 1) * 0.04 + signedRandom(entry.seed, 13) * 0.025, 0.78, 0.92)
    const opacity = clamp(0.95 - (tier - 1) * 0.1 + signedRandom(entry.seed, 14) * 0.04, 0.68, 0.97)

    return {
      ...entry,
      sx: clamp(sx, -boundX, boundX),
      sy: clamp(sy, -boundY, boundY),
      z,
      scale,
      opacity,
    }
  })

  // Screen-space pairwise relaxation so exploded cards stay spread apart across corners/edges
  const minSepX = Math.min(230, boundX * 0.76)
  const minSepY = Math.min(126, boundY * 0.92)

  for (let iter = 0; iter < 10; iter++) {
    for (let i = 0; i < bgNodes.length; i++) {
      const a = bgNodes[i]

      // Keep outside hero center zone (bias diagonally outward if trapped directly above/below)
      const rx = (a.sx - heroSx) / Math.max(1, keepOutX)
      const ry = (a.sy - heroSy) / Math.max(1, keepOutY)
      const r = Math.hypot(rx, ry)
      if (r < 1.08) {
        const nx = Math.abs(rx) < 0.35
          ? (i % 2 === 0 ? 1 : -1) * 0.72
          : rx / Math.max(0.05, r)
        const ny = r > 0.05 ? ry / r : (i % 3 === 0 ? 1 : -1)
        a.sx += nx * 32
        a.sy += ny * 22
      }

      // Repel overlapping background cards
      for (let j = i + 1; j < bgNodes.length; j++) {
        const b = bgNodes[j]
        const dx = b.sx - a.sx
        const dy = b.sy - a.sy
        if (Math.abs(dx) < minSepX && Math.abs(dy) < minSepY) {
          const sx = dx === 0 ? (j % 2 === 0 ? 1 : -1) : Math.sign(dx)
          const sy = dy === 0 ? (j % 2 === 0 ? -1 : 1) : Math.sign(dy)
          const pushX = (minSepX - Math.abs(dx)) * 0.34 * sx
          const pushY = (minSepY - Math.abs(dy)) * 0.38 * sy
          a.sx -= pushX
          b.sx += pushX
          a.sy -= pushY
          b.sy += pushY
        }
      }

      a.sx = clamp(a.sx, -boundX, boundX)
      a.sy = clamp(a.sy, -boundY, boundY)
    }
  }

  bgNodes.sort((a, b) => a.z - b.z || a.idx - b.idx)
  for (const [depthIndex, node] of bgNodes.entries()) {
    const pScale = perspectiveScale(node.z)
    // Compensate 3D coordinates for perspective shrink so screen position matches (sx, sy)
    const x3d = node.sx / pScale
    const y3d = node.sy / pScale

    // Radial blast tilt pointing outward from the center explosion (kept gentle so text stays sharp)
    const rotY = Number(clamp(-(node.sx / Math.max(1, boundX)) * 12 + signedRandom(node.seed, 15) * 4, -15, 15).toFixed(2))
    const rotX = Number(clamp((node.sy / Math.max(1, boundY)) * 5 + signedRandom(node.seed, 16) * 2.5, -8, 8).toFixed(2))
    const rotZ = Number(clamp((node.sx * node.sy) / Math.max(1, boundX * boundY) * 2.8 + signedRandom(node.seed, 17) * 2.5, -4, 4).toFixed(2))

    layouts[node.idx] = {
      x: Math.round(x3d),
      y: Math.round(y3d),
      z: Math.round(node.z),
      rotX,
      rotY,
      rotZ,
      scale: Number(node.scale.toFixed(3)),
      opacity: Number(node.opacity.toFixed(3)),
      zIndex: FRONT_CARD_Z_INDEX - bgNodes.length + depthIndex,
      isFront: false,
    }
  }

  return layouts
}
