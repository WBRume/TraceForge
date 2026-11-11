/** Small, safe inline Markdown subset shared by diagnosis and case views. */

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/**
 * Render inline code and bold only. The input is escaped before any tags are
 * injected, so model-authored text cannot become arbitrary HTML.
 */
export function renderInlineMarkdown(value: string | null | undefined): string {
  return escapeHtml(String(value || ''))
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`([，。；：！？、）》」』】])?/g, (_match, code: string, punctuation: string) => {
      const chip = `<code class="inline-code">${code}</code>`
      return punctuation ? `<span class="inline-nb">${chip}${punctuation}</span>` : chip
    })
    .replace(/\n/g, '<br>')
}
