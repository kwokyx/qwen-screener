<script setup>
import { computed, h, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import KLineChart from '../components/charts/KLineChart.vue'
import {
  NAlert,
  NButton,
  NButtonGroup,
  NCard,
  NDataTable,
  NDescriptions,
  NDescriptionsItem,
  NGi,
  NGrid,
  NProgress,
  NResult,
  NSkeleton,
  NSpace,
  NSpin,
  NStatistic,
  NTabPane,
  NTag,
  NTabs,
} from 'naive-ui'
import { Preview } from '../shared/theme.js'
import * as stockApi from '../api/stock'
import * as qwenApi from '../api/qwen'
import * as screenerApi from '../api/screener'
import EmptyState from '../components/EmptyState.vue'
import { useAiStatusStore } from '../stores/aiStatus'

const aiStatus = useAiStatusStore()
import { marked } from 'marked'
import { friendlyError } from '../shared/errors.js'

marked.setOptions({ breaks: true, gfm: true })
import StarButton from '../components/StarButton.vue'
import AlertRuleEditor from '../components/AlertRuleEditor.vue'
import { useWatchlistStore } from '../stores/watchlist'

const wl = useWatchlistStore()

const route = useRoute()
const router = useRouter()

const code = computed(() => route.params.code || '600519.SH')

const detail = ref(null)
const quote = ref(null)
const rawDailyKlineData = ref([])
const rawPeriodKlineData = ref([])
const rawKlineData = ref([])
const loading = ref(true)
const errorMsg = ref('')

const aiText = ref('')
const aiLoading = ref(false)
const aiStreaming = ref(false)
const aiError = ref('')
let aiAbort = null
let quoteTimer = null

const dailyKlineRanges = [
  { label: '近1个月', short: '1月', days: 22 },
  { label: '近3个月', short: '3月', days: 66 },
  { label: '近6个月', short: '6月', days: 120 },
  { label: '近1年', short: '1年', days: 240 },
  { label: '近2年', short: '2年', days: 480 },
]
const weeklyKlineRanges = [
  { label: '近6个月', short: '6月', days: 26 },
  { label: '近1年', short: '1年', days: 52 },
  { label: '近3年', short: '3年', days: 156 },
  { label: '近5年', short: '5年', days: 260 },
]
const monthlyKlineRanges = [
  { label: '近1年', short: '1年', days: 12 },
  { label: '近3年', short: '3年', days: 36 },
  { label: '近5年', short: '5年', days: 60 },
  { label: '近10年', short: '10年', days: 120 },
]
const intradayKlineRanges = [
  { label: '最近1个交易日', short: '1日', days: 1 },
  { label: '最近3个交易日', short: '3日', days: 3 },
  { label: '最近5个交易日', short: '5日', days: 5 },
  { label: '最近10个交易日', short: '10日', days: 10 },
]
const klineFrequencies = [
  { label: '5分', value: '5m', frequency: '5', intraday: true },
  { label: '15分', value: '15m', frequency: '15', intraday: true },
  { label: '30分', value: '30m', frequency: '30', intraday: true },
  { label: '60分', value: '60m', frequency: '60', intraday: true },
  { label: '日K', value: 'day', frequency: 'd', ranges: dailyKlineRanges, defaultRange: 2 },
  { label: '周K', value: 'week', frequency: 'w', ranges: weeklyKlineRanges, defaultRange: 1 },
  { label: '月K', value: 'month', frequency: 'm', ranges: monthlyKlineRanges, defaultRange: 2 },
]
const klineRange = ref(2)
const klineFrequency = ref('day')
const klineLoading = ref(false)
const klineError = ref('')
const indicators = ['MA', 'BOLL', 'MACD', 'KDJ', 'RSI']
const activeIndicator = ref(0)
const detailTabs = ['财务摘要', '估值', '同行对比', '基本信息']
const detailTab = ref(0)
const baselineDailyBars = 240

const peers = ref([])
const peersLoading = ref(false)
async function loadPeers() {
  if (!detail.value?.industry) return
  peersLoading.value = true
  try {
    const data = await screenerApi.screen(
      [{ field: 'industry', op: 'eq', value: detail.value.industry }],
      { sort_by: 'market_cap', sort_desc: true, limit: 12 },
    )
    peers.value = data.items || []
  } catch {
    peers.value = []
  } finally {
    peersLoading.value = false
  }
}
watch(() => detail.value?.industry, (v) => { if (v) loadPeers() })
watch(detailTab, (v) => { if (v === 2 && !peers.value.length) loadPeers() })


function dayTime(day) {
  const [year, month, date] = String(day || '').split('-').map(Number)
  if (!year || !month || !date) return Number.NaN
  return new Date(year, month - 1, date).getTime()
}

function isWeekday(day) {
  const time = dayTime(day)
  if (!Number.isFinite(time)) return false
  const weekday = new Date(time).getDay()
  return weekday !== 0 && weekday !== 6
}

function mapKline(real) {
  if (!Array.isArray(real)) return []
  const seen = new Set()
  return real
    .filter((k) => k?.trade_date && isWeekday(k.trade_date))
    .sort((a, b) => dayTime(a.trade_date) - dayTime(b.trade_date))
    .filter((k) => {
      if (seen.has(k.trade_date)) return false
      seen.add(k.trade_date)
      return true
    })
    .map((k) => ({
      o: k.open,
      c: k.close,
      h: k.high,
      l: k.low,
      v: k.volume,
      day: k.trade_date,
    }))
}

function mapIntradayKline(real) {
  if (!Array.isArray(real)) return []
  const seen = new Set()
  return real
    .filter((k) => k?.datetime)
    .sort((a, b) => new Date(a.datetime).getTime() - new Date(b.datetime).getTime())
    .filter((k) => {
      if (seen.has(k.datetime)) return false
      seen.add(k.datetime)
      return true
    })
    .map((k) => ({
      o: k.open,
      c: k.close,
      h: k.high,
      l: k.low,
      v: k.volume,
      datetime: k.datetime,
    }))
}

const isIntradayFrequency = computed(() => klineFrequencies.find((x) => x.value === klineFrequency.value)?.intraday === true)
const activeKlineFrequency = computed(() => klineFrequencies.find((x) => x.value === klineFrequency.value) || klineFrequencies[4])
const activeKlineRanges = computed(() => {
  if (isIntradayFrequency.value) return intradayKlineRanges
  return activeKlineFrequency.value.ranges || dailyKlineRanges
})
const klineData = computed(() => isIntradayFrequency.value
  ? rawKlineData.value
  : rawPeriodKlineData.value)
const chartDisplayData = computed(() => klineData.value)
const klineVisibleBars = computed(() => {
  const count = chartDisplayData.value.length
  if (count <= 10) return 18
  if (isIntradayFrequency.value) {
    if (klineFrequency.value === '5m') return 96
    if (klineFrequency.value === '15m') return 80
    if (klineFrequency.value === '30m') return 70
    return 60
  }
  if (count <= 35) return 35
  if (klineFrequency.value === 'month') return 48
  if (klineFrequency.value === 'week') return 64
  return 90
})
const klineCaption = computed(() => {
  const range = activeKlineRanges.value[klineRange.value]?.label || ''
  const freq = activeKlineFrequency.value?.label || '日K'
  return `${freq} · ${range} · ${isIntradayFrequency.value ? '不复权' : '前复权'}`
})
const klineDataType = computed(() => {
  if (isIntradayFrequency.value) return '分钟K：盘中分时蜡烛，来自 baostock 分钟线，不用日线替代。'
  if (klineFrequency.value === 'week') return '周K：每根蜡烛代表一个交易周，直接请求周线数据。'
  if (klineFrequency.value === 'month') return '月K：每根蜡烛代表一个交易月，直接请求月线数据。'
  return '日K：每根蜡烛代表一个交易日，不是 24 小时分时。'
})
const klineEmptyText = computed(() => {
  if (klineLoading.value) return ''
  if (klineError.value) return '当前周期数据加载失败'
  if (isIntradayFrequency.value) return '当前分钟 K 暂无数据；系统不会用日线伪装分钟线。'
  return '当前周期暂无 K 线数据'
})
const klineStats = computed(() => {
  const data = chartDisplayData.value || []
  if (!data.length) return []
  const first = data[0]
  const last = data[data.length - 1]
  const highs = data.map((item) => Number(item.h)).filter(Number.isFinite)
  const lows = data.map((item) => Number(item.l)).filter(Number.isFinite)
  const volumes = data.map((item) => Number(item.v)).filter(Number.isFinite)
  const high = highs.length ? Math.max(...highs) : null
  const low = lows.length ? Math.min(...lows) : null
  const volume = volumes.length ? volumes[volumes.length - 1] : null
  const timeKey = isIntradayFrequency.value ? 'datetime' : 'day'
  return [
    { label: '样本', value: `${data.length}根` },
    { label: '起始', value: formatKlineTime(first?.[timeKey]) },
    { label: '结束', value: formatKlineTime(last?.[timeKey]) },
    { label: '最新收盘', value: last?.c != null ? Number(last.c).toFixed(2) : '—' },
    { label: '区间高点', value: high != null ? high.toFixed(2) : '—' },
    { label: '区间低点', value: low != null ? low.toFixed(2) : '—' },
    { label: '末根成交量', value: volume != null ? formatCompactVolume(volume) : '—' },
  ]
})

function formatKlineTime(value) {
  if (!value) return '—'
  const raw = String(value)
  if (!raw.includes('T') && !raw.includes(' ')) return raw
  const date = new Date(raw)
  if (!Number.isFinite(date.getTime())) return raw
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatCompactVolume(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(2)}万`
  return n.toFixed(0)
}

async function reloadKline() {
  const days = activeKlineRanges.value[klineRange.value]?.days || activeKlineRanges.value[0].days
  klineLoading.value = true
  klineError.value = ''
  try {
    if (isIntradayFrequency.value) {
      const kl = await stockApi.intraday(code.value, activeKlineFrequency.value.frequency, days)
      rawKlineData.value = mapIntradayKline(kl)
    } else {
      const kl = await stockApi.kline(code.value, days, activeKlineFrequency.value.frequency)
      const mapped = mapKline(kl)
      rawPeriodKlineData.value = mapped
      if (klineFrequency.value === 'day' && (mapped.length >= baselineDailyBars || rawDailyKlineData.value.length < baselineDailyBars)) {
        rawDailyKlineData.value = mapped
      }
    }
  } catch (e) {
    klineError.value = friendlyError(e, { context: 'data' })
    if (isIntradayFrequency.value) rawKlineData.value = []
    else rawPeriodKlineData.value = []
  } finally {
    klineLoading.value = false
  }
}

async function loadQuote() {
  try {
    quote.value = await stockApi.quote(code.value)
  } catch {
    quote.value = null
  }
}

function setKlineRange(value) {
  klineRange.value = Number(value)
  reloadKline()
}

function setKlineFrequency(value) {
  klineFrequency.value = value
  const next = klineFrequencies.find((x) => x.value === value)
  klineRange.value = next?.intraday ? 0 : (next?.defaultRange ?? 0)
  reloadKline()
}

function setIndicator(value) {
  activeIndicator.value = Number(value)
}

function setDetailTab(value) {
  detailTab.value = Number(value)
}

async function load() {
  loading.value = true
  errorMsg.value = ''
  aiText.value = ''
  try {
    const days = activeKlineRanges.value[klineRange.value]?.days || 120
    const [d, dailyKl, q] = await Promise.all([
      stockApi.detail(code.value),
      stockApi.kline(code.value, Math.max(days, baselineDailyBars), 'd').catch(() => []),
      stockApi.quote(code.value).catch(() => null),
    ])
    detail.value = d
    quote.value = q
    rawDailyKlineData.value = mapKline(dailyKl)
    if (isIntradayFrequency.value) await reloadKline()
    else if (klineFrequency.value === 'day') {
      rawKlineData.value = []
      rawPeriodKlineData.value = rawDailyKlineData.value.slice(-days)
    } else {
      rawKlineData.value = []
      await reloadKline()
    }
  } catch (e) {
    const status = e.response?.status
    if (status === 404) {
      errorMsg.value = `未找到股票 ${code.value}，请到行情页或按 ⌘K 搜索其他代码`
    } else {
      errorMsg.value = friendlyError(e, { context: 'data' })
    }
  } finally {
    loading.value = false
  }
}

async function askQwen() {
  if (aiStreaming.value) {
    aiAbort?.abort()
    return
  }
  aiText.value = ''
  aiError.value = ''
  aiLoading.value = true
  aiStreaming.value = true
  aiAbort = new AbortController()

  try {
    await qwenApi.streamAnalyze(code.value, (ev) => {
      if (ev.type === 'chunk' && ev.text) {
        aiLoading.value = false
        aiText.value += ev.text
      } else if (ev.type === 'error') {
        aiError.value = friendlyError(ev.message, { context: 'ai' })
      }
    }, aiAbort.signal)
  } catch (e) {
    if (e.name !== 'AbortError') {
      aiError.value = friendlyError(e, { context: 'ai' })
    }
  } finally {
    aiLoading.value = false
    aiStreaming.value = false
    aiAbort = null
  }
}

onMounted(() => {
  load()
  quoteTimer = setInterval(loadQuote, 30000)
})
onBeforeUnmount(() => {
  if (quoteTimer) clearInterval(quoteTimer)
  aiAbort?.abort()
})
watch(code, load)

const displayQuote = computed(() => quote.value || detail.value?.latest || null)
const change = computed(() => {
  const q = displayQuote.value
  if (!q) return null
  if (q.change != null) return q.change
  const prevClose = q.prev_close ?? detail.value?.prev_close
  if (q.close == null || prevClose == null) return null
  return q.close - prevClose
})
const changePct = computed(() => {
  const q = displayQuote.value
  if (q?.change_pct != null) return q.change_pct
  return detail.value?.change_pct ?? 0
})

const priceColor = computed(() => (change.value != null && change.value >= 0) ? Preview.positive : Preview.negative)

const headerMetrics = computed(() => {
  const l = {
    ...(detail.value?.latest || {}),
    ...(displayQuote.value || {}),
    pe: displayQuote.value?.pe ?? detail.value?.latest?.pe,
    pb: displayQuote.value?.pb ?? detail.value?.latest?.pb,
    market_cap: displayQuote.value?.market_cap ?? detail.value?.latest?.market_cap,
    dividend_yield: detail.value?.latest?.dividend_yield,
  }
  if (!l) return []
  const fmt = (v, d = 2) => v == null ? '—' : Number(v).toFixed(d)
  const fmtPct = (v, d = 2, normalizeFraction = false) => {
    if (v == null) return '—'
    const n = Number(v)
    if (!Number.isFinite(n)) return '—'
    const pct = normalizeFraction && Math.abs(n) > 0 && Math.abs(n) < 1 ? n * 100 : n
    return `${pct.toFixed(d)}%`
  }

  let volRatio = null
  if (rawDailyKlineData.value && rawDailyKlineData.value.length >= 6 && l.volume) {
    const last5 = rawDailyKlineData.value.slice(-6, -1)
    const vols = last5.map((k) => k.v ?? k.volume).filter((v) => v != null && v > 0)
    if (vols.length >= 3) {
      const avg5 = vols.reduce((a, b) => a + b, 0) / vols.length
      if (avg5 > 0) volRatio = l.volume / avg5
    }
  }

  let high52 = null, low52 = null
  if (rawDailyKlineData.value && rawDailyKlineData.value.length) {
    const dailyWindow = rawDailyKlineData.value.slice(-baselineDailyBars)
    high52 = Math.max(...dailyWindow.map((k) => k.h ?? k.high ?? -Infinity))
    low52 = Math.min(...dailyWindow.map((k) => k.l ?? k.low ?? Infinity))
    if (!isFinite(high52)) high52 = null
    if (!isFinite(low52)) low52 = null
  }

  return [
    { l: '今开', v: fmt(l.open) },
    { l: '最高', v: fmt(l.high) },
    { l: '最低', v: fmt(l.low) },
    { l: '市盈率', v: fmt(l.pe) },
    { l: '市净率', v: fmt(l.pb) },
    { l: '总市值', v: l.market_cap != null ? (l.market_cap >= 10000 ? (l.market_cap / 10000).toFixed(2) + '万亿' : Math.round(l.market_cap).toLocaleString() + '亿') : '—' },
    { l: '股息率', v: fmtPct(l.dividend_yield, 2) },
    { l: '换手率', v: fmtPct(l.turnover, 2) },
    { l: '成交量', v: l.volume != null ? (l.volume / 1e8).toFixed(2) + '亿' : '—' },
    { l: '量比', v: volRatio != null ? volRatio.toFixed(2) : '—' },
    { l: '52周高', v: high52 != null ? high52.toFixed(2) : '—' },
    { l: '52周低', v: low52 != null ? low52.toFixed(2) : '—' },
  ]
})

const finRows = computed(() => {
  const d = detail.value
  if (!d) return []
  const fmt = (v, d2 = 2, suf = '') => v == null ? '—' : (v.toFixed(d2) + suf)
  return [
    { l: 'ROE',          v: fmt(d.roe, 2, '%') },
    { l: '营收同比',      v: fmt(d.revenue_yoy, 2, '%') },
    { l: '净利同比',      v: fmt(d.profit_yoy, 2, '%') },
    { l: '毛利率',        v: fmt(d.gross_margin, 2, '%') },
    { l: '资产负债率',    v: fmt(d.debt_ratio, 2, '%') },
    { l: '股息率(TTM)',   v: fmt(d.latest?.dividend_yield, 2, '%') },
  ]
})

const scoreBreakdown = computed(() => {
  const d = detail.value
  if (!d) return []
  const l = d.latest || {}
  const peScore = l.pe && l.pe > 0
    ? Math.round(Math.max(20, Math.min(100, 110 - l.pe * 4)))
    : 60
  const roeScore = d.roe != null
    ? Math.round(Math.max(20, Math.min(100, 40 + d.roe * 4)))
    : 60
  const growth = ((d.revenue_yoy || 0) + (d.profit_yoy || 0)) / 2
  const growthScore = Math.round(Math.max(20, Math.min(100, 60 + growth * 1.5)))
  const divScore = l.dividend_yield != null
    ? Math.round(Math.max(20, Math.min(100, 50 + l.dividend_yield * 8)))
    : 50
  return [
    { l: '估值', v: peScore, s: peScore > 60 ? 'success' : 'warning' },
    { l: '盈利', v: roeScore, s: roeScore > 60 ? 'success' : 'warning' },
    { l: '成长', v: growthScore, s: growthScore > 60 ? 'success' : 'warning' },
    { l: '分红', v: divScore, s: divScore > 60 ? 'success' : 'warning' },
  ]
})

const bullScore = computed(() => {
  if (!detail.value) return 0
  const { latest, roe } = detail.value
  let s = 60
  if (latest?.pe && latest.pe > 0) s += Math.max(0, Math.min(20, 25 - latest.pe * 0.5))
  if (latest?.dividend_yield) s += Math.min(15, latest.dividend_yield * 2)
  if (roe) s += Math.min(15, roe)
  return Math.round(Math.max(0, Math.min(99, s)))
})

const scoreLabel = computed(() => {
  if (bullScore.value >= 80) return '强烈关注'
  if (bullScore.value >= 60) return '可关注'
  if (bullScore.value >= 40) return '中性'
  return '谨慎'
})

const scoreColor = computed(() => {
  if (bullScore.value >= 80) return Preview.brand
  if (bullScore.value >= 60) return '#2563EB'
  if (bullScore.value >= 40) return '#f0a020'
  return '#D64545'
})

const market = computed(() => {
  const c = code.value || ''
  if (c.startsWith('688')) return '科创板'
  if (c.startsWith('300') || c.startsWith('301')) return '创业板'
  if (c.endsWith('.BJ')) return '北交所'
  return '主板'
})

const aiHtml = computed(() => {
  if (!aiText.value) return ''
  return marked.parse(aiText.value)
})

const valuationCells = computed(() => {
  const l = detail.value?.latest
  if (!l) return []
  const fmt = (v, d = 2, suf = '') => v == null ? '—' : v.toFixed(d) + suf
  return [
    { l: '市盈率 PE', v: fmt(l.pe), s: l.pe == null || l.pe <= 0 ? '—' : (l.pe < 15 ? '低估区' : l.pe < 30 ? '合理' : '偏高') },
    { l: '市净率 PB', v: fmt(l.pb), s: l.pb == null ? '—' : (l.pb < 1.5 ? '破净 / 低 PB' : l.pb < 3 ? '合理' : '偏高') },
    { l: '股息率 TTM', v: fmt(l.dividend_yield, 2, '%'), s: l.dividend_yield == null ? '—' : (l.dividend_yield > 4 ? '高股息' : l.dividend_yield > 2 ? '一般' : '偏低') },
    { l: '总市值', v: l.market_cap == null ? '—' : Math.round(l.market_cap).toLocaleString(), s: l.market_cap == null ? '—' : (l.market_cap > 1000 ? '大盘股' : l.market_cap > 100 ? '中盘股' : '小盘股') },
  ]
})

const fmtPeer = (v, d = 2) => v != null ? Number(v).toFixed(d) : '—'
const peerColumns = computed(() => [
  {
    title: '名称', key: 'name', minWidth: 120,
    render: (p) => h('div', { style: { display: 'flex', alignItems: 'center', gap: '6px', fontWeight: p.code === detail.value?.code ? 700 : 600 } }, [
      h('span', p.name),
      p.code === detail.value?.code
        ? h(NTag, { size: 'tiny', type: 'info', bordered: false }, { default: () => '本股' })
        : null,
    ]),
  },
  { title: '代码', key: 'code', width: 96, render: (p) => h('span', { style: { fontFamily: 'IBM Plex Mono, monospace', color: Preview.textMuted, fontSize: '10.5px' } }, p.code) },
  { title: '现价', key: 'close', align: 'right', width: 78, render: (p) => h('span', { style: { fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700 } }, fmtPeer(p.close)) },
  { title: 'PE', key: 'pe', align: 'right', width: 70, render: (p) => h('span', { style: { fontFamily: 'IBM Plex Mono, monospace' } }, p.pe != null && p.pe > 0 ? p.pe.toFixed(2) : '—') },
  { title: 'PB', key: 'pb', align: 'right', width: 70, render: (p) => h('span', { style: { fontFamily: 'IBM Plex Mono, monospace' } }, fmtPeer(p.pb)) },
  {
    title: 'ROE', key: 'roe', align: 'right', width: 78,
    render: (p) => h('span', { style: { fontFamily: 'IBM Plex Mono, monospace', fontWeight: p.roe > 10 ? 700 : 500 } }, p.roe != null ? `${p.roe.toFixed(2)}%` : '—'),
  },
  {
    title: '股息率', key: 'dividend_yield', align: 'right', width: 86,
    render: (p) => h('span', { style: { fontFamily: 'IBM Plex Mono, monospace' } }, p.dividend_yield != null ? `${p.dividend_yield.toFixed(2)}%` : '—'),
  },
  {
    title: '总市值', key: 'market_cap', align: 'right', width: 104,
    render: (p) => h('span', { style: { fontFamily: 'IBM Plex Mono, monospace' } }, `${p.market_cap != null ? Math.round(p.market_cap).toLocaleString() : '—'}亿`),
  },
])

function peerRowProps(row) {
  return {
    style: 'cursor: pointer;',
    onClick: () => router.push(`/detail/${row.code}`),
  }
}
</script>

<template>
  <Shell>
    <!-- Loading -->
    <div v-if="loading && !detail" class="detail-loading">
      <NSpin size="large">
        <NCard :bordered="false" style="width: min(800px, 100%);">
          <NSpace vertical size="large">
            <NSpace align="center">
              <NSkeleton text :width="120" :sharp="false" />
              <NSkeleton text :width="80" :sharp="false" />
              <NSkeleton text :width="180" :sharp="false" />
            </NSpace>
            <NSkeleton height="430px" :sharp="false" />
          </NSpace>
        </NCard>
      </NSpin>
    </div>

    <!-- Error -->
    <div v-else-if="errorMsg" style="display:grid; place-items:center; min-height:400px;">
      <NResult status="error" title="无法加载股票详情" :description="errorMsg">
        <template #footer>
          <NSpace justify="center">
            <NButton @click="$router.push('/dashboard')">回到行情</NButton>
            <NButton type="primary" @click="load">
              <template #icon><Icon name="refresh" :size="12" /></template>
              重试
            </NButton>
          </NSpace>
        </template>
      </NResult>
    </div>

    <!-- Content -->
    <div v-else-if="detail" class="detail-page">
      <!-- Stock Header Bar -->
      <div class="stock-header">
        <div class="stock-header-left">
          <span class="stock-code">{{ code }}</span>
          <h2 class="stock-name">{{ detail.name }}</h2>
          <NTag size="small" :bordered="false">{{ detail.industry || '—' }}</NTag>
          <NTag size="small" :bordered="false" type="default">{{ market }}</NTag>
          <div class="stock-price-inline">
            <span class="price-big" :style="{ color: priceColor }">
              {{ displayQuote?.close?.toFixed(2) || '—' }}
            </span>
            <span v-if="change != null" class="price-delta" :style="{ color: priceColor }">
              {{ change >= 0 ? '+' : '' }}{{ change.toFixed(2) }}
            </span>
            <NTag v-if="changePct" :type="changePct >= 0 ? 'error' : 'success'" size="small" :bordered="false">
              {{ changePct >= 0 ? '+' : '' }}{{ changePct.toFixed(2) }}%
            </NTag>
          </div>
        </div>
        <div class="stock-header-right">
          <NSpace size="small">
            <StarButton variant="button" :stock="{ code: detail.code, name: detail.name, sector: detail.industry, refPrice: displayQuote?.close || detail.latest?.close }" :size="12" />
            <AlertRuleEditor v-if="wl.has(detail.code)" :code="detail.code" />
            <NButton
              size="small"
              :type="aiStreaming ? 'default' : 'primary'"
              :disabled="!aiStreaming && !aiStatus.isUp"
              @click="askQwen"
            >
              <template #icon>
                <Icon :name="aiStreaming ? 'x' : 'sparkle'" :size="12" />
              </template>
              {{ aiStreaming ? '停止' : (!aiStatus.isUp ? '千问离线' : (aiText ? '重新生成' : '千问解读')) }}
            </NButton>
          </NSpace>
        </div>
      </div>

      <!-- Main: K-line (wide) + Sidebar -->
      <div class="detail-main">
        <div class="detail-left">
          <!-- K-line Card -->
          <NCard class="section-card chart-card" size="small">
            <template #header>
              <div class="chart-header">
                <div>
                  <strong>K 线走势</strong>
                  <span class="chart-sub">{{ klineCaption }}</span>
                </div>
              </div>
            </template>
            <div class="chart-toolbar">
              <div class="kline-control-group">
                <span>周期</span>
                <NButtonGroup size="tiny">
                  <NButton
                    v-for="t in klineFrequencies"
                    :key="t.value"
                    :type="klineFrequency === t.value ? 'primary' : 'default'"
                    secondary
                    @click="setKlineFrequency(t.value)"
                  >
                    {{ t.label }}
                  </NButton>
                </NButtonGroup>
              </div>
              <div class="kline-control-group">
                <span>区间</span>
                <NButtonGroup size="tiny" class="range-buttons">
                  <NButton
                    v-for="(t, i) in activeKlineRanges"
                    :key="t.label"
                    :type="klineRange === i ? 'primary' : 'default'"
                    secondary
                    @click="setKlineRange(i)"
                  >
                    {{ t.short }}
                  </NButton>
                </NButtonGroup>
              </div>
              <div class="kline-control-group indicator-group">
                <span>指标</span>
                <NButtonGroup size="tiny">
                  <NButton
                    v-for="(t, i) in indicators"
                    :key="t"
                    :type="activeIndicator === i ? 'primary' : 'default'"
                    secondary
                    @click="setIndicator(i)"
                  >
                    {{ t }}
                  </NButton>
                </NButtonGroup>
              </div>
            </div>
            <div class="kline-meta">
              <span class="kline-mode">{{ klineDataType }}</span>
              <span
                v-for="item in klineStats"
                :key="item.label"
                class="kline-stat"
              >
                {{ item.label }} <strong>{{ item.value }}</strong>
              </span>
            </div>
            <NAlert v-if="klineError" type="warning" :bordered="false" class="kline-error">
              {{ klineError }}
            </NAlert>
            <NSpin :show="klineLoading">
              <KLineChart
                v-if="chartDisplayData.length"
                :data="chartDisplayData"
                :height="390"
                :indicator="indicators[activeIndicator]"
                :visible-bars="klineVisibleBars"
                :period="klineFrequency"
              />
              <div v-else class="kline-empty">
                <EmptyState icon="chart" title="暂无 K 线数据" :subtitle="klineEmptyText" compact />
              </div>
            </NSpin>
          </NCard>

          <!-- Key Stats Ribbon -->
          <div class="stats-ribbon">
            <div v-for="(m, i) in headerMetrics" :key="i" class="stat-cell">
              <span class="stat-label">{{ m.l }}</span>
              <strong class="stat-num">{{ m.v }}</strong>
            </div>
          </div>

          <!-- Tabs + Content -->
          <NCard class="section-card" size="small" style="margin-top:12px;">
            <template #header>
              <NTabs :value="detailTab" type="line" size="small" animated @update:value="setDetailTab">
                <NTabPane v-for="(t, i) in detailTabs" :key="t" :name="i" :tab="t" />
              </NTabs>
            </template>

            <!-- 财务摘要 -->
            <div v-if="detailTab === 0">
              <NDescriptions :column="3" size="small" label-placement="top" bordered>
                <NDescriptionsItem v-for="r in finRows" :key="r.l" :label="r.l">
                  <span class="mono-bold">{{ r.v }}</span>
                </NDescriptionsItem>
              </NDescriptions>
            </div>

            <!-- 估值 -->
            <div v-else-if="detailTab === 1">
              <NGrid :cols="4" :x-gap="10">
                <NGi v-for="m in valuationCells" :key="m.l">
                  <NCard size="small" embedded>
                    <NStatistic :label="m.l" :value="m.v" />
                    <NTag size="small" :bordered="false">{{ m.s }}</NTag>
                  </NCard>
                </NGi>
              </NGrid>
            </div>

            <!-- 同行对比 -->
            <div v-else-if="detailTab === 2">
              <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;">
                <span style="font-size:12px; font-weight:700;">同行对比 · {{ detail.industry || '—' }}</span>
                <span v-if="peers.length" style="font-size:10.5px; color:#64748B;">前 {{ peers.length }} 只</span>
              </div>
              <div v-if="peersLoading" style="display:flex; flex-direction:column; gap:6px;">
                <NSkeleton v-for="n in 5" :key="n" height="28px" :sharp="false" />
              </div>
              <NDataTable
                v-else-if="peers.length"
                :columns="peerColumns"
                :data="peers"
                :row-key="(row) => row.code"
                :row-props="peerRowProps"
                :pagination="false"
                size="small"
                :bordered="false"
              />
              <EmptyState v-else icon="chart" title="暂无同行数据" subtitle="该行业暂无其他可比公司" compact />
            </div>

            <!-- 基本信息 -->
            <div v-else>
              <NDescriptions :column="2" size="small" bordered>
                <NDescriptionsItem label="股票代码"><span class="mono-bold">{{ detail.code }}</span></NDescriptionsItem>
                <NDescriptionsItem label="股票名称">{{ detail.name }}</NDescriptionsItem>
                <NDescriptionsItem label="所属行业">{{ detail.industry || '—' }}</NDescriptionsItem>
                <NDescriptionsItem label="上市板块">{{ market }}</NDescriptionsItem>
                <NDescriptionsItem label="最新交易日"><span style="font-family:'IBM Plex Mono', monospace;">{{ detail.latest?.trade_date || '—' }}</span></NDescriptionsItem>
                <NDescriptionsItem label="货币单位">人民币 CNY</NDescriptionsItem>
              </NDescriptions>
            </div>
          </NCard>

          <!-- AI Analysis Card -->
          <NCard title="千问解读" size="small" class="section-card ai-card-wide">
            <template #header-extra>
              <NSpace size="small" align="center">
                <NTag size="small" :bordered="false">基本面摘要</NTag>
                <NButton v-if="aiText && !aiStreaming" text size="tiny" type="primary" @click="askQwen">重新生成</NButton>
              </NSpace>
            </template>

            <NAlert v-if="!aiText && !aiLoading && !aiStreaming && !aiError" type="default" :bordered="false" class="ai-empty">
              点击顶部「千问解读」按钮，生成估值、盈利质量、成长和风险摘要。
            </NAlert>

            <div v-if="aiLoading && !aiText" class="ai-thinking">
              <NSpin size="small" /> 正在分析当前行情和财务指标...
            </div>

            <NAlert v-if="aiError" type="error" :bordered="false">
              <span>{{ aiError }}</span>
              <NButton size="tiny" secondary @click="askQwen" style="margin-top:6px;">重试</NButton>
            </NAlert>

            <div v-if="aiText" class="ai-md">
              <div v-html="aiHtml" />
              <span v-if="aiStreaming" class="caret" />
            </div>
          </NCard>
        </div>

        <!-- Sidebar -->
        <div class="detail-right">
          <!-- Score Card -->
          <NCard title="综合评分" size="small" class="section-card">
            <div class="score-block">
              <div class="score-ring" :style="{ color: scoreColor, borderColor: scoreColor }">
                {{ bullScore }}
              </div>
              <div class="score-text">
                <div class="score-label" :style="{ color: scoreColor }">{{ scoreLabel }}</div>
                <div class="score-sub">{{ bullScore }}/99</div>
              </div>
            </div>
            <div class="score-bars">
              <div v-for="d in scoreBreakdown" :key="d.l" class="score-bar-item">
                <div class="score-bar-head">
                  <span>{{ d.l }}</span>
                  <strong>{{ d.v }}</strong>
                </div>
                <NProgress
                  type="line"
                  :percentage="d.v"
                  :height="6"
                  :show-indicator="false"
                  :status="d.s"
                />
              </div>
            </div>
          </NCard>

          <!-- Stock Info Card -->
          <NCard title="股票信息" size="small" class="section-card">
            <NDescriptions :column="1" label-placement="left" size="small">
              <NDescriptionsItem label="代码">{{ code }}</NDescriptionsItem>
              <NDescriptionsItem label="行业">{{ detail.industry || '—' }}</NDescriptionsItem>
              <NDescriptionsItem label="板块">{{ market }}</NDescriptionsItem>
              <NDescriptionsItem label="交易日">{{ detail.latest?.trade_date || '—' }}</NDescriptionsItem>
            </NDescriptions>
            <NButton block type="primary" size="small" :loading="loading" style="margin-top:12px;" @click="load">
              <template #icon><Icon name="refresh" :size="12" /></template>
              刷新数据
            </NButton>
          </NCard>

          <NAlert type="warning" :bordered="false" class="risk-note">
            <template #icon><Icon name="shield" :size="11" /></template>
            仅供研究参考，不构成投资建议
          </NAlert>
        </div>
      </div>
    </div>
  </Shell>
</template>

<style scoped>
.detail-page {
  color: #111111;
  padding-top: 0;
}

.detail-loading {
  display: grid;
  place-items: center;
  padding: 60px 0;
}

/* ---- Stock Header ---- */
.stock-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 0 0 12px;
  background: #FFFFFF;
  border: 0;
  border-radius: 0;
  margin-bottom: 0;
  box-shadow: none;
}

.stock-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  max-width: 820px;
}

.stock-code {
  font-size: 12px;
  font-family: 'IBM Plex Mono', monospace;
  color: #71717A;
  order: 1;
}

.stock-name {
  margin: 0;
  font-size: 22px;
  font-weight: 800;
  color: #111111;
  line-height: 1;
  order: 0;
}

.stock-header :deep(.n-tag) {
  background: #F5F5F5;
  color: #52525B;
  border-radius: 4px;
  order: 2;
}

.stock-price-inline {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-left: 0;
  width: 100%;
  order: 3;
  padding-top: 8px;
}

.price-big {
  font-size: 46px;
  font-weight: 800;
  font-family: 'IBM Plex Mono', monospace;
  line-height: 0.95;
  letter-spacing: 0;
}

.price-delta {
  font-size: 15px;
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 700;
}

.stock-header-right {
  flex-shrink: 0;
}

/* ---- Main Layout ---- */
.detail-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 16px;
  align-items: start;
}

.detail-left {
  min-width: 0;
}

.detail-right {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-card {
  background: #F7F7F7;
  border: 0;
  border-radius: 8px;
  box-shadow: none;
  overflow: hidden;
}

/* ---- K-line ---- */
.chart-card {
  border-top: 0;
}

.chart-card :deep(.n-card-header) {
  padding: 12px 16px 0;
  gap: 8px;
}

.chart-card :deep(.n-card__content) {
  padding: 6px 16px 14px;
}

.chart-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chart-header strong {
  font-size: 16px;
  color: #111111;
}

.chart-sub {
  font-size: 11px;
  color: #71717A;
  margin-left: 10px;
}

.chart-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
  padding: 6px 0;
  border-top: 1px solid #ECEFF3;
  border-bottom: 1px solid #ECEFF3;
}

.chart-toolbar :deep(.n-button) {
  --n-height: 24px !important;
  border-radius: 4px;
}

.kline-meta {
  min-height: 28px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 6px;
  padding: 5px 0;
  border-bottom: 1px solid #ECEFF3;
}

.kline-mode,
.kline-stat {
  font-size: 10.5px;
  color: #71717A;
  line-height: 1.4;
}

.kline-mode {
  flex-basis: 100%;
  color: #52525B;
}

.kline-stat {
  padding: 2px 6px;
  border: 1px solid #E5E7EB;
  border-radius: 4px;
  background: #FFFFFF;
}

.kline-stat strong {
  margin-left: 3px;
  color: #111111;
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 700;
}

.kline-error {
  margin-bottom: 8px;
  font-size: 12px;
}

.kline-empty {
  height: 390px;
  display: grid;
  place-items: center;
  border: 1px solid #EDEDED;
  border-radius: 6px;
  background: #FFFFFF;
}

.kline-control-group {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.kline-control-group > span {
  color: #71717A;
  font-size: 11px;
  font-weight: 650;
  flex-shrink: 0;
}

.kline-control-group :deep(.n-button-group) {
  flex-wrap: wrap;
}

.kline-control-group :deep(.n-button) {
  min-width: 36px;
}

.indicator-group {
  margin-left: auto;
}

/* ---- Stats Ribbon ---- */
.stats-ribbon {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 8px;
  margin-top: 8px;
}

.stat-cell {
  padding: 8px 10px;
  background: #F7F7F7;
  border: 0;
  border-radius: 6px;
  text-align: left;
}

.stat-label {
  display: block;
  font-size: 10px;
  color: #71717A;
  margin-bottom: 3px;
}

.stat-num {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 13px;
  color: #111111;
  font-weight: 700;
  white-space: nowrap;
}

/* ---- Score ---- */
.score-block {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.score-ring {
  width: 58px;
  height: 58px;
  border-radius: 50%;
  border: 2px solid;
  display: grid;
  place-items: center;
  font-size: 20px;
  font-weight: 800;
  font-family: 'IBM Plex Mono', monospace;
  flex-shrink: 0;
}

.score-text { flex: 1; }
.score-label { font-size: 14px; font-weight: 800; }
.score-sub { font-size: 11px; color: #71717A; margin-top: 1px; }

.score-bars {
  /* inside score card */
}

.score-bar-item {
  margin-bottom: 7px;
}

.score-bar-item:last-child {
  margin-bottom: 0;
}

.score-bar-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 3px;
  font-size: 11px;
}

.score-bar-head strong {
  font-family: 'IBM Plex Mono', monospace;
  color: #1F2937;
}

/* ---- AI ---- */
.ai-empty {
  font-size: 12px;
  background: #FFFFFF;
}

.ai-card-wide {
  margin-top: 12px;
}

.ai-thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  color: #71717A;
  font-size: 12px;
}

.risk-note {
  font-size: 11px;
  background: #F7F7F7;
}

.mono-bold {
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 700;
}

/* ---- AI markdown ---- */
.ai-md :deep(h1),
.ai-md :deep(h2),
.ai-md :deep(h3) {
  font-size: 13px;
  font-weight: 700;
  margin: 10px 0 5px;
  color: #111111;
}
.ai-md :deep(h1):first-child,
.ai-md :deep(h2):first-child,
.ai-md :deep(h3):first-child { margin-top: 0; }
.ai-md :deep(p) { margin: 5px 0; line-height: 1.7; font-size: 12px; }
.ai-md :deep(p):first-child { margin-top: 0; }
.ai-md :deep(p):last-child { margin-bottom: 0; }
.ai-md :deep(strong) { color: #111111; font-weight: 700; }
.ai-md :deep(em) { color: #3F3F46; font-style: normal; font-weight: 600; }
.ai-md :deep(ul),
.ai-md :deep(ol) { padding-left: 16px; margin: 5px 0; }
.ai-md :deep(li) { margin: 2px 0; line-height: 1.6; font-size: 12px; }
.ai-md :deep(code) {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  padding: 1px 4px;
  background: #FFFFFF;
  border-radius: 3px;
}
.ai-md :deep(blockquote) {
  margin: 6px 0;
  padding: 4px 10px;
  border-left: 3px solid #111111;
  color: #3F3F46;
  background: #FFFFFF;
  border-radius: 0 4px 4px 0;
}

.caret {
  display: inline-block;
  width: 6px;
  height: 14px;
  margin-left: 2px;
  background: #111111;
  vertical-align: middle;
  animation: caret-blink 1s steps(2) infinite;
}
@keyframes caret-blink { 50% { opacity: 0 } }

@media (max-width: 900px) {
  .chart-card :deep(.n-card-header) {
    flex-wrap: wrap;
  }

  .kline-control-group {
    width: 100%;
    justify-content: flex-start;
  }

  .kline-control-group :deep(.n-button-group) {
    flex: 1;
    min-width: 0;
  }

  .indicator-group {
    margin-left: 0;
  }

  .chart-toolbar {
    justify-content: flex-start;
    overflow-x: auto;
    padding-bottom: 2px;
  }

  .detail-main {
    grid-template-columns: 1fr;
  }

  .stats-ribbon {
    grid-template-columns: repeat(3, 1fr);
  }
}
</style>
