<script setup>
import { computed, ref } from 'vue'

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
  if (!data || !data.length) return null
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
      ma5: ma5[i],
      ma20: ma20[i],
    }
  })

  const vols = data.map((d, i) => {
    const x = 50 + i * cw + cw / 2
    const h = (d.v / maxVol) * (volH - 10)
    const y = props.height - 10 - h
    const isUp = d.c >= d.o
    return { x: x - candleW / 2, y, w: candleW, h, color: (isUp ? UP : DOWN) + '99' }
  })

  return { yLabels, candles, vols, ma5Path: buildPath(ma5), ma20Path: buildPath(ma20), cw, priceH, volH, yMax, range }
})

// ---- Hover 交互 ----
const svgRef = ref(null)
const hoverIdx = ref(-1)
const cursorY = ref(0)        // 鼠标 Y（用于横向标尺）

function onMove(e) {
  if (!view.value || !svgRef.value) return
  // 把屏幕坐标转回 SVG 内坐标（处理 viewBox / 缩放）
  const rect = svgRef.value.getBoundingClientRect()
  const sx = (e.clientX - rect.left) * (props.width / rect.width)
  const sy = (e.clientY - rect.top) * (props.height / rect.height)
  // 找最近的蜡烛
  const candles = view.value.candles
  let bestI = 0, bestD = Infinity
  for (let i = 0; i < candles.length; i++) {
    const dx = Math.abs(candles[i].x - sx)
    if (dx < bestD) { bestD = dx; bestI = i }
  }
  hoverIdx.value = bestI
  cursorY.value = Math.max(10, Math.min(props.height - 10, sy))
}

function onLeave() {
  hoverIdx.value = -1
}

const hover = computed(() => {
  if (hoverIdx.value < 0 || !view.value) return null
  const i = hoverIdx.value
  const d = props.data[i]
  if (!d) return null
  const c = view.value.candles[i]
  // tooltip 横向防溢出：默认放右边，靠近右侧时翻到左边
  const TIP_W = 168
  const TIP_PAD = 8
  const onRight = c.x + TIP_W + TIP_PAD < props.width - 10
  const tipX = onRight ? c.x + TIP_PAD : c.x - TIP_W - TIP_PAD
  // y 价格刻度（以鼠标 y 反推）
  const yMax = view.value.yMax, range = view.value.range, priceH = view.value.priceH
  const yPrice = yMax - ((cursorY.value - 10) / priceH) * range
  return {
    i,
    x: c.x,
    rawDate: d.day,
    open: d.o, high: d.h, low: d.l, close: d.c, vol: d.v,
    isUp: d.c >= d.o,
    pct: d.o > 0 ? ((d.c - d.o) / d.o) * 100 : 0,
    ma5: c.ma5, ma20: c.ma20,
    tipX, tipW: TIP_W,
    cursorY: cursorY.value,
    cursorPrice: yPrice >= view.value.yMax - range && yPrice <= view.value.yMax ? yPrice : null,
  }
})

function fmtDate(d) {
  if (!d) return '—'
  if (typeof d === 'string') return d
  // 是 Date 或 number → 转 YYYY-MM-DD
  try { return new Date(d).toISOString().slice(0, 10) } catch { return String(d) }
}
function fmt(v, n = 2) { return v == null ? '—' : Number(v).toFixed(n) }
function fmtVol(v) {
  if (v == null) return '—'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return String(Math.round(v))
}
</script>

<template>
  <svg v-if="view" ref="svgRef" :width="width" :height="height"
       style="display:block; font-family: 'IBM Plex Mono', monospace; user-select: none"
       @mousemove="onMove" @mouseleave="onLeave">
    <!-- 网格 + Y 标签 -->
    <g v-for="(l, i) in view.yLabels" :key="i">
      <line x1="50" :x2="width - 10" :y1="l.y" :y2="l.y" stroke="#f1f5f9" stroke-width="1" />
      <text x="44" :y="l.y + 3" font-size="10" fill="#94a3b8" text-anchor="end">{{ l.v.toFixed(2) }}</text>
    </g>
    <!-- 蜡烛 -->
    <g v-for="(c, i) in view.candles" :key="i">
      <line :x1="c.x" :x2="c.x" :y1="c.yH" :y2="c.yL" :stroke="c.color" stroke-width="1" />
      <rect :x="c.rectX" :y="c.rectY" :width="c.candleW" :height="c.rectH" :fill="c.color" :stroke="c.color" />
    </g>
    <!-- MA 线 -->
    <path :d="view.ma5Path" fill="none" stroke="#f59e0b" stroke-width="1.2" />
    <path :d="view.ma20Path" fill="none" stroke="#8b5cf6" stroke-width="1.2" />
    <!-- 量柱 -->
    <rect v-for="(v, i) in view.vols" :key="'v'+i" :x="v.x" :y="v.y" :width="v.w" :height="v.h" :fill="v.color" />

    <!-- ===== Hover 十字光标 + tooltip ===== -->
    <g v-if="hover">
      <!-- 垂直竖线 -->
      <line :x1="hover.x" :x2="hover.x" y1="10" :y2="height - 10"
            stroke="#7A776F" stroke-width="0.8" stroke-dasharray="3,3" pointer-events="none" />
      <!-- 水平横线 -->
      <line x1="50" :x2="width - 10" :y1="hover.cursorY" :y2="hover.cursorY"
            stroke="#7A776F" stroke-width="0.8" stroke-dasharray="3,3" pointer-events="none" />
      <!-- 高亮当前蜡烛 -->
      <circle :cx="hover.x" :cy="((view.yMax - hover.close) / view.range) * view.priceH + 10" r="3.5"
              :fill="hover.isUp ? '#C8312A' : '#0E8A66'" stroke="#fff" stroke-width="1.5" pointer-events="none" />
      <!-- Y 轴价格徽标 -->
      <g v-if="hover.cursorPrice != null" pointer-events="none">
        <rect x="2" :y="hover.cursorY - 8" width="44" height="16" rx="3" fill="#1F1F1D" />
        <text x="24" :y="hover.cursorY + 3.5" font-size="10" fill="#fff" text-anchor="middle">
          {{ hover.cursorPrice.toFixed(2) }}
        </text>
      </g>
      <!-- X 轴日期徽标 -->
      <g pointer-events="none">
        <rect :x="hover.x - 36" :y="height - 26" width="72" height="16" rx="3" fill="#1F1F1D" />
        <text :x="hover.x" :y="height - 14" font-size="10" fill="#fff" text-anchor="middle">
          {{ fmtDate(hover.rawDate) }}
        </text>
      </g>

      <!-- Tooltip 卡片 -->
      <g pointer-events="none">
        <rect :x="hover.tipX" y="14" :width="hover.tipW" height="142" rx="6"
              fill="#FFFFFF" stroke="rgba(14,14,12,0.10)" stroke-width="1"
              filter="url(#tip-shadow)" />
        <defs>
          <filter id="tip-shadow" x="-10%" y="-10%" width="120%" height="120%">
            <feDropShadow dx="0" dy="2" stdDeviation="4" flood-opacity="0.10" />
          </filter>
        </defs>
        <text :x="hover.tipX + 10" y="30" font-size="10.5" fill="#7A776F" font-family="IBM Plex Sans, sans-serif">
          {{ fmtDate(hover.rawDate) }}
        </text>
        <text :x="hover.tipX + hover.tipW - 10" y="30" font-size="10.5"
              :fill="hover.isUp ? '#C8312A' : '#0E8A66'" text-anchor="end" font-weight="700">
          {{ hover.isUp ? '+' : '' }}{{ hover.pct.toFixed(2) }}%
        </text>

        <!-- OHLC 双列 -->
        <g font-size="10.5" font-family="IBM Plex Sans, sans-serif">
          <text :x="hover.tipX + 10" y="50" fill="#7A776F">开</text>
          <text :x="hover.tipX + 78" y="50" fill="#111110" text-anchor="end" font-family="IBM Plex Mono, monospace" font-weight="600">{{ fmt(hover.open) }}</text>

          <text :x="hover.tipX + 88" y="50" fill="#7A776F">高</text>
          <text :x="hover.tipX + hover.tipW - 10" y="50" fill="#C8312A" text-anchor="end" font-family="IBM Plex Mono, monospace" font-weight="600">{{ fmt(hover.high) }}</text>

          <text :x="hover.tipX + 10" y="68" fill="#7A776F">收</text>
          <text :x="hover.tipX + 78" y="68" :fill="hover.isUp ? '#C8312A' : '#0E8A66'" text-anchor="end" font-family="IBM Plex Mono, monospace" font-weight="700">{{ fmt(hover.close) }}</text>

          <text :x="hover.tipX + 88" y="68" fill="#7A776F">低</text>
          <text :x="hover.tipX + hover.tipW - 10" y="68" fill="#0E8A66" text-anchor="end" font-family="IBM Plex Mono, monospace" font-weight="600">{{ fmt(hover.low) }}</text>

          <text :x="hover.tipX + 10" y="86" fill="#7A776F">量</text>
          <text :x="hover.tipX + hover.tipW - 10" y="86" fill="#3F3D38" text-anchor="end" font-family="IBM Plex Mono, monospace" font-weight="600">{{ fmtVol(hover.vol) }}</text>
        </g>

        <!-- 分割 -->
        <line :x1="hover.tipX + 10" :x2="hover.tipX + hover.tipW - 10" y1="98" y2="98"
              stroke="rgba(14,14,12,0.08)" stroke-width="1" stroke-dasharray="2,2" />

        <!-- MA -->
        <g font-size="10.5" font-family="IBM Plex Sans, sans-serif">
          <circle :cx="hover.tipX + 14" cy="113" r="3" fill="#f59e0b" />
          <text :x="hover.tipX + 22" y="116" fill="#7A776F">MA5</text>
          <text :x="hover.tipX + hover.tipW - 10" y="116" fill="#111110" text-anchor="end" font-family="IBM Plex Mono, monospace" font-weight="600">{{ fmt(hover.ma5) }}</text>

          <circle :cx="hover.tipX + 14" cy="133" r="3" fill="#8b5cf6" />
          <text :x="hover.tipX + 22" y="136" fill="#7A776F">MA20</text>
          <text :x="hover.tipX + hover.tipW - 10" y="136" fill="#111110" text-anchor="end" font-family="IBM Plex Mono, monospace" font-weight="600">{{ fmt(hover.ma20) }}</text>
        </g>

        <text :x="hover.tipX + 10" y="151" font-size="9.5" fill="#B8B4A8" font-family="IBM Plex Sans, sans-serif">
          第 {{ hover.i + 1 }} / {{ data.length }} 根
        </text>
      </g>
    </g>
  </svg>
</template>
