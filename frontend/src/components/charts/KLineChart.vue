<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { dispose, init } from 'klinecharts'

const props = defineProps({
  data: { type: Array, required: true },
  height: { type: Number, default: 430 },
  indicator: { type: String, default: 'MA' },
  fitContent: { type: Boolean, default: true },
  visibleBars: { type: Number, default: 90 },
})

const chartEl = ref(null)
let chart = null
let resizeObserver = null

const monoFont = 'IBM Plex Mono, ui-monospace, SFMono-Regular, Menlo, monospace'

function formatVolume(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '--'
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toFixed(0)
}

function formatDateLabel(timestamp) {
  const d = new Date(timestamp)
  if (!Number.isFinite(d.getTime())) return ''
  const pad = (v) => String(v).padStart(2, '0')
  const date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  return d.getHours() || d.getMinutes() ? `${date} ${time}` : date
}

function toTimestamp(value) {
  if (value instanceof Date) return value.getTime()
  if (typeof value === 'number') return value
  const raw = String(value || '')
  if (raw.includes('T') || raw.includes(' ')) {
    const time = new Date(raw).getTime()
    return Number.isFinite(time) ? time : Number.NaN
  }
  const [year, month, date] = raw.split('-').map(Number)
  if (!year || !month || !date) return Number.NaN
  return new Date(year, month - 1, date).getTime()
}

const chartData = computed(() => props.data.map((d) => ({
  timestamp: toTimestamp(d.timestamp ?? d.datetime ?? d.day),
  open: d.o,
  high: d.h,
  low: d.l,
  close: d.c,
  volume: d.v,
})).filter((d) => d.timestamp && d.open != null && d.high != null && d.low != null && d.close != null))

function applyData() {
  if (!chart) return
  syncBarSpace()
  chart.applyNewData(chartData.value)
  chart.setPriceVolumePrecision(2, 0)
  chart.scrollToRealTime(0)
}

function syncBarSpace() {
  if (!chart || !chartEl.value || !props.fitContent) return
  const count = Math.max(chartData.value.length, 1)
  const width = chartEl.value.clientWidth || 900
  const visibleCount = Math.max(12, Math.min(props.visibleBars, count))
  const target = (width - 92) / visibleCount
  const barSpace = Math.max(4.5, Math.min(18, target))
  chart.setBarSpace(barSpace)
  chart.setOffsetRightDistance(8)
  chart.setLeftMinVisibleBarCount(2)
  chart.setRightMinVisibleBarCount(2)
}

function syncIndicator() {
  if (!chart) return

  chart.removeIndicator('candle_pane', 'MA')
  chart.removeIndicator('candle_pane', 'BOLL')
  chart.removeIndicator('volume_pane')
  chart.removeIndicator('indicator_pane')

  chart.createIndicator('VOL', false, { id: 'volume_pane', height: 58, minHeight: 46, dragEnabled: false })

  if (props.indicator === 'MA' || props.indicator === 'BOLL') {
    chart.createIndicator(props.indicator, false, { id: 'candle_pane' })
    return
  }

  chart.createIndicator(props.indicator, false, { id: 'indicator_pane', height: 78, minHeight: 60, dragEnabled: false })
}

function initChart() {
  if (!chartEl.value) return
  chart = init(chartEl.value, {
    customApi: {
      formatDate: (_dateTimeFormat, timestamp) => formatDateLabel(timestamp),
      formatBigNumber: formatVolume,
    },
    styles: {
      grid: {
        show: true,
        horizontal: { show: true, color: '#ECEFF3', style: 'dashed', dashedValue: [2, 4], size: 1 },
        vertical: { show: true, color: '#F4F5F7', style: 'dashed', dashedValue: [2, 6], size: 1 },
      },
      candle: {
        type: 'candle_solid',
        margin: {
          top: 0.08,
          bottom: 0.04,
        },
        bar: {
          upColor: '#D84A66',
          downColor: '#10A56B',
          noChangeColor: '#94A3B8',
          upBorderColor: '#D84A66',
          downBorderColor: '#10A56B',
          noChangeBorderColor: '#94A3B8',
          upWickColor: '#D84A66',
          downWickColor: '#10A56B',
          noChangeWickColor: '#94A3B8',
        },
        priceMark: {
          show: true,
          high: { show: true, color: '#9CA3AF', textColor: '#64748B', textSize: 10, textFamily: monoFont },
          low: { show: true, color: '#9CA3AF', textColor: '#64748B', textSize: 10, textFamily: monoFont },
          last: {
            show: true,
            upColor: '#D84A66',
            downColor: '#10A56B',
            noChangeColor: '#94A3B8',
            line: { show: true, style: 'dashed', dashedValue: [3, 4], size: 1 },
            text: { show: true, color: '#FFFFFF', size: 11, family: monoFont, weight: 700 },
          },
        },
        tooltip: {
          showRule: 'follow_cross',
          showType: 'rect',
          defaultValue: '--',
          text: {
            size: 11,
            color: '#334155',
            family: monoFont,
            weight: 600,
            marginStart: 6,
            marginEnd: 6,
            marginTop: 3,
            marginBottom: 3,
          },
          rect: {
            position: 'fixed',
            offsetLeft: 8,
            offsetTop: 8,
            offsetRight: 8,
            borderRadius: 4,
            borderSize: 1,
            borderColor: '#E5E7EB',
            color: 'rgba(255, 255, 255, 0.96)',
            style: 'stroke_fill',
          },
        },
      },
      xAxis: {
        show: true,
        size: 24,
        axisLine: { show: true, color: '#E5E7EB', size: 1 },
        tickText: { show: true, color: '#6B7280', size: 10, family: monoFont, weight: 500, marginStart: 4, marginEnd: 4 },
        tickLine: { show: false, color: '#E5E7EB', size: 1, length: 3 },
      },
      yAxis: {
        show: true,
        size: 58,
        position: 'right',
        inside: true,
        axisLine: { show: false, color: '#E5E7EB', size: 1 },
        tickText: { show: true, color: '#6B7280', size: 10, family: monoFont, weight: 500, marginStart: 4, marginEnd: 6 },
        tickLine: { show: false, color: '#E5E7EB', size: 1, length: 3 },
      },
      separator: { size: 1, color: '#E5E7EB', fill: true, activeBackgroundColor: '#F3F4F6' },
      indicator: {
        lastValueMark: {
          show: false,
        },
        tooltip: {
          showName: true,
          showParams: true,
          showRule: 'follow_cross',
          defaultValue: '--',
          text: {
            size: 10,
            color: '#64748B',
            family: monoFont,
            weight: 600,
            marginStart: 5,
            marginEnd: 5,
            marginTop: 2,
            marginBottom: 2,
          },
        },
        bars: [
          { upColor: 'rgba(216, 74, 102, 0.52)', downColor: 'rgba(16, 165, 107, 0.52)', noChangeColor: 'rgba(148, 163, 184, 0.38)' },
        ],
        lines: [
          { color: '#2563EB', size: 1 },
          { color: '#F59E0B', size: 1 },
          { color: '#7C3AED', size: 1 },
          { color: '#0EA5E9', size: 1 },
          { color: '#64748B', size: 1 },
        ],
      },
      crosshair: {
        show: true,
        horizontal: {
          show: true,
          line: { show: true, color: '#94A3B8', style: 'dashed', dashedValue: [3, 4], size: 1 },
          text: { show: true, backgroundColor: '#111827', color: '#F8FAFC', size: 10, family: monoFont, borderRadius: 3 },
        },
        vertical: {
          show: true,
          line: { show: true, color: '#94A3B8', style: 'dashed', dashedValue: [3, 4], size: 1 },
          text: { show: true, backgroundColor: '#111827', color: '#F8FAFC', size: 10, family: monoFont, borderRadius: 3 },
        },
      },
    },
  })

  if (!chart) return
  syncBarSpace()
  syncIndicator()
  applyData()
  resizeObserver = new ResizeObserver(() => {
    chart?.resize()
    syncBarSpace()
  })
  resizeObserver.observe(chartEl.value)
}

onMounted(initChart)

watch(chartData, applyData, { deep: true })
watch(() => props.indicator, syncIndicator)
watch(() => props.fitContent, syncBarSpace)
watch(() => props.visibleBars, syncBarSpace)

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  if (chart) dispose(chart)
  chart = null
})
</script>

<template>
  <div ref="chartEl" class="kline-chart" :style="{ height: `${height}px` }" />
</template>

<style scoped>
.kline-chart {
  width: 100%;
  background: #FFFFFF;
  border: 1px solid #EDEDED;
  border-radius: 6px;
  overflow: hidden;
}
</style>
