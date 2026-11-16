<script setup lang="ts">
import { computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { micromark } from 'micromark'
import { gfm, gfmHtml } from 'micromark-extension-gfm'

const props = defineProps<{ source: string }>()
const { t } = useI18n()
const footnotePrefix = `chat-footnote-${useId()}-`
const footnoteLabelId = `${footnotePrefix}label`
const syntax = gfm()

const html = computed(() => {
  const template = document.createElement('template')
  // Raw HTML and unsafe URLs are disabled by the Markdown compiler.
  template.innerHTML = micromark(props.source, {
    extensions: [syntax],
    htmlExtensions: [gfmHtml({
      clobberPrefix: footnotePrefix,
      label: t('chat.markdown_footnotes'),
      labelAttributes: '',
      backLabel: t('chat.markdown_back_to_reference'),
    })],
  })
  const label = template.content.querySelector('#footnote-label')
  if (label) label.id = footnoteLabelId
  const url = document.createElement('a')
  for (const link of template.content.querySelectorAll('a')) {
    if (link.hasAttribute('data-footnote-ref')) {
      link.setAttribute('aria-describedby', footnoteLabelId)
      continue
    }
    if (link.hasAttribute('data-footnote-backref')) continue

    // Desktop clients open new-window links through the OS.
    url.href = link.getAttribute('href') || ''
    if (link.getAttribute('href') && ['http:', 'https:', 'mailto:'].includes(url.protocol)) {
      link.target = '_blank'
      link.rel = 'noopener noreferrer'
    } else {
      link.removeAttribute('href')
    }
  }
  for (const image of template.content.querySelectorAll('img')) {
    if (!image.getAttribute('src')) image.removeAttribute('src')
    image.loading = 'lazy'
    image.referrerPolicy = 'no-referrer'
  }
  for (const lineBreak of template.content.querySelectorAll('p br')) {
    const next = lineBreak.nextSibling
    // Paragraphs preserve soft line breaks, so the compiler's newline after
    // a hard break would otherwise produce a second visible line break.
    if (next instanceof Text && next.data.startsWith('\n')) next.deleteData(0, 1)
  }
  for (const table of template.content.querySelectorAll('table')) {
    const scroll = document.createElement('div')
    scroll.className = 'markdown-table-scroll'
    table.replaceWith(scroll)
    scroll.append(table)
  }
  return template.innerHTML
})

function followFootnote(event: MouseEvent) {
  if (!(event.target instanceof Element) || !(event.currentTarget instanceof HTMLElement)) return
  const link = event.target.closest<HTMLAnchorElement>('a[data-footnote-ref], a[data-footnote-backref]')
  if (!link) return

  event.preventDefault()
  const target = document.getElementById(link.hash.slice(1))
  if (!target || !event.currentTarget.contains(target)) return
  target.tabIndex = -1
  target.focus({ preventScroll: true })
  target.scrollIntoView({ block: 'center' })
}
</script>

<template>
  <div class="msg-content message-markdown" v-html="html" @click="followFootnote" />
</template>

<style scoped>
.message-markdown {
  white-space: normal;
  overflow-wrap: anywhere;
}

.message-markdown :deep(:where(p, h1, h2, h3, h4, h5, h6, ul, ol, blockquote, pre, hr, .markdown-table-scroll)) {
  margin: 0 0 0.65em;
}

.message-markdown :deep(:where(p, ul, ol, blockquote, pre, .markdown-table-scroll):last-child) {
  margin-bottom: 0;
}

.message-markdown :deep(p) {
  white-space: pre-line;
}

.message-markdown :deep(:where(h1, h2, h3, h4, h5, h6)) {
  color: inherit;
  line-height: 1.35;
}

.message-markdown :deep(h1) { font-size: 1.45em; }
.message-markdown :deep(h2) { font-size: 1.25em; }
.message-markdown :deep(h3) { font-size: 1.1em; }
.message-markdown :deep(:where(h4, h5, h6)) { font-size: 1em; }

.message-markdown :deep(:where(ul, ol)) {
  padding-inline-start: 1.5em;
}

.message-markdown :deep(li + li) { margin-top: 0.15em; }
.message-markdown :deep(li:has(> input[type='checkbox'], > p > input[type='checkbox'])) { list-style: none; }
.message-markdown :deep(input[type='checkbox']) { margin-inline: -1.25em 0.35em; }

.message-markdown :deep(blockquote) {
  padding-inline-start: 0.75em;
  border-inline-start: 3px solid #cbd5e1;
  color: #475569;
}

.message-markdown :deep(:where(hr, .footnotes)) {
  border: 0;
  border-top: 1px solid #dbe3ea;
}

.message-markdown :deep(a[href]) {
  color: #0369a1;
  text-decoration: underline;
  text-underline-offset: 0.15em;
}

.message-markdown :deep(img) { max-width: 100%; height: auto; }

.message-markdown :deep(:where(code, pre)) {
  font-family: ui-monospace, Consolas, monospace;
  background: #f1f5f9;
  border-radius: 5px;
}

.message-markdown :deep(:not(pre) > code) {
  padding: 0.12em 0.28em;
  font-size: 0.9em;
  white-space: pre-wrap;
}

.message-markdown :deep(pre) {
  max-width: 100%;
  padding: 0.65em 0.85em;
  overflow-x: auto;
  font-size: 0.88em;
  white-space: pre;
  word-break: normal;
  overflow-wrap: normal;
}

.message-markdown :deep(.markdown-table-scroll) { overflow-x: auto; }
.message-markdown :deep(table) { width: max-content; border-collapse: collapse; overflow-wrap: normal; word-break: normal; }
.message-markdown :deep(:where(th, td)) { border: 1px solid #dbe3ea; padding: 0.3em 0.65em; }
.message-markdown :deep(th) { background: #f1f5f9; }

.message-markdown :deep(.footnotes) { margin-top: 0.8em; padding-top: 0.5em; font-size: 0.87em; }
.message-markdown :deep(.footnotes h2) { font-size: 1em; }
</style>
