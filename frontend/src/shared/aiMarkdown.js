import { marked } from 'marked'

function tokenText(input) {
  if (typeof input === 'string') return input
  return input?.text ?? ''
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/`/g, '&#96;')
}

function safeUrl(value) {
  const raw = String(value ?? '').trim()
  if (!raw) return ''
  if (/^(javascript|data|vbscript):/i.test(raw)) return ''
  if (/^(https?:|mailto:|tel:)/i.test(raw)) return raw
  if (/^(#|\/|\.\.?\/)/.test(raw)) return raw
  return ''
}

function safeLanguage(value) {
  const lang = String(value ?? '').trim().toLowerCase()
  return /^[a-z0-9_+-]{1,24}$/.test(lang) ? lang : 'text'
}

function unwrapMarkdownFence(text) {
  const raw = String(text ?? '').trim()
  const match = raw.match(/^```([a-zA-Z0-9_-]*)[ \t]*\n([\s\S]*?)\n?```[ \t]*$/)
  if (!match) return raw

  const lang = (match[1] || '').toLowerCase()
  const body = match[2] || ''
  const markdownLike = /(^|\n)(#{1,6}\s|[-*+]\s|\d+\.\s|>\s|```|\|.+\|)/.test(body)
  if (!lang || lang === 'md' || lang === 'markdown' || markdownLike) return body.trim()
  return raw
}

export function repairAiMarkdown(text) {
  let out = unwrapMarkdownFence(text).replace(/\r/g, '')
  if (!out) return ''

  const codeBlocks = []
  out = out.replace(/```[\s\S]*?```/g, (match) => {
    const index = codeBlocks.push(match) - 1
    return `\u0000AI_CODE_${index}\u0000`
  })

  out = out
    .replace(/([^\n#])(#{2,6})(?=[^\n#])/g, '$1\n\n$2')
    .replace(/(^|\n)(#{1,6})(?=[^\s#])/g, '$1$2 ')
    .replace(/\*\*\s+([^*\n][^*\n]*?)\s+\*\*/g, '**$1**')
    .replace(/\*\*\s+([^*\n]+?)\*\*/g, '**$1**')
    .replace(/\*\*([^*\n]+?)\s+\*\*/g, '**$1**')
    .replace(/(\*\*[^*\n]+?\*\*)(?=[\u4e00-\u9fff])/g, '$1 ')
    .replace(/([\u4e00-\u9fff])(\*\*[^*\n]+?\*\*)/g, '$1 $2')
    .replace(/([。；;：:])\s*([-*+]\s+)/g, '$1\n\n$2')
    .replace(/([。；;：:])\s*(\d+\.\s+)/g, '$1\n\n$2')
    .replace(/(^|\n)([-*+])(?=[^\s-*+])/g, '$1$2 ')
    .replace(/([^\n])\n(#{1,6}\s+)/g, '$1\n\n$2')
    .replace(/(^|\n)(#{1,6}\s[^\n]+)\n(?!\n)/g, '$1$2\n\n')
    .replace(/\n{3,}/g, '\n\n')

  out = out.replace(/(^|\n)([^\n]+)\n(\s*(?:[-*+]\s+|\d+\.\s+))/g, (_match, prefix, previous, marker) => {
    const previousIsList = /^\s*(?:[-*+]\s+|\d+\.\s+)/.test(previous)
    return `${prefix}${previous}\n${previousIsList ? '' : '\n'}${marker}`
  })

  out = out.replace(/\u0000AI_CODE_(\d+)\u0000/g, (_match, index) => codeBlocks[Number(index)] || '')
  return out.trim()
}

const markdownRenderer = new marked.Renderer()

markdownRenderer.html = function html(input) {
  return escapeHtml(tokenText(input))
}

markdownRenderer.code = function code(input) {
  const text = typeof input === 'string' ? input : input?.text ?? ''
  const lang = typeof input === 'string' ? arguments[1] : input?.lang ?? ''
  const language = safeLanguage(lang)
  return `<pre class="ai-code-block"><code class="language-${language}">${escapeHtml(text)}</code></pre>`
}

markdownRenderer.link = function link(input) {
  const href = safeUrl(input?.href)
  const label = escapeHtml(tokenText(input) || input?.href || '')
  if (!href) return label
  const title = input?.title ? ` title="${escapeAttribute(input.title)}"` : ''
  return `<a href="${escapeAttribute(href)}"${title} target="_blank" rel="noreferrer noopener">${label}</a>`
}

markdownRenderer.image = function image(input) {
  const label = tokenText(input)
  return label ? `<em>${escapeHtml(label)}</em>` : ''
}

function sanitizeRenderedHtml(html) {
  if (typeof window === 'undefined' || typeof DOMParser === 'undefined') {
    return html
  }

  const doc = new DOMParser().parseFromString(html || '', 'text/html')
  doc
    .querySelectorAll('script, iframe, object, embed, link, meta, style, form, input, button, svg, math, img, video, audio, source')
    .forEach((node) => node.remove())

  doc.body.querySelectorAll('*').forEach((node) => {
    Array.from(node.attributes).forEach((attr) => {
      const name = attr.name.toLowerCase()
      const value = attr.value || ''
      const isCodeClass = name === 'class' && ['CODE', 'PRE'].includes(node.tagName)
      const isAnchorAttr = node.tagName === 'A' && ['href', 'title', 'target', 'rel'].includes(name)
      if (name.startsWith('on') || (!isCodeClass && !isAnchorAttr)) {
        node.removeAttribute(attr.name)
        return
      }
      if ((name === 'href' || name === 'src') && !safeUrl(value)) {
        node.removeAttribute(attr.name)
      }
    })

    if (node.tagName === 'A') {
      node.setAttribute('target', '_blank')
      node.setAttribute('rel', 'noreferrer noopener')
    }
  })

  return doc.body.innerHTML
}

export function renderAiMarkdown(text) {
  if (!String(text ?? '').trim()) return ''
  return sanitizeRenderedHtml(
    marked.parse(repairAiMarkdown(text), {
      breaks: true,
      gfm: true,
      renderer: markdownRenderer,
    }),
  )
}
