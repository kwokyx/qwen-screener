<script setup>
import { computed } from 'vue'
const props = defineProps({
  value: { type: Number, required: true },
  max: { type: Number, default: 100 },
  size: { type: Number, default: 64 },
  stroke: { type: Number, default: 8 },
  color: { type: String, default: '#2456D8' },
  label: { type: [String, Number], default: '' },
})
const r = computed(() => (props.size - props.stroke) / 2)
const c = computed(() => 2 * Math.PI * r.value)
const filled = computed(() => Math.min(1, props.value / props.max))
</script>
<template>
  <svg :width="size" :height="size">
    <circle :cx="size/2" :cy="size/2" :r="r" fill="none" stroke="#f1f5f9" :stroke-width="stroke" />
    <circle :cx="size/2" :cy="size/2" :r="r" fill="none" :stroke="color" :stroke-width="stroke" :stroke-dasharray="`${c * filled} ${c}`" stroke-linecap="round" :transform="`rotate(-90 ${size/2} ${size/2})`" />
    <text v-if="label !== ''" :x="size/2" :y="size/2 + 4" text-anchor="middle" :font-size="size * 0.28" font-weight="700" fill="#1e293b">{{ label }}</text>
  </svg>
</template>
