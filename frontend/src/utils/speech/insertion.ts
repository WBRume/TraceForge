/** Own only the current dictation range, so interim corrections cannot duplicate text. */
export class SpeechInsertion {
  private value: string
  private start: number
  private end: number

  constructor(value: string, start: number, end = start) {
    this.value = value
    this.start = Math.max(0, Math.min(start, value.length))
    this.end = Math.max(this.start, Math.min(end, value.length))
  }

  get caret() { return this.end }

  /** Preserve edits outside dictation; editing inside it commits the text and ends dictation. */
  rebase(value: string): boolean {
    if (value === this.value) return true
    let left = 0
    while (left < value.length && left < this.value.length && value[left] === this.value[left]) left++
    let oldRight = this.value.length
    let newRight = value.length
    while (oldRight > left && newRight > left && this.value[oldRight - 1] === value[newRight - 1]) { oldRight--; newRight-- }
    const delta = newRight - oldRight
    if (oldRight <= this.start) { this.start += delta; this.end += delta }
    else if (left < this.end) return false
    this.value = value
    return true
  }

  update(value: string, text: string): { value: string; caret: number } | undefined {
    if (!this.rebase(value)) return
    this.value = value.slice(0, this.start) + text + value.slice(this.end)
    this.end = this.start + text.length
    return { value: this.value, caret: this.end }
  }
}
