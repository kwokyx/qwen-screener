<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Array, required: true },
  width: { type: Number, default: 80 },
  height: { type: Number, default: 28 },
  color: { type: String, default: null },
  fill: { type: String, default: null },
})

const UP = '#C8312A'
const DOWN = '#0E8A66'

const view = computed(() => {
  if (!props.data || props.data.length === 0) return null
  const min = Math.min(...props.data)
  const max = Math.max(...props.data)
  const range = max - min || 1
  const dx = props.width / (props.data.length - 1)
  const pts = props.data.map((v, i) => [i * dx, props.height - ((v - min) / range) * props.height])
  const trend = props.data[props.data.length - 1] >= props.data[0]
  const c = props.color || (trend ? UP : DOWN)
  const f = props.fill || c + '22'
  const path = pts.map((p, i) => (i === 0 ? `M${p[0]},${p[1]}` : `L${p[0]},${p[1]}`)).join(' ')
  const area = path + ` L${props.width},${props.height} L0,${props.height} Z`
  return { path, area, c, f }
})
</script>

<template>
  <svg v-if="view" :width="width" :height="height" style="display:block">
    <path :d="view.area" :fill="view.f" />
    <path :d="view.path" fill="none" :stroke="view.c" stroke-width="1.5" stroke-linejoin="round" />
  </svg>
</template>
