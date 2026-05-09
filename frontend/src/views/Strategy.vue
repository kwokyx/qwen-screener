<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import Skeleton from '../components/Skeleton.vue'
import { A2 } from '../shared/theme.js'
import { runBacktest } from '../api/strategy'

const router = useRouter()

function heatBg(pct) {
  // pct 是小数收益率，按 ±6% 上限做强度映射
  const v = pct * 100
  const intensity = Math.min(1, Math.abs(v) / 6)
  return v >= 0
    ? `rgba(220,38,38,${0.18 + intensity * 0.6})`
    : `rgba(5,150,105,${0.18 + intensity * 0.6})`
}

const monthLabels = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']

// ---- 4 个预设策略：每条都对应真实的 conditions 数组 ----
const strategies = [
  {
    id: 0, name: '高股息防御', tag: '稳健', author: '千问出品',
    conditions: [
      { field: 'dividend_yield', op: 'gt', value: 3 },
      { field: 'pe', op: 'lt', value: 15 },
      { field: 'market_cap', op: 'gt', value: 500 },
    ],
    sort_by: 'dividend_yield',
    holdings_count: 8,
    stop_loss: -0.15,
  },
  {
    id: 1, name: '低估值蓝筹', tag: '平衡', author: '千问出品',
    conditions: [
      { field: 'pe', op: 'lt', value: 12 },
      { field: 'pb', op: 'lt', value: 1.5 },
      { field: 'roe', op: 'gt', value: 10 },
      { field: 'market_cap', op: 'gt', value: 1000 },
    ],
    sort_by: 'roe',
    holdings_count: 10,
    stop_loss: -0.15,
  },
  {
    id: 2, name: '高 ROE 成长', tag: '成长', author: '我的策略',
    conditions: [
      { field: 'roe', op: 'gt', value: 15 },
      { field: 'profit_yoy', op: 'gt', value: 20 },
      { field: 'pe', op: 'lt', value: 50 },
    ],
    sort_by: 'profit_yoy',
    holdings_count: 12,
    stop_loss: -0.20,
  },
  {
    id: 3, name: '高毛利消费', tag: '主题', author: '我的策略',
    conditions: [
      { field: 'gross_margin', op: 'gt', value: 40 },
      { field: 'roe', op: 'gt', value: 12 },
      { field: 'pe', op: 'lt', value: 35 },
    ],
    sort_by: 'gross_margin',
    holdings_count: 10,
    stop_loss: -0.18,
  },
]

const activeStrategy = ref(0)
const result = ref(null)        // BacktestResponse
const loading = ref(false)
const errorMsg = ref('')
const startDate = ref('2024-01-01')
const endDate = ref('2026-04-30')
const rebalance = ref('monthly')

// ---- 触发回测 ----
async function runActive() {
  const s = strategies[activeStrategy.value]
  if (!s.conditions.length) {
    errorMsg.value = '该策略没有任何买入条件'
    return
  }
  if (new Date(startDate.value) >= new Date(endDate.value)) {
    errorMsg.value = '回测起始日期必须早于结束日期'
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    result.value = await runBacktest({
      name: s.name,
      conditions: s.conditions,
      sort_by: s.sort_by,
      sort_desc: true,
      holdings_count: s.holdings_count,
      start_date: startDate.value,
      end_date: endDate.value,
      rebalance: rebalance.value,
      initial_capital: 1_000_000,
      transaction_cost: 0.003,
      stop_loss: s.stop_loss,
    })
  } catch (e) {
    errorMsg.value = e.response?.data?.detail || e.message || '回测失败'
  } finally {
    loading.value = false
  }
}

function pickStrategy(i) {
  if (loading.value) return
  activeStrategy.value = i
  runActive()
}

// 启动后默认跑第一个，保证页面打开就有内容
onMounted(runActive)

// ---- 派生显示 ----
const equityData = computed(() => {
  if (!result.value) return { strat: [], bench: [] }
  const initial = result.value.equity[0]?.value || 1
  return {
    strat: result.value.equity.map((p) => p.value / initial),
    bench: result.value.benchmark.map((p) => p.value / (result.value.benchmark[0]?.value || 1)),
  }
})

const summary = computed(() => {
  const m = result.value?.metrics
  if (!m) return []
  const pct = (v) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
  return [
    { l: '累计收益', v: pct(m.total_return), s: `vs 基准 ${pct(m.benchmark_return)}`, tone: m.total_return >= 0 ? A2.up : A2.down, big: true },
    { l: '年化收益', v: pct(m.annual_return), s: `α ${pct(m.total_return - m.benchmark_return)}`, tone: m.annual_return >= 0 ? A2.up : A2.down },
    { l: '最大回撤', v: pct(m.max_drawdown), s: `波动率 ${(m.volatility * 100).toFixed(1)}%`, tone: A2.down },
    { l: '夏普比率', v: m.sharpe.toFixed(2), s: m.sharpe > 1.5 ? '> 1.5 优秀' : m.sharpe > 1 ? '> 1 良好' : '一般', tone: A2.text },
    { l: '胜率', v: `${(m.win_rate * 100).toFixed(1)}%`, s: `${m.total_trades} 笔已平`, tone: A2.text },
    { l: '盈亏比', v: m.profit_loss_ratio.toFixed(2), s: '平均盈/亏', tone: A2.qwen },
  ]
})

// 月度收益矩阵：取出现过的所有年份，每年 12 个月
const monthlyMatrix = computed(() => {
  if (!result.value) return { years: [], grid: [] }
  const map = new Map()
  for (const r of result.value.monthly_returns) {
    if (!map.has(r.year)) map.set(r.year, new Array(12).fill(null))
    map.get(r.year)[r.month - 1] = r.pct
  }
  const years = Array.from(map.keys()).sort((a, b) => a - b)
  return { years, grid: years.map((y) => map.get(y)) }
})

const monthlyStats = computed(() => {
  if (!result.value) return null
  const all = result.value.monthly_returns.map((r) => r.pct).filter((v) => v != null)
  if (!all.length) return null
  const wins = all.filter((v) => v > 0)
  const losses = all.filter((v) => v < 0)
  return {
    winN: wins.length, totalN: all.length,
    lossN: losses.length,
    best: Math.max(...all),
    worst: Math.min(...all),
  }
})

const entryRules = computed(() => {
  const opLabel = { gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=', between: '∈', in: '∈' }
  const fieldLabel = {
    pe: 'PE (TTM)', pb: 'PB', roe: 'ROE', market_cap: '市值',
    dividend_yield: '股息率', revenue_yoy: '营收 YoY', profit_yoy: '净利 YoY',
    gross_margin: '毛利率', debt_ratio: '资产负债率', industry: '行业',
  }
  return strategies[activeStrategy.value].conditions.map((c) => ({
    k: fieldLabel[c.field] || c.field,
    op: opLabel[c.op] || c.op,
    v: Array.isArray(c.value) ? c.value.join('-') : String(c.value),
  }))
})

const sizingCells = computed(() => {
  const s = strategies[activeStrategy.value]
  return [
    { l: '持仓数', v: `${s.holdings_count} 只` },
    { l: '权重', v: '等权' },
    { l: '调仓周期', v: { monthly: '月度', weekly: '周度', daily: '日度' }[rebalance.value] },
    { l: '止损线', v: `${(s.stop_loss * 100).toFixed(0)}%` },
  ]
})

// 把后端 trades 适配前端表格
const trades = computed(() => {
  if (!result.value) return []
  return result.value.trades.slice(-12).reverse().map((t) => ({
    d: typeof t.date === 'string' ? t.date : t.date,
    side: t.side,
    stock: t.name || t.code,
    code: t.code,
    px: t.price,
    qty: t.qty,
    hold: t.holding_days || 0,
    pnl: t.pnl || 0,
    trigger: t.trigger,
  }))
})

// chart paths
const chart = computed(() => {
  const { strat, bench } = equityData.value
  const w = 900, h = 240, pad = { l: 40, r: 12, t: 12, b: 26 }
  if (!strat.length || !bench.length) {
    return { empty: true, w, h, pad, stratPath: '', benchPath: '', fillPath: '', yLines: [], dateMarks: [], peakIdx: -1, troughIdx: -1, xStep: 0, base100Y: 0, lastStratX: 0, lastStratY: 0, lastBenchX: 0, lastBenchY: 0, lastStratLabel: '', drawdownX: 0, drawdownW: 0, midX: 0 }
  }
  const all = [...strat, ...bench]
  const min = Math.min(...all) * 0.98, max = Math.max(...all) * 1.02
  const xStep = (w - pad.l - pad.r) / Math.max(1, strat.length - 1)
  const yScale = (v) => pad.t + (h - pad.t - pad.b) * (1 - (v - min) / (max - min))
  const stratPath = strat.map((v, i) => `${i === 0 ? 'M' : 'L'} ${pad.l + i * xStep} ${yScale(v)}`).join(' ')
  const benchPath = bench.map((v, i) => `${i === 0 ? 'M' : 'L'} ${pad.l + i * xStep} ${yScale(v)}`).join(' ')
  const fillPath = `${stratPath} L ${pad.l + (strat.length - 1) * xStep} ${h - pad.b} L ${pad.l} ${h - pad.b} Z`

  // 找峰谷做最大回撤区域标注
  let peakIdx = 0, peakVal = strat[0], maxDD = 0, troughIdx = -1
  for (let i = 1; i < strat.length; i++) {
    if (strat[i] > peakVal) { peakVal = strat[i]; peakIdx = i }
    const dd = (strat[i] - peakVal) / peakVal
    if (dd < maxDD) { maxDD = dd; troughIdx = i }
  }
  // 反推这个 trough 对应的 peak
  if (troughIdx > 0) {
    let p = troughIdx
    while (p > 0 && strat[p - 1] >= strat[p]) p--
    peakIdx = p
  }

  const yTicks = 5
  const yLines = []
  for (let i = 0; i < yTicks; i++) {
    const v = min + (max - min) * (i / (yTicks - 1))
    yLines.push({ v, y: yScale(v), edge: i === 0 || i === yTicks - 1 })
  }

  // 用真实日期标 x 轴
  const dateLabels = result.value
    ? [0, 0.2, 0.4, 0.6, 0.8, 1].map((p) => {
        const i = Math.floor(p * (result.value.equity.length - 1))
        return result.value.equity[i].date.slice(0, 7)
      })
    : ['', '', '', '', '', '']
  const dateMarks = [0, 0.2, 0.4, 0.6, 0.8, 1].map((p, k) => ({
    x: pad.l + Math.floor(p * (strat.length - 1)) * xStep,
    label: dateLabels[k],
    anchor: k === 0 ? 'start' : k === 5 ? 'end' : 'middle',
  }))

  return {
    empty: false,
    w, h, pad,
    stratPath, benchPath, fillPath,
    yLines, dateMarks,
    peakIdx, troughIdx, xStep,
    base100Y: yScale(1.0),
    lastStratX: pad.l + (strat.length - 1) * xStep,
    lastStratY: yScale(strat[strat.length - 1]),
    lastBenchX: pad.l + (bench.length - 1) * xStep,
    lastBenchY: yScale(bench[bench.length - 1]),
    lastStratLabel: (strat[strat.length - 1] * 100).toFixed(1),
    drawdownX: pad.l + peakIdx * xStep,
    drawdownW: troughIdx > peakIdx ? (troughIdx - peakIdx) * xStep : 0,
    midX: pad.l + ((peakIdx + (troughIdx > peakIdx ? troughIdx : peakIdx)) / 2) * xStep,
    maxDDLabel: (maxDD * 100).toFixed(1),
  }
})

const ddRect = computed(() => !chart.value.empty && chart.value.peakIdx >= 0 && chart.value.troughIdx > chart.value.peakIdx)
</script>

<template>
  <Shell>
    <div :style="{ flex: 1, overflow: 'auto', padding: '16px' }">
      <!-- Header bar -->
      <div :style="{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: '12px' }">
        <div>
          <div :style="{ display: 'flex', alignItems: 'baseline', gap: '8px' }">
            <h2 :style="{ margin: 0, fontSize: '22px', fontWeight: 700, letterSpacing: '-0.5px' }">策略回测</h2>
            <span :style="{ fontSize: '12px', color: A2.textMuted }">· Strategy Backtest</span>
          </div>
          <div :style="{ fontSize: '12px', color: A2.textMuted, marginTop: '3px' }">用千问描述策略，或从模板出发 · 回测窗口 {{ startDate }} 至 {{ endDate }}</div>
        </div>
        <div :style="{ display: 'flex', gap: '8px' }">
          <button @click="router.push('/portfolio')"
                  :style="{ padding: '8px 14px', background: A2.surface, border: `1px solid ${A2.borderHair}`, color: A2.textSub, fontSize: '12px', fontWeight: 600, borderRadius: '7px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px' }">
            <Icon name="bookmark" :size="11" /> 我的策略 ({{ strategies.length }})
          </button>
          <button @click="router.push({ path: '/chat', query: { q: '帮我设计一个稳健的选股策略，列出量化条件' } })"
                  :style="{ padding: '8px 14px', background: A2.qwenGrad, border: 'none', color: '#fff', fontSize: '12px', fontWeight: 600, borderRadius: '7px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px', boxShadow: '0 2px 6px rgba(36,86,216,0.25)' }">
            <Icon name="sparkle" :size="11" /> 让千问写一个策略
          </button>
        </div>
      </div>

      <div :style="{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '12px' }">
        <!-- Left config -->
        <div :style="{ display: 'flex', flexDirection: 'column', gap: '10px' }">
          <!-- Library -->
          <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', overflow: 'hidden', boxShadow: A2.shadow }">
            <div :style="{ padding: '12px 14px', borderBottom: `1px solid ${A2.borderHair}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }">
              <div :style="{ fontSize: '12px', fontWeight: 700 }">策略库</div>
              <span :style="{ fontSize: '10px', color: A2.textMuted }">选择 / 编辑</span>
            </div>
            <div v-for="(s, i) in strategies" :key="s.id" @click="pickStrategy(i)"
                 class="strategy-item"
                 :data-active="activeStrategy === i ? 'true' : 'false'"
                 :style="{ padding: '11px 14px', borderTop: i ? `1px solid ${A2.borderHair}` : 'none', cursor: loading ? 'wait' : 'pointer', background: activeStrategy === i ? A2.qwenGradSoft : 'transparent', borderLeft: activeStrategy === i ? `3px solid ${A2.qwen}` : '3px solid transparent', transition: 'background 0.15s, border-color 0.15s', opacity: loading && activeStrategy !== i ? 0.5 : 1 }">
              <div :style="{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }">
                <span :style="{ fontSize: '13px', fontWeight: 700, color: A2.text }">{{ s.name }}</span>
                <span :style="{ fontSize: '9px', padding: '1px 5px', background: A2.bgDeep, color: A2.textMuted, borderRadius: '3px', fontWeight: 600 }">{{ s.tag }}</span>
              </div>
              <div :style="{ display: 'flex', gap: '12px', fontSize: '10px', fontFamily: 'IBM Plex Mono, monospace' }">
                <span v-if="activeStrategy === i && result" :style="{ color: A2.textMuted }">年化 <span :style="{ color: result.metrics.annual_return >= 0 ? A2.up : A2.down, fontWeight: 700 }">{{ (result.metrics.annual_return * 100).toFixed(1) }}%</span></span>
                <span v-if="activeStrategy === i && result" :style="{ color: A2.textMuted }">回撤 <span :style="{ color: A2.down, fontWeight: 700 }">{{ (result.metrics.max_drawdown * 100).toFixed(1) }}%</span></span>
                <span v-if="activeStrategy === i && result" :style="{ color: A2.textMuted }">夏普 <span :style="{ color: A2.text, fontWeight: 700 }">{{ result.metrics.sharpe.toFixed(2) }}</span></span>
                <span v-else :style="{ color: A2.textDim }">{{ s.conditions.length }} 个条件 · 持仓 {{ s.holdings_count }} 只</span>
              </div>
              <div :style="{ fontSize: '10px', color: A2.textDim, marginTop: '3px' }">{{ s.author }}</div>
            </div>
          </div>

          <!-- Editor -->
          <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', padding: '14px', boxShadow: A2.shadow }">
            <div :style="{ fontSize: '12px', fontWeight: 700, marginBottom: '10px' }">策略配置</div>

            <div :style="{ marginBottom: '12px' }">
              <div :style="{ fontSize: '10px', color: A2.textMuted, fontWeight: 600, marginBottom: '5px', letterSpacing: '0.4px', textTransform: 'uppercase' }">选股池</div>
              <div :style="{ padding: '7px 10px', background: A2.bgDeep, border: `1px solid ${A2.borderHair}`, borderRadius: '6px', fontSize: '12px', color: A2.text, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }">
                <span>沪深 300 + 中证 500</span>
                <Icon name="chevronDown" :size="11" :color="A2.textMuted" />
              </div>
            </div>

            <div :style="{ marginBottom: '12px' }">
              <div :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '5px' }">
                <div :style="{ fontSize: '10px', color: A2.textMuted, fontWeight: 600, letterSpacing: '0.4px', textTransform: 'uppercase' }">买入条件</div>
                <span :style="{ fontSize: '10px', color: A2.textDim }">{{ entryRules.length }} 条</span>
              </div>
              <div v-for="r in entryRules" :key="r.k" :style="{ display: 'flex', gap: '4px', marginBottom: '5px', alignItems: 'center' }">
                <div :style="{ flex: 1, padding: '6px 9px', background: A2.bgDeep, border: `1px solid ${A2.borderHair}`, borderRadius: '5px', fontSize: '11px', color: A2.textSub }">{{ r.k }}</div>
                <div :style="{ padding: '6px 9px', background: A2.qwenSoft, color: A2.qwen, border: `1px solid ${A2.borderHair}`, borderRadius: '5px', fontSize: '11px', fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700 }">{{ r.op }}</div>
                <div :style="{ width: '70px', padding: '6px 9px', background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '5px', fontSize: '11px', fontFamily: 'IBM Plex Mono, monospace', color: A2.text, fontWeight: 600 }">{{ r.v }}</div>
                <Icon name="x" :size="11" :color="A2.textDim" />
              </div>
            </div>

            <div :style="{ marginBottom: '12px' }">
              <div :style="{ fontSize: '10px', color: A2.textMuted, fontWeight: 600, marginBottom: '5px', letterSpacing: '0.4px', textTransform: 'uppercase' }">仓位 & 调仓</div>
              <div :style="{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }">
                <div v-for="c in sizingCells" :key="c.l" :style="{ padding: '7px 9px', background: A2.bgDeep, border: `1px solid ${A2.borderHair}`, borderRadius: '5px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }">
                  <span :style="{ fontSize: '10px', color: A2.textMuted }">{{ c.l }}</span>
                  <span :style="{ fontSize: '11px', fontWeight: 700, color: A2.text, fontFamily: 'IBM Plex Mono, monospace' }">{{ c.v }}</span>
                </div>
              </div>
            </div>

            <div :style="{ marginBottom: '12px' }">
              <div :style="{ fontSize: '10px', color: A2.textMuted, fontWeight: 600, marginBottom: '5px', letterSpacing: '0.4px', textTransform: 'uppercase' }">回测窗口</div>
              <div :style="{ display: 'flex', gap: '4px', alignItems: 'center' }">
                <input v-model="startDate" type="date" class="cfg-input" />
                <span :style="{ color: A2.textMuted, fontSize: '11px' }">至</span>
                <input v-model="endDate" type="date" class="cfg-input" />
              </div>
            </div>

            <div :style="{ marginBottom: '14px' }">
              <div :style="{ fontSize: '10px', color: A2.textMuted, fontWeight: 600, marginBottom: '5px', letterSpacing: '0.4px', textTransform: 'uppercase' }">调仓周期</div>
              <select v-model="rebalance" class="cfg-input" :style="{ width: '100%' }">
                <option value="monthly">月度</option>
                <option value="weekly">周度</option>
                <option value="daily">日度</option>
              </select>
            </div>

            <button @click="runActive" :disabled="loading"
                    :style="{ width: '100%', padding: '10px', background: A2.text, color: '#fff', border: 'none', borderRadius: '7px', fontSize: '12px', fontWeight: 700, cursor: loading ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', opacity: loading ? 0.7 : 1 }">
              <Icon :name="loading ? 'refresh' : 'play'" :size="11" /> {{ loading ? '回测中…' : '运行回测' }}
            </button>
            <div v-if="errorMsg" :style="{ marginTop: '8px', padding: '8px 10px', background: A2.upSoft, color: A2.up, borderRadius: '6px', fontSize: '11px', display: 'flex', alignItems: 'flex-start', gap: '6px' }">
              <Icon name="alert" :size="11" />
              <span style="flex:1">{{ errorMsg }}</span>
            </div>
            <div v-if="result && result.data_source !== 'real'" :style="{ marginTop: '8px', padding: '8px 10px', background: A2.bgDeep, color: A2.textMuted, borderRadius: '6px', fontSize: '10.5px', lineHeight: 1.5, display: 'flex', alignItems: 'flex-start', gap: '6px' }">
              <Icon name="shield" :size="12" />
              <span>本回测基于模拟价格序列生成，仅用于策略逻辑验证；不代表真实历史表现，亦不构成投资建议。</span>
            </div>

            <!-- 后端额外说明：universe 不足、止损触发统计等 -->
            <div v-if="result && result.notes && result.notes.length" :style="{ marginTop: '8px', padding: '8px 10px', background: A2.qwenGradSoft, color: A2.qwenDeep, borderRadius: '6px', fontSize: '10.5px', lineHeight: 1.55 }">
              <div v-for="(n, i) in result.notes" :key="i" :style="{ display: 'flex', gap: '5px', alignItems: 'flex-start' }">
                <span :style="{ color: A2.qwen }">·</span>
                <span style="flex:1">{{ n }}</span>
              </div>
            </div>

            <!-- universe 远小于目标持仓 → 醒目提示 -->
            <div v-if="result && result.universe.length < strategies[activeStrategy].holdings_count / 2" :style="{ marginTop: '8px', padding: '8px 10px', background: A2.upSoft, color: A2.up, borderRadius: '6px', fontSize: '10.5px', lineHeight: 1.45, display: 'flex', alignItems: 'flex-start', gap: '6px' }">
              <Icon name="alert" :size="12" />
              <span>仅命中 {{ result.universe.length }} 只股票（目标 {{ strategies[activeStrategy].holdings_count }} 只），结果代表性有限。建议放宽部分条件或同步更多 A 股数据。</span>
            </div>
          </div>
        </div>

        <!-- Right results -->
        <div :style="{ display: 'flex', flexDirection: 'column', gap: '10px' }">
          <!-- Summary metrics -->
          <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '8px' }">
            <template v-if="!summary.length">
              <div v-for="n in 6" :key="n" :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '9px', padding: '12px 14px', boxShadow: A2.shadow }">
                <Skeleton :height="9" :width="60" :style="{ marginBottom: '6px' }" />
                <Skeleton :height="22" :width="80" />
                <Skeleton :height="9" :width="50" :style="{ marginTop: '6px' }" />
              </div>
            </template>
            <div v-else v-for="m in summary" :key="m.l" :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '9px', padding: '12px 14px', boxShadow: A2.shadow, position: 'relative', overflow: 'hidden' }">
              <div v-if="m.big" :style="{ position: 'absolute', left: 0, top: 0, bottom: 0, width: '3px', background: m.tone }" />
              <div :style="{ fontSize: '10px', color: A2.textMuted, fontWeight: 600, letterSpacing: '0.4px', textTransform: 'uppercase', marginBottom: '4px' }">{{ m.l }}</div>
              <div :style="{ fontSize: m.big ? '22px' : '18px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', color: m.tone, letterSpacing: '-0.5px' }">{{ m.v }}</div>
              <div :style="{ fontSize: '10px', color: A2.textMuted, marginTop: '2px', fontFamily: 'IBM Plex Mono, monospace' }">{{ m.s }}</div>
            </div>
          </div>

          <!-- 数据源警示：回测用了合成价格序列 -->
          <div v-if="result && result.data_source !== 'real'"
               :style="{ marginBottom: '10px', padding: '9px 12px', background: A2.amberSoft, color: '#8C5A0F', border: `1px solid ${A2.amber}33`, borderRadius: '8px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '8px' }">
            <Icon name="alert" :size="13" />
            <span style="flex:1">
              <strong>{{ result.data_source === 'synthesized' ? '完全模拟价格' : '部分模拟价格' }}</strong>：
              本系统当前历史日 K 线不足，回测使用了确定性高斯游走合成价格。结果仅展示算法逻辑，<strong>不代表真实收益</strong>。
              真实数据积累后将自动切换。
            </span>
          </div>

          <!-- Equity curve -->
          <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', padding: '16px', boxShadow: A2.shadow }">
            <div :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }">
              <div>
                <div :style="{ fontSize: '14px', fontWeight: 700, letterSpacing: '-0.2px' }">{{ strategies[activeStrategy].name }} · 净值曲线</div>
                <div :style="{ fontSize: '11px', color: A2.textMuted, marginTop: '2px' }">初始资金 100 万 · 含交易成本 0.3%</div>
              </div>
              <div :style="{ display: 'flex', gap: '14px', alignItems: 'center' }">
                <div :style="{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: A2.textSub }">
                  <div :style="{ width: '12px', height: '2px', background: A2.qwen, borderRadius: '1px' }" /> 策略
                </div>
                <div :style="{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: A2.textMuted }">
                  <div :style="{ width: '12px', height: '2px', background: A2.textDim, borderRadius: '1px' }" /> 沪深 300
                </div>
              </div>
            </div>
            <svg :viewBox="`0 0 ${chart.w} ${chart.h}`" preserveAspectRatio="none" :style="{ width: '100%', height: '240px' }">
              <defs>
                <linearGradient id="bt-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#2456D8" stop-opacity="0.18" />
                  <stop offset="100%" stop-color="#2456D8" stop-opacity="0" />
                </linearGradient>
              </defs>

              <g v-for="(t, i) in chart.yLines" :key="i">
                <line :x1="chart.pad.l" :x2="chart.w - chart.pad.r" :y1="t.y" :y2="t.y" stroke="rgba(14,14,12,0.06)" :stroke-dasharray="t.edge ? '0' : '2,3'" stroke-width="0.5" />
                <text :x="chart.pad.l - 6" :y="t.y + 3" font-size="9" fill="#B8B4A8" text-anchor="end" font-family="IBM Plex Mono, monospace">{{ (t.v * 100).toFixed(0) }}</text>
              </g>

              <line :x1="chart.pad.l" :x2="chart.w - chart.pad.r" :y1="chart.base100Y" :y2="chart.base100Y" stroke="#7A776F" stroke-width="0.6" stroke-dasharray="2,4" />
              <text :x="chart.w - chart.pad.r - 4" :y="chart.base100Y - 3" font-size="8" fill="#7A776F" text-anchor="end" font-family="IBM Plex Mono, monospace">起始 100</text>

              <rect v-if="ddRect" :x="chart.drawdownX" :y="chart.pad.t" :width="chart.drawdownW" :height="chart.h - chart.pad.t - chart.pad.b" fill="rgba(5,150,105,0.06)" />

              <path :d="chart.fillPath" fill="url(#bt-fill)" />
              <path :d="chart.benchPath" fill="none" stroke="#B8B4A8" stroke-width="1.2" stroke-dasharray="3,3" />
              <path :d="chart.stratPath" fill="none" stroke="#2456D8" stroke-width="1.6" />

              <circle :cx="chart.lastStratX" :cy="chart.lastStratY" r="3.5" fill="#2456D8" stroke="#fff" stroke-width="1.4" />
              <text :x="chart.lastStratX - 6" :y="chart.lastStratY - 6" font-size="10" fill="#2456D8" text-anchor="end" font-weight="700" font-family="IBM Plex Mono, monospace">{{ chart.lastStratLabel }}</text>
              <circle :cx="chart.lastBenchX" :cy="chart.lastBenchY" r="2.5" fill="#B8B4A8" stroke="#fff" stroke-width="1.2" />

              <g v-if="ddRect">
                <line :x1="chart.drawdownX" :x2="chart.drawdownX + chart.drawdownW" :y1="chart.pad.t + 18" :y2="chart.pad.t + 18" stroke="#059669" stroke-width="0.8" />
                <text :x="chart.midX" :y="chart.pad.t + 13" font-size="9" fill="#059669" text-anchor="middle" font-weight="600" font-family="IBM Plex Mono, monospace">最大回撤 {{ chart.maxDDLabel }}%</text>
              </g>

              <text v-for="m in chart.dateMarks" :key="m.x" :x="m.x" :y="chart.h - 8" font-size="9" fill="#7A776F" :text-anchor="m.anchor" font-family="IBM Plex Mono, monospace">{{ m.label }}</text>
            </svg>
          </div>

          <!-- Bottom row: Qwen + heatmap -->
          <div :style="{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: '10px' }">
            <div :style="{ background: A2.qwenGradSoft, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', padding: '16px', boxShadow: A2.shadow, position: 'relative', overflow: 'hidden' }">
              <div :style="{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }">
                <div :style="{ width: '26px', height: '26px', background: A2.qwenGrad, color: '#fff', display: 'grid', placeItems: 'center', fontSize: '12px', fontWeight: 800, borderRadius: '6px', boxShadow: '0 2px 6px rgba(36,86,216,0.25)' }">千</div>
                <div :style="{ fontSize: '13px', fontWeight: 700 }">回测概要</div>
                <span v-if="result" :style="{ marginLeft: 'auto', fontSize: '10px', color: A2.textMuted, padding: '2px 7px', background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '3px', fontFamily: 'IBM Plex Mono, monospace' }">{{ startDate }} ~ {{ endDate }}</span>
              </div>
              <div v-if="!result" :style="{ fontSize: '12px', color: A2.textMuted, padding: '8px 0' }">
                <Skeleton :height="12" :width="'90%'" :style="{ marginBottom: '6px' }" />
                <Skeleton :height="12" :width="'80%'" :style="{ marginBottom: '6px' }" />
                <Skeleton :height="12" :width="'60%'" />
              </div>
              <div v-else :style="{ fontSize: '12px', color: A2.textSub, lineHeight: 1.7, marginBottom: '10px' }">
                策略 <strong>{{ result.name }}</strong> 在窗口内累计收益
                <strong :style="{ color: result.metrics.total_return >= 0 ? A2.up : A2.down }">{{ (result.metrics.total_return * 100).toFixed(2) }}%</strong>，
                基准（等权买入持有）
                <strong>{{ (result.metrics.benchmark_return * 100).toFixed(2) }}%</strong>，超额
                <strong :style="{ color: result.metrics.total_return - result.metrics.benchmark_return >= 0 ? A2.up : A2.down }">{{ ((result.metrics.total_return - result.metrics.benchmark_return) * 100).toFixed(2) }}%</strong>。
                夏普 {{ result.metrics.sharpe.toFixed(2) }}，最大回撤
                <strong :style="{ color: A2.down }">{{ (result.metrics.max_drawdown * 100).toFixed(2) }}%</strong>，
                共 {{ result.metrics.total_trades }} 笔已平仓交易、胜率 {{ (result.metrics.win_rate * 100).toFixed(1) }}%。
                选出股票池：{{ result.universe_names.slice(0, 5).join('、') }}<span v-if="result.universe_names.length > 5">…</span>。
              </div>
              <div v-if="result" :style="{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', paddingTop: '10px', borderTop: `1px dashed ${A2.borderHair}` }">
                <div>
                  <div :style="{ fontSize: '9px', color: A2.textMuted, marginBottom: '2px', fontWeight: 600, letterSpacing: '0.3px' }">α (vs 基准)</div>
                  <div :style="{ fontSize: '14px', fontWeight: 700, color: A2.text, fontFamily: 'IBM Plex Mono, monospace' }">{{ ((result.metrics.total_return - result.metrics.benchmark_return) * 100).toFixed(2) }}%</div>
                </div>
                <div>
                  <div :style="{ fontSize: '9px', color: A2.textMuted, marginBottom: '2px', fontWeight: 600, letterSpacing: '0.3px' }">Calmar 比率</div>
                  <div :style="{ fontSize: '14px', fontWeight: 700, color: A2.text, fontFamily: 'IBM Plex Mono, monospace' }">{{ result.metrics.max_drawdown < 0 ? Math.abs(result.metrics.annual_return / result.metrics.max_drawdown).toFixed(2) : '∞' }}</div>
                </div>
                <div>
                  <div :style="{ fontSize: '9px', color: A2.textMuted, marginBottom: '2px', fontWeight: 600, letterSpacing: '0.3px' }">年化波动率</div>
                  <div :style="{ fontSize: '14px', fontWeight: 700, color: A2.text, fontFamily: 'IBM Plex Mono, monospace' }">{{ (result.metrics.volatility * 100).toFixed(2) }}%</div>
                </div>
              </div>
            </div>

            <!-- Heatmap -->
            <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', padding: '14px', boxShadow: A2.shadow }">
              <div :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }">
                <div :style="{ fontSize: '12px', fontWeight: 700 }">月度收益</div>
                <span :style="{ fontSize: '10px', color: A2.textMuted }">%</span>
              </div>
              <div v-if="monthlyMatrix.years.length" :style="{ display: 'grid', gridTemplateColumns: '36px repeat(12, 1fr)', gap: '2px', fontSize: '9px', fontFamily: 'IBM Plex Mono, monospace' }">
                <div></div>
                <div v-for="m in monthLabels" :key="m" :style="{ textAlign: 'center', color: A2.textMuted, fontSize: '8px', padding: '2px 0' }">{{ m.replace('月', '') }}</div>
                <template v-for="(rets, yi) in monthlyMatrix.grid" :key="monthlyMatrix.years[yi]">
                  <div :style="{ textAlign: 'right', color: A2.textMuted, alignSelf: 'center', fontSize: '9px', paddingRight: '4px' }">{{ monthlyMatrix.years[yi] }}</div>
                  <div v-for="(r, mi) in rets" :key="mi"
                       :style="{ background: r == null ? A2.bgDeep : heatBg(r), padding: '6px 2px', textAlign: 'center', borderRadius: '3px', color: r == null ? A2.textDim : '#fff', fontWeight: 700, fontSize: '9px' }">
                    {{ r == null ? '—' : (r >= 0 ? '+' : '') + (r * 100).toFixed(1) }}
                  </div>
                </template>
              </div>
              <div v-else :style="{ display: 'grid', gridTemplateColumns: '36px repeat(12, 1fr)', gap: '2px' }">
                <div></div>
                <Skeleton v-for="n in 36" :key="n" :height="12" :rounded="3" />
              </div>

              <div v-if="monthlyStats" :style="{ marginTop: '12px', paddingTop: '10px', borderTop: `1px dashed ${A2.borderHair}`, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }">
                <div :style="{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }">
                  <span :style="{ color: A2.textMuted }">盈利月</span>
                  <span :style="{ fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: A2.up }">{{ monthlyStats.winN }} / {{ monthlyStats.totalN }}</span>
                </div>
                <div :style="{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }">
                  <span :style="{ color: A2.textMuted }">最佳月</span>
                  <span :style="{ fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: A2.up }">+{{ (monthlyStats.best * 100).toFixed(1) }}%</span>
                </div>
                <div :style="{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }">
                  <span :style="{ color: A2.textMuted }">亏损月</span>
                  <span :style="{ fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: A2.down }">{{ monthlyStats.lossN }} / {{ monthlyStats.totalN }}</span>
                </div>
                <div :style="{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }">
                  <span :style="{ color: A2.textMuted }">最差月</span>
                  <span :style="{ fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: A2.down }">{{ (monthlyStats.worst * 100).toFixed(1) }}%</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Trade log -->
          <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', overflow: 'hidden', boxShadow: A2.shadow }">
            <div :style="{ padding: '11px 16px', borderBottom: `1px solid ${A2.borderHair}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }">
              <div :style="{ fontSize: '12px', fontWeight: 700 }">近期交易记录</div>
              <div :style="{ fontSize: '10px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace' }">{{ result ? `共 ${result.trades.length} 笔（含未平仓）· 显示最近 ${trades.length} 笔` : '等待回测' }}</div>
            </div>
            <table :style="{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }">
              <thead>
                <tr :style="{ color: A2.textMuted, fontSize: '10px', fontWeight: 600, letterSpacing: '0.4px' }">
                  <th :style="{ textAlign: 'left', padding: '7px 16px', fontWeight: 600 }">日期</th>
                  <th :style="{ textAlign: 'left', padding: '7px 6px', fontWeight: 600 }">方向</th>
                  <th :style="{ textAlign: 'left', padding: '7px 6px', fontWeight: 600 }">标的</th>
                  <th :style="{ textAlign: 'right', padding: '7px 6px', fontWeight: 600 }">价格</th>
                  <th :style="{ textAlign: 'right', padding: '7px 6px', fontWeight: 600 }">数量</th>
                  <th :style="{ textAlign: 'right', padding: '7px 6px', fontWeight: 600 }">持有天数</th>
                  <th :style="{ textAlign: 'right', padding: '7px 6px', fontWeight: 600 }">盈亏</th>
                  <th :style="{ textAlign: 'left', padding: '7px 16px', fontWeight: 600 }">触发条件</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="!trades.length">
                  <td colspan="8" :style="{ padding: '24px 16px', textAlign: 'center', color: A2.textMuted, fontSize: '11.5px' }">
                    {{ loading ? '回测中…' : '等待回测结果' }}
                  </td>
                </tr>
                <tr v-for="t in trades" :key="t.d + t.code + t.side" :style="{ borderTop: `1px solid ${A2.borderHair}` }">
                  <td :style="{ padding: '9px 16px', fontFamily: 'IBM Plex Mono, monospace', color: A2.textMuted }">{{ t.d }}</td>
                  <td :style="{ padding: '9px 6px' }">
                    <span :style="{ fontSize: '9px', padding: '2px 6px', background: t.side === 'BUY' ? A2.upSoft : A2.downSoft, color: t.side === 'BUY' ? A2.up : A2.down, borderRadius: '3px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace' }">{{ t.side }}</span>
                  </td>
                  <td :style="{ padding: '9px 6px' }">
                    <span :style="{ fontWeight: 600, color: A2.text }">{{ t.stock }}</span>
                    <span :style="{ marginLeft: '6px', fontFamily: 'IBM Plex Mono, monospace', color: A2.textMuted, fontSize: '10px' }">{{ t.code }}</span>
                  </td>
                  <td :style="{ padding: '9px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.text, fontWeight: 600 }">{{ t.px.toFixed(2) }}</td>
                  <td :style="{ padding: '9px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ t.qty.toLocaleString() }}</td>
                  <td :style="{ padding: '9px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textMuted }">{{ t.hold || '—' }}</td>
                  <td :style="{ padding: '9px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: t.pnl > 0 ? A2.up : (t.pnl < 0 ? A2.down : A2.textDim) }">{{ t.pnl ? (t.pnl > 0 ? '+' : '') + t.pnl.toLocaleString() : '—' }}</td>
                  <td :style="{ padding: '9px 16px', color: A2.textSub }">{{ t.trigger }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </Shell>
</template>

<style scoped>
.strategy-item[data-active="false"]:hover { background: rgba(36, 86, 216, 0.04) !important; }
.cfg-input {
  flex: 1;
  font-family: inherit;
  font-size: 11.5px;
  padding: 6px 9px;
  background: #FFFFFF;
  border: 1px solid rgba(14,14,12,0.08);
  border-radius: 5px;
  color: #111110;
  outline: none;
  font-family: 'IBM Plex Mono', monospace;
}
.cfg-input:focus { border-color: #2456D8; }
</style>
