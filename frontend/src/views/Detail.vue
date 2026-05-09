<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import PctChip from '../components/charts/PctChip.vue'
import Donut from '../components/charts/Donut.vue'
import FullCandle from '../components/charts/FullCandle.vue'
import { A2 } from '../shared/theme.js'
import * as stockApi from '../api/stock'
import * as qwenApi from '../api/qwen'
import * as screenerApi from '../api/screener'
import EmptyState from '../components/EmptyState.vue'
import { useAiStatusStore } from '../stores/aiStatus'

const aiStatus = useAiStatusStore()
import { marked } from 'marked'
import { friendlyError } from '../shared/errors.js'

// marked: 紧凑配置（不允许原始 HTML，禁用 mangle，保留 GFM 列表/粗体）
marked.setOptions({ breaks: true, gfm: true })
import StarButton from '../components/StarButton.vue'
import AlertRuleEditor from '../components/AlertRuleEditor.vue'
import Skeleton from '../components/Skeleton.vue'
import { useWatchlistStore } from '../stores/watchlist'

const wl = useWatchlistStore()

const route = useRoute()

// 默认显示茅台（如果路由没带 code）
const code = computed(() => route.params.code || '600519.SH')

const detail = ref(null)
const klineData = ref([])
const loading = ref(true)
const errorMsg = ref('')

// 千问分析（按需，流式）
const aiText = ref('')
const aiLoading = ref(false)
const aiStreaming = ref(false)
const aiError = ref('')
let aiAbort = null

// K 线采样周期：用 days 参数控制后端取多少个交易日
// 因为现阶段 DB 是日级粒度（无分时），分时改成"近 5 天"，季 K 改成"两年"
const klineTabs = [
  { label: '5日',  days: 5 },
  { label: '30日', days: 30 },
  { label: '日K',  days: 80 },
  { label: '半年', days: 120 },
  { label: '一年', days: 240 },
  { label: '两年', days: 480 },
]
const klinePeriod = ref(2)   // 默认 "日K"
const indicators = ['MA', 'BOLL', 'MACD', 'KDJ', 'RSI']
const activeIndicator = ref(0)   // MA 默认开；其他纯标签
const detailTabs = ['财务摘要', '估值', '同行对比', '基本信息']
const detailTab = ref(0)

// 同行（同行业）数据
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


function mapKline(real) {
  if (!Array.isArray(real)) return []
  return real.map((k) => ({
    o: k.open, c: k.close, h: k.high, l: k.low, v: k.volume, day: k.trade_date,
  }))
}

async function reloadKline() {
  const days = klineTabs[klinePeriod.value].days
  try {
    const kl = await stockApi.kline(code.value, days)
    const real = Array.isArray(kl) ? [...kl].reverse() : []
    klineData.value = mapKline(real)
  } catch {
    klineData.value = []
  }
}

async function load() {
  loading.value = true
  errorMsg.value = ''
  aiText.value = ''
  try {
    const days = klineTabs[klinePeriod.value].days
    const [d, kl] = await Promise.all([
      stockApi.detail(code.value),
      stockApi.kline(code.value, days).catch(() => []),
    ])
    detail.value = d
    const real = Array.isArray(kl) ? [...kl].reverse() : []
    klineData.value = mapKline(real)
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
  // 复点同一按钮：正在跑就取消
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
        // 第一个 chunk 到达即视为开始 streaming，关掉"思考中"占位
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

onMounted(load)
watch(code, load)

// 涨跌：用今开 vs 现价近似
const change = computed(() => {
  const l = detail.value?.latest
  if (!l || l.close == null || l.open == null) return null
  return l.close - l.open
})
const changePct = computed(() => {
  const l = detail.value?.latest
  if (!l || l.close == null || l.open == null || l.open === 0) return 0
  return ((l.close - l.open) / l.open) * 100
})

// header 指标（密集版：分两行 8+8）
const headerMetrics = computed(() => {
  const l = detail.value?.latest
  if (!l) return []
  const fmt = (v, d = 2) => v == null ? '—' : Number(v).toFixed(d)
  // 振幅 = (high - low) / open
  const amp = l.open > 0 && l.high != null && l.low != null ? ((l.high - l.low) / l.open) * 100 : null
  // 量比 = 当日量 / 过去 5 日均量；只在 K 线 ≥ 6 个交易日时计算，否则 null
  let volRatio = null
  if (klineData.value && klineData.value.length >= 6 && l.volume) {
    const last5 = klineData.value.slice(-6, -1)  // 倒数第 2 到第 6 共 5 根（不含当日）
    const vols = last5.map((k) => k.v ?? k.volume).filter((v) => v != null && v > 0)
    if (vols.length >= 3) {
      const avg5 = vols.reduce((a, b) => a + b, 0) / vols.length
      if (avg5 > 0) volRatio = l.volume / avg5
    }
  }
  // 52 周高/低：从 K 线序列里提取（如果加载完成）
  let high52 = null, low52 = null
  if (klineData.value && klineData.value.length) {
    high52 = Math.max(...klineData.value.map((k) => k.h ?? k.high ?? -Infinity))
    low52 = Math.min(...klineData.value.map((k) => k.l ?? k.low ?? Infinity))
    if (!isFinite(high52)) high52 = null
    if (!isFinite(low52)) low52 = null
  }
  // 流通市值：当前没字段，用总市值代替
  const floatCap = l.market_cap

  return [
    { l: '今开', v: fmt(l.open), c: A2.text },
    { l: '最高', v: fmt(l.high), c: l.open != null && l.high > l.open ? A2.up : A2.text },
    { l: '最低', v: fmt(l.low), c: l.open != null && l.low < l.open ? A2.down : A2.text },
    { l: '振幅', v: amp != null ? amp.toFixed(2) + '%' : '—', c: A2.text },
    { l: '成交量', v: l.volume != null ? (l.volume / 1e8).toFixed(2) + '亿' : '—', c: A2.text },
    { l: '成交额', v: l.amount != null ? (l.amount / 1e8).toFixed(2) + '亿' : (l.volume != null && l.close != null ? (l.volume * l.close / 1e8).toFixed(2) + '亿' : '—'), c: A2.text },
    { l: '换手率', v: fmt(l.turnover) + '%', c: A2.text },
    { l: '量比', v: volRatio != null ? volRatio.toFixed(2) : '—', c: A2.text },
    // 第二行
    { l: '市盈率', v: fmt(l.pe), c: A2.text },
    { l: '市净率', v: fmt(l.pb), c: A2.text },
    { l: '总市值', v: l.market_cap != null ? Math.round(l.market_cap).toLocaleString() + '亿' : '—', c: A2.text },
    { l: '流通市值', v: floatCap != null ? Math.round(floatCap).toLocaleString() + '亿' : '—', c: A2.text },
    { l: '52周高', v: high52 != null ? high52.toFixed(2) : '—', c: A2.up },
    { l: '52周低', v: low52 != null ? low52.toFixed(2) : '—', c: A2.down },
    { l: '股息率', v: fmt(l.dividend_yield) + '%', c: l.dividend_yield > 4 ? A2.up : A2.text },
    { l: '所属', v: detail.value?.industry || '—', c: A2.qwen, isText: true },
  ]
})

// 财务表
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

// 子维度（每项 0-100）
const scoreBreakdown = computed(() => {
  const d = detail.value
  if (!d) return []
  const l = d.latest || {}
  // 估值得分：PE 越低越好（参考 < 10 满分），PB 辅助
  const peScore = l.pe && l.pe > 0
    ? Math.round(Math.max(20, Math.min(100, 110 - l.pe * 4)))
    : 60
  // 盈利得分：ROE 主导
  const roeScore = d.roe != null
    ? Math.round(Math.max(20, Math.min(100, 40 + d.roe * 4)))
    : 60
  // 成长得分：营收+净利同比
  const growth = ((d.revenue_yoy || 0) + (d.profit_yoy || 0)) / 2
  const growthScore = Math.round(Math.max(20, Math.min(100, 60 + growth * 1.5)))
  // 现金流 / 分红
  const divScore = l.dividend_yield != null
    ? Math.round(Math.max(20, Math.min(100, 50 + l.dividend_yield * 8)))
    : 50
  return [
    { l: '估值', v: peScore },
    { l: '盈利', v: roeScore },
    { l: '成长', v: growthScore },
    { l: '分红', v: divScore },
  ]
})

// 综合评分（同 Results 的逻辑）
const bullScore = computed(() => {
  if (!detail.value) return 0
  const { latest, roe } = detail.value
  let s = 60
  if (latest?.pe && latest.pe > 0) s += Math.max(0, Math.min(20, 25 - latest.pe * 0.5))
  if (latest?.dividend_yield) s += Math.min(15, latest.dividend_yield * 2)
  if (roe) s += Math.min(15, roe)
  return Math.round(Math.max(0, Math.min(99, s)))
})

const market = computed(() => {
  const c = code.value || ''
  if (c.startsWith('688')) return '科创板'
  if (c.startsWith('300') || c.startsWith('301')) return '创业板'
  if (c.endsWith('.BJ')) return '北交所'
  return '主板'
})

// 把 markdown 文本渲染成 HTML；流式中的尾光标用占位符 ▁ 替换为光标 span
const aiHtml = computed(() => {
  if (!aiText.value) return ''
  let html = marked.parse(aiText.value)
  // 简单去掉段落首尾多余空白
  return html
})

const valuationCells = computed(() => {
  const l = detail.value?.latest
  if (!l) return []
  const fmt = (v, d = 2, suf = '') => v == null ? '—' : v.toFixed(d) + suf
  // PE 颜色：< 行业一般水位 红（贵）；中位 灰；> 绿（便宜）—— 简化按区间
  const peTone = l.pe == null || l.pe <= 0 ? A2.text : (l.pe < 15 ? A2.up : (l.pe > 40 ? A2.down : A2.text))
  return [
    { l: '市盈率 PE', v: fmt(l.pe), s: l.pe == null || l.pe <= 0 ? '—' : (l.pe < 15 ? '低估区' : l.pe < 30 ? '合理' : '偏高'), tone: peTone },
    { l: '市净率 PB', v: fmt(l.pb), s: l.pb == null ? '—' : (l.pb < 1.5 ? '破净 / 低 PB' : l.pb < 3 ? '合理' : '偏高'), tone: A2.text },
    { l: '股息率 TTM', v: fmt(l.dividend_yield, 2, '%'), s: l.dividend_yield == null ? '—' : (l.dividend_yield > 4 ? '高股息' : l.dividend_yield > 2 ? '一般' : '偏低'), tone: l.dividend_yield > 4 ? A2.up : A2.text },
    { l: '总市值', v: l.market_cap == null ? '—' : Math.round(l.market_cap).toLocaleString(), s: l.market_cap == null ? '—' : (l.market_cap > 1000 ? '大盘股' : l.market_cap > 100 ? '中盘股' : '小盘股'), tone: A2.text },
  ]
})
</script>

<template>
  <Shell>
    <!-- Loading skeleton -->
    <div v-if="loading && !detail" :style="{ flex: 1, overflow: 'auto' }">
      <div :style="{ background: A2.surface, borderBottom: `1px solid ${A2.borderHair}`, padding: '14px 22px', display: 'flex', flexDirection: 'column', gap: '14px' }">
        <div :style="{ display: 'flex', alignItems: 'center', gap: '14px' }">
          <Skeleton :width="120" :height="28" />
          <Skeleton :width="80" :height="14" />
          <div style="flex:1" />
          <Skeleton :width="180" :height="36" />
          <Skeleton :width="80" :height="22" />
        </div>
        <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: '14px' }">
          <div v-for="n in 8" :key="n">
            <Skeleton :width="40" :height="9" :style="{ marginBottom: '4px' }" />
            <Skeleton :width="60" :height="14" />
          </div>
        </div>
      </div>
      <div :style="{ padding: '24px', display: 'grid', gridTemplateColumns: '1fr 380px', gap: '14px' }">
        <Skeleton :height="380" :rounded="10" />
        <Skeleton :height="380" :rounded="10" />
      </div>
    </div>

    <div v-else-if="errorMsg" :style="{ flex: 1, display: 'grid', placeItems: 'center' }">
      <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, padding: '24px 32px', borderRadius: '12px', fontSize: '13px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px', maxWidth: '460px', textAlign: 'center', boxShadow: A2.shadow }">
        <div :style="{ width: '44px', height: '44px', background: A2.upSoft, color: A2.up, borderRadius: '50%', display: 'grid', placeItems: 'center' }">
          <Icon name="alert" :size="22" />
        </div>
        <div :style="{ fontWeight: 700, fontSize: '14px', color: A2.text }">无法加载股票详情</div>
        <div :style="{ fontSize: '12px', color: A2.textMuted, lineHeight: 1.6 }">{{ errorMsg }}</div>
        <div :style="{ display: 'flex', gap: '8px' }">
          <button class="btn-outline" @click="$router.push('/dashboard')">回到行情</button>
          <button class="btn-primary" @click="load">
            <Icon name="refresh" :size="12" /> 重试
          </button>
        </div>
      </div>
    </div>

    <template v-else-if="detail">
      <!-- 2-row header so metrics never get squeezed under the title row -->
      <div :style="{ background: A2.surface, borderBottom: `1px solid ${A2.borderHair}`, padding: '12px 22px', display: 'flex', flexDirection: 'column', gap: '12px', flexShrink: 0 }">
        <div :style="{ display: 'flex', alignItems: 'center', gap: '18px', flexWrap: 'wrap' }">
          <div :style="{ display: 'flex', alignItems: 'baseline', gap: '10px', flexWrap: 'wrap' }">
            <div :style="{ fontSize: '24px', fontWeight: 700, letterSpacing: '-0.4px' }">{{ detail.name }}</div>
            <div :style="{ fontSize: '13px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace' }">{{ detail.code }}</div>
            <div :style="{ fontSize: '10px', padding: '3px 8px', background: '#FFEDD5', color: '#9A3412', borderRadius: '999px', fontWeight: 600 }">{{ market }}</div>
            <div v-if="detail.industry" :style="{ fontSize: '10px', padding: '3px 8px', background: A2.qwenSoft, color: A2.qwenDeep, borderRadius: '999px', fontWeight: 600 }">{{ detail.industry }}</div>
          </div>
          <div :style="{ display: 'flex', alignItems: 'baseline', gap: '10px' }">
            <div :style="{ fontSize: '34px', fontWeight: 800, fontFamily: 'IBM Plex Mono, monospace', color: change >= 0 ? A2.up : A2.down, letterSpacing: '-1px', lineHeight: 1 }">
              {{ detail.latest?.close?.toFixed(2) || '—' }}
            </div>
            <div v-if="change != null" :style="{ fontSize: '13px', color: change >= 0 ? A2.up : A2.down, fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700 }">
              {{ change >= 0 ? '+' : '' }}{{ change.toFixed(2) }}
            </div>
            <PctChip v-if="change != null" :pct="changePct" size="lg" />
          </div>
          <div style="flex:1" />
          <div :style="{ display: 'flex', gap: '6px', alignItems: 'center' }">
            <StarButton variant="button" :stock="{ code: detail.code, name: detail.name, sector: detail.industry, refPrice: detail.latest?.close }" :size="12" />
            <AlertRuleEditor v-if="wl.has(detail.code)" :code="detail.code" />
            <button @click="askQwen"
                    :disabled="!aiStreaming && !aiStatus.isUp"
                    :title="!aiStatus.isUp ? `AI 服务暂时不可用（${aiStatus.reason || '上游网络异常'}）` : ''"
                    :style="{ padding: '8px 16px', background: aiStreaming ? '#3F3D38' : (!aiStatus.isUp ? '#B8B4A8' : A2.qwenGrad), color: '#fff', border: 'none', fontSize: '12px', fontWeight: 600, cursor: !aiStreaming && !aiStatus.isUp ? 'not-allowed' : 'pointer', borderRadius: '7px', display: 'flex', alignItems: 'center', gap: '5px', boxShadow: '0 2px 8px rgba(14,14,12,0.12)', opacity: !aiStreaming && !aiStatus.isUp ? 0.7 : 1 }">
              <Icon :name="aiStreaming ? 'x' : 'sparkle'" :size="12" />
              {{ aiStreaming ? '停止' : (!aiStatus.isUp ? '千问离线' : (aiText ? '重新生成' : '问千问')) }}
            </button>
          </div>
        </div>
        <!-- Metrics: 16 字段两行 8 联，密集版 -->
        <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: '8px 14px', fontSize: '11px' }">
          <div v-for="(d, i) in headerMetrics" :key="i">
            <div :style="{ color: A2.textMuted, marginBottom: '1px', fontSize: '9.5px', letterSpacing: '0.3px' }">{{ d.l }}</div>
            <div :style="{ fontFamily: d.isText ? 'inherit' : 'IBM Plex Mono, monospace', fontWeight: 700, color: d.c, fontSize: '12.5px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }">{{ d.v }}</div>
          </div>
        </div>
      </div>

      <div :style="{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 380px', overflow: 'hidden' }">
        <!-- K-line + tabs -->
        <div :style="{ background: A2.surface, overflow: 'auto', padding: '14px', borderRight: `1px solid ${A2.borderHair}` }">
          <div :style="{ display: 'flex', gap: 0, borderBottom: `1px solid ${A2.borderHair}`, marginBottom: '10px' }">
            <div v-for="(t, i) in klineTabs" :key="t.label"
                 @click="klinePeriod = i; reloadKline()"
                 :style="{ padding: '8px 16px', fontSize: '12px', color: klinePeriod === i ? A2.text : A2.textMuted, fontWeight: klinePeriod === i ? 700 : 500, cursor: 'pointer', borderBottom: klinePeriod === i ? `2px solid ${A2.up}` : '2px solid transparent', transition: 'color 0.15s, border-color 0.15s' }">{{ t.label }}</div>
            <div style="flex:1" />
            <div v-for="(t, i) in indicators" :key="t"
                 @click="activeIndicator = i"
                 :style="{ padding: '8px 12px', fontSize: '11px', color: activeIndicator === i ? A2.qwenDeep : A2.textMuted, fontWeight: activeIndicator === i ? 700 : 500, cursor: 'pointer', transition: 'color 0.15s' }">{{ t }}</div>
          </div>
          <div :style="{ position: 'relative', background: A2.bgDeep, borderRadius: '8px', padding: '10px' }">
            <FullCandle :data="klineData" :width="760" :height="340" />
          </div>

          <!-- Tabs below chart -->
          <div :style="{ display: 'flex', gap: 0, borderBottom: `1px solid ${A2.borderHair}`, marginTop: '18px' }">
            <div v-for="(t, i) in detailTabs" :key="t"
                 @click="detailTab = i"
                 :style="{ padding: '10px 16px', fontSize: '12px', color: detailTab === i ? A2.text : A2.textMuted, fontWeight: detailTab === i ? 700 : 500, cursor: 'pointer', borderBottom: detailTab === i ? `2px solid ${A2.text}` : '2px solid transparent', transition: 'color 0.15s, border-color 0.15s' }">{{ t }}</div>
          </div>

          <!-- 财务摘要 -->
          <div v-if="detailTab === 0" :style="{ padding: '14px 4px' }">
            <div :style="{ fontSize: '12px', fontWeight: 700, marginBottom: '10px' }">核心财务指标 · 最新报告期</div>
            <table :style="{ width: '100%', fontSize: '11.5px', borderCollapse: 'collapse' }">
              <tbody>
                <tr v-for="(r, i) in finRows" :key="i" :style="{ borderTop: i === 0 ? 'none' : `1px solid ${A2.borderHair}` }">
                  <td :style="{ padding: '9px 8px', color: A2.textMuted, fontWeight: 500, width: '40%' }">{{ r.l }}</td>
                  <td :style="{ padding: '9px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: r.v.startsWith('+') ? A2.up : (r.v.startsWith('-') ? A2.down : A2.text) }">{{ r.v }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 估值 -->
          <div v-else-if="detailTab === 1" :style="{ padding: '14px 4px' }">
            <div :style="{ fontSize: '12px', fontWeight: 700, marginBottom: '10px' }">估值水平</div>
            <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px' }">
              <div v-for="m in valuationCells" :key="m.l" :style="{ background: A2.bgDeep, border: `1px solid ${A2.borderHair}`, borderRadius: '7px', padding: '12px 14px' }">
                <div :style="{ fontSize: '10px', color: A2.textMuted, marginBottom: '4px', fontWeight: 600, letterSpacing: '0.4px', textTransform: 'uppercase' }">{{ m.l }}</div>
                <div :style="{ fontSize: '20px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', color: m.tone, letterSpacing: '-0.5px' }">{{ m.v }}</div>
                <div :style="{ fontSize: '10px', color: A2.textMuted, marginTop: '2px' }">{{ m.s }}</div>
              </div>
            </div>
          </div>

          <!-- 同行对比 -->
          <div v-else-if="detailTab === 2" :style="{ padding: '14px 4px' }">
            <div :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }">
              <div :style="{ fontSize: '12px', fontWeight: 700 }">同行对比 · {{ detail.industry || '—' }}</div>
              <span v-if="peers.length" :style="{ fontSize: '10.5px', color: A2.textMuted }">按市值排序，前 {{ peers.length }} 只</span>
            </div>
            <div v-if="peersLoading" :style="{ display: 'flex', flexDirection: 'column', gap: '6px' }">
              <Skeleton v-for="n in 5" :key="n" :height="28" />
            </div>
            <table v-else-if="peers.length" :style="{ width: '100%', borderCollapse: 'collapse', fontSize: '11.5px' }">
              <thead>
                <tr :style="{ color: A2.textMuted, fontSize: '10px', fontWeight: 600, letterSpacing: '0.4px', background: A2.bgDeep }">
                  <th :style="{ textAlign: 'left', padding: '8px 12px' }">名称</th>
                  <th :style="{ textAlign: 'left', padding: '8px 6px' }">代码</th>
                  <th :style="{ textAlign: 'right', padding: '8px 6px' }">现价</th>
                  <th :style="{ textAlign: 'right', padding: '8px 6px' }">PE</th>
                  <th :style="{ textAlign: 'right', padding: '8px 6px' }">PB</th>
                  <th :style="{ textAlign: 'right', padding: '8px 6px' }">ROE</th>
                  <th :style="{ textAlign: 'right', padding: '8px 6px' }">股息率</th>
                  <th :style="{ textAlign: 'right', padding: '8px 12px' }">总市值</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in peers" :key="p.code"
                    @click="$router.push(`/detail/${p.code}`)"
                    :class="{ 'peer-self': p.code === detail.code }"
                    class="peer-row"
                    :style="{ borderTop: `1px solid ${A2.borderHair}`, cursor: 'pointer' }">
                  <td :style="{ padding: '9px 12px', fontWeight: p.code === detail.code ? 700 : 600, color: p.code === detail.code ? A2.qwenDeep : A2.text }">
                    {{ p.name }}<span v-if="p.code === detail.code" :style="{ fontSize: '9px', marginLeft: '5px', padding: '1px 5px', background: A2.qwenSoft, color: A2.qwenDeep, borderRadius: '3px', fontWeight: 700 }">本股</span>
                  </td>
                  <td :style="{ padding: '9px 6px', fontFamily: 'IBM Plex Mono, monospace', color: A2.textMuted, fontSize: '10.5px' }">{{ p.code }}</td>
                  <td :style="{ padding: '9px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', fontWeight: 600, color: A2.text }">{{ p.close != null ? p.close.toFixed(2) : '—' }}</td>
                  <td :style="{ padding: '9px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ p.pe != null && p.pe > 0 ? p.pe.toFixed(2) : '—' }}</td>
                  <td :style="{ padding: '9px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ p.pb != null ? p.pb.toFixed(2) : '—' }}</td>
                  <td :style="{ padding: '9px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: p.roe > 10 ? A2.up : A2.textSub, fontWeight: p.roe > 10 ? 600 : 500 }">{{ p.roe != null ? p.roe.toFixed(2) + '%' : '—' }}</td>
                  <td :style="{ padding: '9px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: p.dividend_yield > 4 ? A2.up : A2.textSub }">{{ p.dividend_yield != null ? p.dividend_yield.toFixed(2) + '%' : '—' }}</td>
                  <td :style="{ padding: '9px 12px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ p.market_cap != null ? Math.round(p.market_cap).toLocaleString() : '—' }}<span :style="{ color: A2.textDim, fontSize: '9px' }">亿</span></td>
                </tr>
              </tbody>
            </table>
            <EmptyState v-else icon="chart" title="暂无同行数据" subtitle="该行业暂无其他可比公司，或行业数据未同步" compact />
          </div>

          <!-- 基本信息 -->
          <div v-else :style="{ padding: '14px 4px' }">
            <div :style="{ fontSize: '12px', fontWeight: 700, marginBottom: '12px' }">基本信息</div>
            <div :style="{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px 28px', fontSize: '12px', lineHeight: 1.7 }">
              <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', borderBottom: `1px dashed ${A2.borderHair}`, paddingBottom: '6px' }">
                <span :style="{ color: A2.textMuted }">股票代码</span>
                <strong :style="{ color: A2.text, fontFamily: 'IBM Plex Mono, monospace' }">{{ detail.code }}</strong>
              </div>
              <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', borderBottom: `1px dashed ${A2.borderHair}`, paddingBottom: '6px' }">
                <span :style="{ color: A2.textMuted }">股票名称</span>
                <strong :style="{ color: A2.text }">{{ detail.name }}</strong>
              </div>
              <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', borderBottom: `1px dashed ${A2.borderHair}`, paddingBottom: '6px' }">
                <span :style="{ color: A2.textMuted }">所属行业</span>
                <strong :style="{ color: A2.text }">{{ detail.industry || '—' }}</strong>
              </div>
              <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', borderBottom: `1px dashed ${A2.borderHair}`, paddingBottom: '6px' }">
                <span :style="{ color: A2.textMuted }">上市板块</span>
                <strong :style="{ color: A2.text }">{{ market }}</strong>
              </div>
              <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', borderBottom: `1px dashed ${A2.borderHair}`, paddingBottom: '6px' }">
                <span :style="{ color: A2.textMuted }">最新交易日</span>
                <strong :style="{ color: A2.text, fontFamily: 'IBM Plex Mono, monospace' }">{{ detail.latest?.trade_date || '—' }}</strong>
              </div>
              <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', borderBottom: `1px dashed ${A2.borderHair}`, paddingBottom: '6px' }">
                <span :style="{ color: A2.textMuted }">货币单位</span>
                <strong :style="{ color: A2.text }">人民币 CNY</strong>
              </div>
            </div>
            <div :style="{ marginTop: '16px', padding: '10px 12px', background: A2.bgDeep, borderRadius: '7px', fontSize: '11px', color: A2.textMuted, lineHeight: 1.55, display: 'flex', alignItems: 'flex-start', gap: '6px' }">
              <Icon name="shield" :size="11" />
              <span>本页面所有数据仅供研究参考，不构成投资建议；据此操作，盈亏自负。</span>
            </div>
          </div>
        </div>

        <!-- Right: Qwen analysis -->
        <div :style="{ background: A2.surface, padding: '16px', overflow: 'auto', fontSize: '12px' }">
          <div :style="{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }">
            <div :style="{ width: '26px', height: '26px', background: A2.qwenGrad, color: '#fff', display: 'grid', placeItems: 'center', fontSize: '11px', fontWeight: 800, borderRadius: '7px', boxShadow: '0 2px 6px rgba(14,14,12,0.10)' }">千</div>
            <div :style="{ fontSize: '14px', fontWeight: 700, letterSpacing: '-0.2px' }">千问深度解读</div>
          </div>

          <!-- Score block -->
          <div :style="{ background: A2.qwenGradSoft, border: `1px solid ${A2.borderHair}`, padding: '14px', marginBottom: '14px', borderRadius: '10px' }">
            <div :style="{ display: 'flex', alignItems: 'center', gap: '14px' }">
              <Donut :value="bullScore" :size="68" :stroke="7" :color="A2.qwen" :label="bullScore" />
              <div style="flex:1">
                <div :style="{ fontSize: '11px', color: A2.textMuted }">综合评分</div>
                <div :style="{ fontSize: '18px', fontWeight: 800, color: A2.qwenDeep, letterSpacing: '-0.3px' }">
                  {{ bullScore >= 80 ? '强烈关注' : bullScore >= 60 ? '可关注' : bullScore >= 40 ? '中性' : '谨慎' }}
                </div>
                <div :style="{ fontSize: '10px', color: A2.textMuted, marginTop: '2px' }">基于估值 / 盈利 / 现金流综合</div>
              </div>
            </div>
            <!-- 4 个子维度 -->
            <div :style="{ marginTop: '12px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }">
              <div v-for="d in scoreBreakdown" :key="d.l" :style="{ fontSize: '11px' }">
                <div :style="{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }">
                  <span :style="{ color: A2.textSub, fontWeight: 500 }">{{ d.l }}</span>
                  <span :style="{ fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: A2.qwenDeep }">{{ d.v }}</span>
                </div>
                <div :style="{ height: '4px', background: 'rgba(255,255,255,0.7)', borderRadius: '2px', overflow: 'hidden' }">
                  <div :style="{ width: `${d.v}%`, height: '100%', background: A2.qwenGrad, transition: 'width 0.4s ease' }" />
                </div>
              </div>
            </div>
          </div>

          <!-- AI text -->
          <div v-if="!aiText && !aiLoading && !aiStreaming && !aiError" :style="{ padding: '24px 14px', textAlign: 'center', background: A2.bgDeep, borderRadius: '10px', color: A2.textMuted, fontSize: '12px' }">
            点击右上角「问千问」按钮，让大模型基于当前基本面数据生成深度分析。
          </div>
          <div v-if="aiLoading && !aiText" :style="{ padding: '20px 14px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', background: A2.bgDeep, borderRadius: '10px', color: A2.textMuted, fontSize: '12px' }">
            <span class="dots-loader" :style="{ '--c': A2.qwen }"></span>
            千问思考中…
          </div>
          <div v-if="aiError" :style="{ padding: '12px 14px', background: A2.upSoft, color: A2.up, borderRadius: '8px', fontSize: '12px', lineHeight: 1.6, display: 'flex', alignItems: 'flex-start', gap: '8px' }">
            <Icon name="alert" :size="13" />
            <span style="flex:1">{{ aiError }}</span>
            <button class="btn-outline" :style="{ padding: '4px 10px', fontSize: '11px' }" @click="askQwen">
              <Icon name="refresh" :size="11" /> 重试
            </button>
          </div>
          <div v-if="aiText" class="ai-md" :style="{ padding: '14px', background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', fontSize: '12.5px', color: A2.textSub }">
            <div v-html="aiHtml" />
            <span v-if="aiStreaming" class="caret" />
          </div>
        </div>
      </div>
    </template>
  </Shell>
</template>

<style scoped>
.peer-row { transition: background 0.12s; }
.peer-row:hover { background: #EFEDE6; }
.peer-row.peer-self { background: rgba(36, 86, 216, 0.06); }
.peer-row.peer-self:hover { background: rgba(36, 86, 216, 0.10); }
</style>

<style scoped>
/* AI 输出的 markdown 排版 */
.ai-md :deep(h1),
.ai-md :deep(h2),
.ai-md :deep(h3) {
  font-size: 13px;
  font-weight: 700;
  margin: 12px 0 6px;
  color: #111110;
}
.ai-md :deep(h1):first-child,
.ai-md :deep(h2):first-child,
.ai-md :deep(h3):first-child { margin-top: 0; }
.ai-md :deep(p) { margin: 6px 0; line-height: 1.75; }
.ai-md :deep(p):first-child { margin-top: 0; }
.ai-md :deep(p):last-child { margin-bottom: 0; }
.ai-md :deep(strong) { color: #111110; font-weight: 700; }
.ai-md :deep(em) { color: #3F3D38; font-style: normal; font-weight: 600; }
.ai-md :deep(ul),
.ai-md :deep(ol) { padding-left: 18px; margin: 6px 0; }
.ai-md :deep(li) { margin: 3px 0; line-height: 1.7; }
.ai-md :deep(code) {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11.5px;
  padding: 1px 5px;
  background: #EFEDE6;
  border-radius: 3px;
}
.ai-md :deep(blockquote) {
  margin: 8px 0;
  padding: 4px 12px;
  border-left: 3px solid rgba(36, 86, 216, 0.4);
  color: #3F3D38;
  background: #EFF3FD;
  border-radius: 0 6px 6px 0;
}
.ai-md :deep(hr) {
  border: none;
  border-top: 1px dashed rgba(14, 14, 12, 0.10);
  margin: 10px 0;
}

/* 打字光标 */
.caret {
  display: inline-block;
  width: 6px;
  height: 14px;
  margin-left: 2px;
  background: #2456D8;
  vertical-align: middle;
  animation: caret-blink 1s steps(2) infinite;
}
@keyframes caret-blink { 50% { opacity: 0 } }

/* 三点 loader */
.dots-loader {
  display: inline-block;
  width: 28px;
  height: 6px;
  position: relative;
}
.dots-loader::before,
.dots-loader::after,
.dots-loader { background: var(--c, #2456D8); }
.dots-loader {
  border-radius: 50%;
  width: 6px; height: 6px;
  animation: dot-pulse 1.0s infinite alternate;
  animation-delay: 0.2s;
}
.dots-loader::before, .dots-loader::after {
  content: '';
  position: absolute;
  top: 0;
  width: 6px; height: 6px;
  border-radius: 50%;
}
.dots-loader::before { left: -10px; animation: dot-pulse 1.0s infinite alternate; }
.dots-loader::after  { left: 10px;  animation: dot-pulse 1.0s infinite alternate; animation-delay: 0.4s; }
@keyframes dot-pulse {
  0%   { opacity: 0.3; transform: scale(0.8); }
  100% { opacity: 1;   transform: scale(1.1); }
}
</style>
