<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Array, required: true },
  width: { type: Number, default: 800 },
  height: { type: Number, default: 320 },
  showVol: { type: Boolean, default: true },
})

const UP = '#C8312A'
const DOWN = '#0E8A66'

const view = computed(() => {
  const data = props.data
  if (!data) return null
  const volH = props.showVol ? 60 : 0
  const priceH = props.height - volH - 20
  const allHigh = Math.max(...data.map(d => d.h))
  const allLow = Math.min(...data.map(d => d.l))
  const padding = (allHigh - allLow) * 0.05
  const yMax = allHigh + padding
  const yMin = allLow - padding
  const range = yMax - yMin || 1
  const cw = (props.width - 60) / data.length
  const candleW = Math.max(2, cw * 0.7)
  const maxVol = Math.max(...data.map(d => d.v))

  const ma = (n) => data.map((_, i) => {
    if (i < n - 1) return null
    const slice = data.slice(i - n + 1, i + 1)
    return slice.reduce((s, d) => s + d.c, 0) / n
  })
  const ma5 = ma(5), ma20 = ma(20)
  const buildPath = (arr) => {
    let path = ''
    arr.forEach((v, i) => {
      if (v == null) return
      const x = 50 + i * cw + cw / 2
      const y = ((yMax - v) / range) * priceH + 10
      path += (path ? 'L' : 'M') + x + ',' + y
    })
    return path
  }

  const ySteps = 5
  const yLabels = []
  for (let i = 0; i <= ySteps; i++) {
    const v = yMin + (range * i) / ySteps
    const y = priceH - (i / ySteps) * priceH + 10
    yLabels.push({ v, y })
  }

  const candles = data.map((d, i) => {
    const x = 50 + i * cw + cw / 2
    const yH = ((yMax - d.h) / range) * priceH + 10
    const yL = ((yMax - d.l) / range) * priceH + 10
    const yO = ((yMax - d.o) / range) * priceH + 10
    const yC = ((yMax - d.c) / range) * priceH + 10
    const isUp = d.c >= d.o
    const color = isUp ? UP : DOWN
    return {
      x, yH, yL, color,
      rectX: x - candleW / 2,
      rectY: Math.min(yO, yC),
      rectH: Math.max(0.5, Math.abs(yC - yO)),
      candleW,
    }
  })

  const vols = data.map((d, i) => {
    const x = 50 + i * cw + cw / 2
    const h = (d.v / maxVol) * (volH - 10)
    const y = props.height - 10 - h
    const isUp = d.c >= d.o
    return { x: x - candleW / 2, y, w: candleW, h, color: (isUp ? UP : DOWN) + '99' }
  })

  return { yLabels, candles, vols, ma5Path: buildPath(ma5), ma20Path: buildPath(ma20) }
})
</script>

<template>
  <svg v-if="view" :width="width" :height="height" style="display:block; font-family: 'IBM Plex Mono', monospace">
    <g v-for="(l, i) in view.yLabels" :key="i">
      <line x1="50" :x2="width - 10" :y1="l.y" :y2="l.y" stroke="#f1f5f9" stroke-width="1" />
      <text x="44" :y="l.y + 3" font-size="10" fill="#94a3b8" text-anchor="end">{{ l.v.toFixed(2) }}</text>
    </g>
    <g v-for="(c, i) in view.candles" :key="i">
      <line :x1="c.x" :x2="c.x" :y1="c.yH" :y2="c.yL" :stroke="c.color" stroke-width="1" />
      <rect :x="c.rectX" :y="c.rectY" :width="c.candleW" :height="c.rectH" :fill="c.color" :stroke="c.color" />
    </g>
    <path :d="view.ma5Path" fill="none" stroke="#f59e0b" stroke-width="1.2" />
    <path :d="view.ma20Path" fill="none" stroke="#8b5cf6" stroke-width="1.2" />
    <rect v-for="(v, i) in view.vols" :key="'v'+i" :x="v.x" :y="v.y" :width="v.w" :height="v.h" :fill="v.color" />
  </svg>
</template>
