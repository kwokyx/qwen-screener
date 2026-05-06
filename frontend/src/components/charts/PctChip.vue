<script setup>
import { computed } from 'vue'
const props = defineProps({
  pct: { type: Number, required: true },
  size: { type: String, default: 'md' },
})
const positive = computed(() => props.pct >= 0)
const color = computed(() => positive.value ? '#C8312A' : '#0E8A66')
const bg = computed(() => positive.value ? '#FBEEEC' : '#E9F6F0')
const sizes = { sm: { fs: 11, py: 1, px: 5 }, md: { fs: 12, py: 2, px: 6 }, lg: { fs: 14, py: 3, px: 8 } }
const s = computed(() => sizes[props.size])
</script>
<template>
  <span :style="{ display: 'inline-flex', alignItems: 'center', gap: '2px', color, background: bg, padding: `${s.py}px ${s.px}px`, borderRadius: '4px', fontSize: s.fs + 'px', fontWeight: 600, fontFamily: 'IBM Plex Mono, JetBrains Mono, monospace' }">
    {{ positive ? '+' : '' }}{{ pct.toFixed(2) }}%
  </span>
</template>
