<script setup>
import { computed } from 'vue'
import { renderAiMarkdown } from '../shared/aiMarkdown.js'

const props = defineProps({
  text: { type: String, default: '' },
  streaming: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
})

const html = computed(() => renderAiMarkdown(props.text))
</script>

<template>
  <div class="ai-markdown" :class="{ compact, streaming }">
    <div v-html="html" />
    <span v-if="streaming" class="ai-markdown-caret" aria-hidden="true" />
  </div>
</template>

<style scoped>
.ai-markdown {
  color: inherit;
  font-size: inherit;
  line-height: 1.75;
  overflow-wrap: anywhere;
}

.ai-markdown :deep(> div > :first-child) {
  margin-top: 0;
}

.ai-markdown :deep(> div > :last-child) {
  margin-bottom: 0;
}

.ai-markdown :deep(h1),
.ai-markdown :deep(h2),
.ai-markdown :deep(h3),
.ai-markdown :deep(h4) {
  margin: 12px 0 6px;
  color: #111111;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.45;
}

.ai-markdown.compact :deep(h1),
.ai-markdown.compact :deep(h2),
.ai-markdown.compact :deep(h3),
.ai-markdown.compact :deep(h4) {
  margin: 9px 0 5px;
  font-size: 12.5px;
}

.ai-markdown :deep(p) {
  margin: 6px 0;
}

.ai-markdown.compact :deep(p) {
  margin: 4px 0;
}

.ai-markdown :deep(strong) {
  color: #111111;
  font-weight: 700;
}

.ai-markdown :deep(em) {
  color: #3F3F46;
  font-style: normal;
  font-weight: 600;
}

.ai-markdown :deep(ul),
.ai-markdown :deep(ol) {
  margin: 6px 0;
  padding-left: 18px;
}

.ai-markdown :deep(li) {
  margin: 3px 0;
  padding-left: 2px;
}

.ai-markdown :deep(li > p) {
  margin: 2px 0;
}

.ai-markdown :deep(blockquote) {
  margin: 8px 0;
  padding: 6px 10px;
  border-left: 3px solid #111111;
  border-radius: 0 4px 4px 0;
  background: #F7F7F7;
  color: #3F3F46;
}

.ai-markdown :deep(code) {
  border: 1px solid #EDEDED;
  border-radius: 3px;
  background: #F7F7F7;
  color: #27272A;
  font-family: "IBM Plex Mono", monospace;
  font-size: 0.92em;
  padding: 1px 4px;
}

.ai-markdown :deep(pre.ai-code-block) {
  margin: 8px 0;
  overflow: auto;
  padding: 10px 12px;
  border: 1px solid #EDEDED;
  border-radius: 6px;
  background: #111111;
  color: #F8FAFC;
}

.ai-markdown :deep(pre.ai-code-block code) {
  display: block;
  min-width: max-content;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  font-size: 11.5px;
  line-height: 1.65;
  white-space: pre;
}

.ai-markdown :deep(a) {
  color: #111111;
  font-weight: 700;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.ai-markdown :deep(hr) {
  height: 1px;
  margin: 12px 0;
  border: 0;
  background: #EDEDED;
}

.ai-markdown :deep(table) {
  display: block;
  width: 100%;
  max-width: 100%;
  margin: 8px 0;
  overflow-x: auto;
  border-collapse: collapse;
  font-size: 12px;
}

.ai-markdown :deep(th),
.ai-markdown :deep(td) {
  padding: 6px 8px;
  border: 1px solid #EDEDED;
  text-align: left;
  vertical-align: top;
  white-space: nowrap;
}

.ai-markdown :deep(th) {
  background: #F7F7F7;
  color: #111111;
  font-weight: 700;
}

.ai-markdown.streaming :deep(> div > :last-child) {
  display: inline-block;
  min-width: calc(100% - 12px);
  vertical-align: bottom;
}

.ai-markdown-caret {
  display: inline-block;
  width: 6px;
  height: 14px;
  margin-left: 2px;
  background: #111111;
  vertical-align: middle;
  animation: ai-markdown-caret-blink 1s steps(2) infinite;
}

@keyframes ai-markdown-caret-blink {
  50% {
    opacity: 0;
  }
}
</style>
