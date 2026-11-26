import type { DiagramDocument, DiagramFormat } from './diagramModel'

const svgNamespace = 'http://www.w3.org/2000/svg'
const PNG_LIMIT = 8192
const PNG_PIXELS = 24_000_000

export function drawingSvg(art: SVGGElement, bounds: { left: number; top: number; width: number; height: number }) {
  const svg = document.createElementNS(svgNamespace, 'svg')
  const { left, top, width, height } = bounds
  svg.setAttribute('viewBox', [left, top, width, height].join(' '))
  svg.setAttribute('width', String(width))
  svg.setAttribute('height', String(height))
  const background = document.createElementNS(svgNamespace, 'rect')
  background.setAttribute('x', String(left))
  background.setAttribute('y', String(top))
  background.setAttribute('width', String(width))
  background.setAttribute('height', String(height))
  background.setAttribute('fill', '#ffffff')
  svg.append(background)
  const drawing = art.cloneNode(true) as SVGGElement
  drawing.querySelectorAll('[data-diagram-control]').forEach(node => node.remove())
  svg.append(drawing)
  return { markup: new XMLSerializer().serializeToString(svg), width, height }
}

async function png(svg: ReturnType<typeof drawingSvg>) {
  const scale = Math.min(2, PNG_LIMIT / svg.width, PNG_LIMIT / svg.height, Math.sqrt(PNG_PIXELS / (svg.width * svg.height)))
  if (scale < .5) throw new Error('DIAGRAM_PNG_SIZE')
  const objectUrl = URL.createObjectURL(new Blob([svg.markup], { type: 'image/svg+xml' }))
  try {
    const image = new Image()
    image.src = objectUrl
    await image.decode()
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.floor(svg.width * scale))
    canvas.height = Math.max(1, Math.floor(svg.height * scale))
    const context = canvas.getContext('2d')
    if (!context) throw new Error('No drawing context')
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(result => result ? resolve(result) : reject(new Error('Unable to encode PNG')), 'image/png')
    })
  } finally {
    URL.revokeObjectURL(objectUrl)
  }
}

export async function diagramFile(doc: DiagramDocument, format: DiagramFormat, render: () => ReturnType<typeof drawingSvg>) {
  const stem = doc.title.replace(/[\u0000-\u001f\\/:*?"<>|]/g, '_').replace(/[. ]+$/, '') || 'diagram'
  const suggestedName = stem + '.' + format
  let blob: Blob
  if (format === 'tfdiagram') blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' })
  else {
    const svg = render()
    blob = format === 'png' ? await png(svg) : new Blob([svg.markup], { type: 'image/svg+xml' })
  }
  return { suggestedName, data: await blob.arrayBuffer(), mimeType: blob.type }
}
