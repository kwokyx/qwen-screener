<script setup>
import { computed } from 'vue'
const props = defineProps({
  pct: { type: Number, required: true },
  size: { type: Number, default: 13 },
})
const positive = computed(() => props.pct >= 0)
</script>
<template>
  <span :style="{ color: positive ? '#C8312A' : '#0E8A66', fontWeight: 600, fontFamily: 'IBM Plex Mono, monospace', fontSize: size + 'px' }">
    {{ positive ? '+' : '' }}{{ pct.toFixed(2) }}%
  </span>
</template>
