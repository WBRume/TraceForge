export function diagramLines(value: string, width: number, fontSize: number, limit: number) {
  const capacity = Math.max(3, width / fontSize)
  const lines: string[] = []
  for (const paragraph of value.replace(/\r\n/g, '\n').split('\n')) {
    let line = ''
    let used = 0
    for (const letter of paragraph) {
      const size = /[^\u0020-\u024f]/u.test(letter) ? 1 : .57
      if (line && used + size > capacity) {
        lines.push(line.trimEnd())
        line = ''
        used = 0
      }
      line += letter
      used += size
    }
    lines.push(line.trimEnd())
  }
  const visible = lines.slice(0, Math.max(1, limit))
  if (lines.length > visible.length) visible[visible.length - 1] = visible.at(-1)!.trimEnd() + '…'
  return visible
}
