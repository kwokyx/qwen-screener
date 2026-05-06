<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import PctChip from '../components/charts/PctChip.vue'
import StarButton from '../components/StarButton.vue'
import AlertRuleEditor from '../components/AlertRuleEditor.vue'
import EmptyState from '../components/EmptyState.vue'
import { A2 } from '../shared/theme.js'
import { seededRand } from '../shared/data.js'
import { useWatchlistStore } from '../stores/watchlist'

const router = useRouter()
const gotoDetail = (code) => router.push(`/detail/${code}`)
const view = ref('持仓')
const wl = useWatchlistStore()

const holdings = [
  { code: '600519.SH', name: '贵州茅台', sector: '食品饮料', qty: 200, cost: 1620.00, price: 1742.50, weight: 27.1, qwen: { tag: '继续持有', tone: 'up', note: '估值合理，护城河稳固' } },
  { code: '300750.SZ', name: '宁德时代', sector: '电池', qty: 500, cost: 198.40, price: 245.30, weight: 22.4, qwen: { tag: '止盈一部分', tone: 'amber', note: '连续放量，建议落袋 30%' } },
  { code: '688981.SH', name: '中芯国际', sector: '半导体', qty: 1000, cost: 64.20, price: 78.45, weight: 14.3, qwen: { tag: '可加仓', tone: 'up', note: '产能利用率回升' } },
  { code: '600036.SH', name: '招商银行', sector: '银行', qty: 800, cost: 38.10, price: 42.18, weight: 6.1, qwen: { tag: '继续持有', tone: 'up', note: '股息稳定 4.8%' } },
  { code: '002594.SZ', name: '比亚迪', sector: '汽车', qty: 300, cost: 268.00, price: 254.20, weight: 13.9, qwen: { tag: '关注突破', tone: 'qwen', note: '海外销量提速，关注 250 阻力' } },
  { code: '601012.SH', name: '隆基绿能', sector: '光伏', qty: 1500, cost: 26.80, price: 21.45, weight: 5.9, qwen: { tag: '减仓观望', tone: 'down', note: '硅料价格未稳，盈利承压' } },
  { code: '300760.SZ', name: '迈瑞医疗', sector: '医疗器械', qty: 200, cost: 264.30, price: 285.60, weight: 5.2, qwen: { tag: '继续持有', tone: 'up', note: '海外订单超预期' } },
  { code: '000858.SZ', name: '五粮液', sector: '食品饮料', qty: 400, cost: 158.40, price: 152.30, weight: 5.1, qwen: { tag: '观望', tone: 'qwen', note: '动销偏弱，等待Q2拐点' } },
]

const totals = computed(() => {
  const totalValue = holdings.reduce((s, h) => s + h.price * h.qty, 0)
  const totalCost = holdings.reduce((s, h) => s + h.cost * h.qty, 0)
  return {
    totalValue,
    totalCost,
    totalPnl: totalValue - totalCost,
    totalPnlPct: ((totalValue - totalCost) / totalCost) * 100,
  }
})

// deterministic equity / bench curves
const curves = computed(() => {
  const equity = []
  const bench = []
  let v = 1100000, b = 1100000
  const r1 = seededRand(31), r2 = seededRand(57)
  for (let i = 0; i < 60; i++) {
    v *= 1 + (r1() - 0.42) * 0.012
    b *= 1 + (r2() - 0.48) * 0.009
    equity.push(v)
    bench.push(b)
  }
  equity[equity.length - 1] = totals.value.totalValue
  return { equity, bench }
})

const toneColor = (t) => ({ up: A2.up, down: A2.down, amber: A2.amber, qwen: A2.qwen })[t] || A2.textSub

const summaryMetrics = [
  { l: '今日盈亏', v: '+¥18,420', s: '+1.46%', tone: 'up' },
  { l: '本周盈亏', v: '+¥42,810', s: '+3.22%', tone: 'up' },
  { l: '本月盈亏', v: '+¥86,420', s: '+7.18%', tone: 'up' },
  { l: '可用资金', v: '¥124,560', s: '占比 8.8%', tone: 'sub' },
  { l: '持仓数', v: '8', s: '自选 24', tone: 'sub' },
  { l: '风险等级', v: 'R3', s: '中等偏积极', tone: 'qwen' },
]

const stats = [
  { l: '年化收益', v: '+22.4%', tone: A2.up },
  { l: '最大回撤', v: '-8.6%', tone: A2.down },
  { l: '夏普比率', v: '1.84', tone: A2.text },
  { l: '波动率', v: '14.2%', tone: A2.text },
  { l: 'α (vs 沪深300)', v: '+9.2%', tone: A2.qwen },
]

const sectorAlloc = [
  { l: '食品饮料', v: 32.2, c: '#DC2626' },
  { l: '电池/汽车', v: 36.3, c: '#2456D8' },
  { l: '半导体', v: 14.3, c: '#7C3AED' },
  { l: '银行', v: 6.1, c: '#059669' },
  { l: '光伏', v: 5.9, c: '#D97706' },
  { l: '其他', v: 5.2, c: '#9CA3AF' },
]

const alerts = [
  { tone: A2.up, tag: '突破', stock: '宁德时代', desc: '今日放量 +5.55% 突破 60 日新高，建议关注止盈点位 ¥248', time: '14:25' },
  { tone: A2.down, tag: '止损', stock: '隆基绿能', desc: '跌破成本线 -19.96%，已触发你设置的 -15% 风控线', time: '13:58' },
  { tone: A2.amber, tag: '集中度', stock: '组合', desc: '前 3 持仓占比 63.8%，超过你设定的 60% 风险阈值', time: '11:30' },
  { tone: A2.qwen, tag: '机会', stock: '迈瑞医疗', desc: '本周机构调研 12 家，海外订单超预期，可考虑加仓', time: '10:12' },
]

// equity chart paths
const chart = computed(() => {
  const w = 700, h = 200, pad = { l: 10, r: 10, t: 10, b: 22 }
  const all = [...curves.value.equity, ...curves.value.bench]
  const min = Math.min(...all), max = Math.max(...all)
  const xStep = (w - pad.l - pad.r) / (curves.value.equity.length - 1)
  const yScale = (v) => pad.t + (h - pad.t - pad.b) * (1 - (v - min) / (max - min))
  const equityPath = curves.value.equity.map((v, i) => `${i === 0 ? 'M' : 'L'} ${pad.l + i * xStep} ${yScale(v)}`).join(' ')
  const benchPath = curves.value.bench.map((v, i) => `${i === 0 ? 'M' : 'L'} ${pad.l + i * xStep} ${yScale(v)}`).join(' ')
  const fillPath = `${equityPath} L ${pad.l + (curves.value.equity.length - 1) * xStep} ${h - pad.b} L ${pad.l} ${h - pad.b} Z`
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map(p => ({ v: min + (max - min) * p }))
  yTicks.forEach(t => t.y = yScale(t.v))
  const lastEquityY = yScale(curves.value.equity[curves.value.equity.length - 1])
  const lastEquityX = pad.l + (curves.value.equity.length - 1) * xStep
  const dateMarks = [0, Math.floor(curves.value.equity.length * 0.25), Math.floor(curves.value.equity.length * 0.5), Math.floor(curves.value.equity.length * 0.75), curves.value.equity.length - 1].map((i, k) => ({
    x: pad.l + i * xStep,
    label: ['03-01', '03-15', '04-01', '04-15', '05-01'][k],
    anchor: k === 0 ? 'start' : k === 4 ? 'end' : 'middle',
  }))
  return { w, h, pad, equityPath, benchPath, fillPath, yTicks, lastEquityX, lastEquityY, dateMarks }
})

// donut arcs
const donutArcs = computed(() => {
  const data = sectorAlloc
  const size = 108
  const total = data.reduce((s, d) => s + d.v, 0)
  const r = size / 2 - 6, cx = size / 2, cy = size / 2
  let acc = 0
  const arcs = data.map(d => {
    const start = (acc / total) * 2 * Math.PI - Math.PI / 2
    acc += d.v
    const end = (acc / total) * 2 * Math.PI - Math.PI / 2
    const large = end - start > Math.PI ? 1 : 0
    const x1 = cx + r * Math.cos(start), y1 = cy + r * Math.sin(start)
    const x2 = cx + r * Math.cos(end), y2 = cy + r * Math.sin(end)
    return { d: `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`, c: d.c }
  })
  return { arcs, size, cx, cy, r }
})

const fmtToneColor = (tone) => tone === 'sub' ? A2.text : (tone === 'qwen' ? A2.qwen : (tone === 'up' ? A2.up : A2.down))
</script>

<template>
  <Shell>
    <div :style="{ flex: 1, overflow: 'auto', padding: '16px' }">
      <!-- Hero: summary + equity -->
      <div :style="{ display: 'grid', gridTemplateColumns: '1.05fr 1.95fr', gap: '10px', marginBottom: '12px' }">
        <!-- Summary card -->
        <div class="card-hover" :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', padding: '18px', boxShadow: A2.shadow, position: 'relative', overflow: 'hidden' }">
          <div :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }">
            <div>
              <div :style="{ fontSize: '11px', color: A2.textMuted, letterSpacing: '0.6px', textTransform: 'uppercase', fontWeight: 600 }">Net Asset Value</div>
              <div :style="{ fontSize: '11px', color: A2.textDim, marginTop: '2px', fontFamily: 'IBM Plex Mono, monospace' }">账户 · 个人 #28461</div>
            </div>
            <div :style="{ fontSize: '10px', color: A2.textMuted, padding: '3px 8px', background: A2.bgDeep, border: `1px solid ${A2.borderHair}`, borderRadius: '4px', fontFamily: 'IBM Plex Mono, monospace' }">2026-05-01</div>
          </div>

          <div :style="{ fontSize: '36px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '-1px', lineHeight: 1.1 }">¥{{ totals.totalValue.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) }}</div>
          <div :style="{ display: 'flex', alignItems: 'baseline', gap: '8px', marginTop: '4px' }">
            <span :style="{ fontSize: '14px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', color: totals.totalPnl >= 0 ? A2.up : A2.down }">{{ totals.totalPnl >= 0 ? '+' : '' }}¥{{ Math.round(totals.totalPnl).toLocaleString() }}</span>
            <PctChip :pct="totals.totalPnlPct" size="sm" />
            <span :style="{ fontSize: '11px', color: A2.textMuted }">累计</span>
          </div>

          <div :style="{ height: '1px', background: A2.borderHair, margin: '16px 0' }" />

          <div :style="{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }">
            <div v-for="m in summaryMetrics" :key="m.l">
              <div :style="{ fontSize: '10px', color: A2.textMuted, fontWeight: 500, marginBottom: '3px' }">{{ m.l }}</div>
              <div :style="{ fontSize: '15px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', color: fmtToneColor(m.tone), letterSpacing: '-0.3px' }">{{ m.v }}</div>
              <div :style="{ fontSize: '10px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace' }">{{ m.s }}</div>
            </div>
          </div>
        </div>

        <!-- Equity curve -->
        <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', padding: '16px', boxShadow: A2.shadow, display: 'flex', flexDirection: 'column' }">
          <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }">
            <div>
              <div :style="{ fontSize: '13px', fontWeight: 700 }">组合净值曲线</div>
              <div :style="{ fontSize: '11px', color: A2.textMuted, marginTop: '1px' }">近 60 个交易日 · 对比沪深 300</div>
            </div>
            <div :style="{ display: 'flex', gap: '14px', alignItems: 'center' }">
              <div :style="{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: A2.textSub }">
                <div :style="{ width: '12px', height: '2px', background: A2.qwen, borderRadius: '1px' }" /> 我的组合
              </div>
              <div :style="{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: A2.textMuted }">
                <div :style="{ width: '12px', height: '2px', background: A2.textDim, borderRadius: '1px' }" /> 沪深 300
              </div>
              <div :style="{ display: 'flex', gap: '2px', padding: '3px', background: A2.bgDeep, borderRadius: '6px', marginLeft: '8px' }">
                <div v-for="(t, i) in ['1W', '1M', '3M', '1Y', 'ALL']" :key="t"
                     :style="{ padding: '4px 10px', background: i === 1 ? A2.surface : 'transparent', color: i === 1 ? A2.text : A2.textMuted, fontSize: '10px', fontWeight: 600, cursor: 'pointer', borderRadius: '4px', boxShadow: i === 1 ? A2.shadow : 'none', fontFamily: 'IBM Plex Mono, monospace' }">{{ t }}</div>
              </div>
            </div>
          </div>

          <div :style="{ flex: 1, position: 'relative', minHeight: '200px' }">
            <svg :viewBox="`0 0 ${chart.w} ${chart.h}`" preserveAspectRatio="none" :style="{ width: '100%', height: '100%' }">
              <defs>
                <linearGradient id="eq-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#2456D8" stop-opacity="0.18" />
                  <stop offset="100%" stop-color="#2456D8" stop-opacity="0" />
                </linearGradient>
              </defs>
              <line v-for="(t, i) in chart.yTicks" :key="i" :x1="chart.pad.l" :x2="chart.w - chart.pad.r" :y1="t.y" :y2="t.y" stroke="rgba(14,14,12,0.06)" :stroke-dasharray="i === 0 || i === chart.yTicks.length - 1 ? '0' : '2,3'" stroke-width="0.5" />
              <path :d="chart.fillPath" fill="url(#eq-fill)" />
              <path :d="chart.benchPath" fill="none" stroke="#B8B4A8" stroke-width="1.2" stroke-dasharray="3,3" />
              <path :d="chart.equityPath" fill="none" stroke="#2456D8" stroke-width="1.6" />
              <circle :cx="chart.lastEquityX" :cy="chart.lastEquityY" r="3" fill="#2456D8" stroke="#fff" stroke-width="1.2" />
              <text v-for="m in chart.dateMarks" :key="m.x" :x="m.x" :y="chart.h - 6" font-size="9" fill="#B8B4A8" :text-anchor="m.anchor" font-family="IBM Plex Mono, monospace">{{ m.label }}</text>
            </svg>
          </div>

          <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '12px', paddingTop: '12px', marginTop: '8px', borderTop: `1px dashed ${A2.borderHair}` }">
            <div v-for="s in stats" :key="s.l">
              <div :style="{ fontSize: '10px', color: A2.textMuted, fontWeight: 500, marginBottom: '2px' }">{{ s.l }}</div>
              <div :style="{ fontSize: '14px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', color: s.tone, letterSpacing: '-0.3px' }">{{ s.v }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Qwen daily review -->
      <div :style="{ background: A2.qwenGradSoft, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', padding: '12px 16px', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '14px', boxShadow: A2.shadow }">
        <div :style="{ width: '30px', height: '30px', background: A2.qwenGrad, color: '#fff', display: 'grid', placeItems: 'center', fontSize: '13px', fontWeight: 800, borderRadius: '7px', flexShrink: 0, boxShadow: '0 2px 6px rgba(36,86,216,0.25)' }">千</div>
        <div style="flex:1">
          <div :style="{ fontSize: '11px', color: A2.qwenDeep, fontWeight: 700, letterSpacing: '0.4px', marginBottom: '2px', textTransform: 'uppercase' }">千问每日组合体检</div>
          <div :style="{ fontSize: '12px', color: A2.textSub, lineHeight: 1.55 }">
            整体配置<strong>偏成长</strong>，集中度<strong :style="{ color: A2.amber }">偏高</strong>（前 3 占 63.8%）。建议关注：<strong>宁德时代</strong>放量已达止盈线、<strong>隆基绿能</strong>跌破支撑可考虑止损。新能源板块整体仓位 47%，建议降至 35% 以下以平衡风险。
          </div>
        </div>
        <button :style="{ padding: '7px 14px', background: A2.qwenGrad, color: '#fff', border: 'none', borderRadius: '6px', fontSize: '11px', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px', flexShrink: 0, boxShadow: '0 2px 6px rgba(36,86,216,0.25)' }">
          <Icon name="sparkle" :size="11" /> 让千问优化组合
        </button>
      </div>

      <!-- Holdings + sidebar -->
      <div :style="{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '10px' }">
        <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', overflow: 'hidden', boxShadow: A2.shadow }">
          <div :style="{ display: 'flex', alignItems: 'center', padding: '12px 16px', borderBottom: `1px solid ${A2.borderHair}` }">
            <div :style="{ display: 'flex', alignItems: 'center', gap: '8px' }">
              <div :style="{ fontSize: '13px', fontWeight: 700 }">{{ view === '自选' ? '自选股' : view === '千问跟踪' ? '千问跟踪' : '持仓明细' }}</div>
              <span v-if="view === '持仓' || view === '千问跟踪'" :style="{ fontSize: '9px', padding: '2px 6px', background: A2.amberSoft, color: A2.amber, borderRadius: '3px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace' }">DEMO</span>
            </div>
            <div style="flex:1" />
            <div :style="{ display: 'flex', gap: '2px', padding: '3px', background: A2.bgDeep, borderRadius: '6px' }">
              <div v-for="t in ['持仓', '自选', '千问跟踪']" :key="t" @click="view = t"
                   :style="{ padding: '4px 11px', background: view === t ? A2.surface : 'transparent', color: view === t ? A2.text : A2.textMuted, fontSize: '11px', fontWeight: 600, cursor: 'pointer', borderRadius: '4px', boxShadow: view === t ? A2.shadow : 'none' }">{{ t }}</div>
            </div>
            <div :style="{ marginLeft: '10px', fontSize: '11px', color: A2.textMuted, display: 'flex', alignItems: 'center', gap: '5px', cursor: 'pointer' }">
              <Icon name="plus" :size="11" /> 添加
            </div>
          </div>
          <!-- 自选 tab：使用本地 watchlist store -->
          <table v-if="view === '自选'" :style="{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }">
            <thead>
              <tr :style="{ color: A2.textMuted, fontSize: '10px', fontWeight: 600, letterSpacing: '0.5px' }">
                <th :style="{ textAlign: 'left', padding: '8px 16px', fontWeight: 600 }">名称 / 代码</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">加入价</th>
                <th :style="{ textAlign: 'left', padding: '8px 12px', fontWeight: 600 }">行业</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">预警</th>
                <th :style="{ textAlign: 'right', padding: '8px 16px', fontWeight: 600 }">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!wl.items.length">
                <td colspan="5" :style="{ padding: 0 }">
                  <EmptyState icon="⭐" title="自选列表为空" subtitle="在 ⌘K 搜索 / 行情 / 因子 / 详情页点 ⭐ 加入" />
                </td>
              </tr>
              <tr v-for="w in wl.items" :key="w.code" class="row-hover" @click="gotoDetail(w.code)" :style="{ borderTop: `1px solid ${A2.borderHair}`, cursor: 'pointer' }">
                <td :style="{ padding: '11px 16px' }">
                  <div :style="{ display: 'flex', alignItems: 'center', gap: '8px' }">
                    <StarButton :stock="{ code: w.code, name: w.name, sector: w.sector, refPrice: w.refPrice }" :size="13" @click.stop />
                    <div>
                      <div :style="{ fontWeight: 600, fontSize: '13px' }">{{ w.name || '—' }}</div>
                      <div :style="{ fontSize: '10px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace' }">{{ w.code }}</div>
                    </div>
                  </div>
                </td>
                <td :style="{ padding: '11px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ w.refPrice != null ? w.refPrice.toFixed(2) : '—' }}</td>
                <td :style="{ padding: '11px 12px', color: A2.textSub, fontSize: '11.5px' }">{{ w.sector || '—' }}</td>
                <td :style="{ padding: '11px 6px', textAlign: 'right' }">
                  <span v-if="w.alerts.length" :style="{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '2px 8px', background: A2.qwenSoft, color: A2.qwenDeep, borderRadius: '4px', fontSize: '11px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace' }">
                    <Icon name="bell" :size="10" /> {{ w.alerts.length }}
                  </span>
                  <span v-else :style="{ color: A2.textDim, fontSize: '11px' }">无</span>
                </td>
                <td :style="{ padding: '11px 16px', textAlign: 'right' }" @click.stop>
                  <AlertRuleEditor :code="w.code" />
                </td>
              </tr>
            </tbody>
          </table>

          <!-- 持仓 / 千问跟踪 tab：原 mock 数据 -->
          <table v-else :style="{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }">
            <thead>
              <tr :style="{ color: A2.textMuted, fontSize: '10px', fontWeight: 600, letterSpacing: '0.5px' }">
                <th :style="{ textAlign: 'left', padding: '8px 16px', fontWeight: 600 }">名称 / 代码</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">现价</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">涨跌</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">持仓</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">成本</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">盈亏</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">占比</th>
                <th :style="{ textAlign: 'left', padding: '8px 12px', fontWeight: 600 }">千问观点</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="h in holdings" :key="h.code" class="row-hover row-clickable" @click="gotoDetail(h.code)" :style="{ borderTop: `1px solid ${A2.borderHair}` }">
                <td :style="{ padding: '11px 16px' }">
                  <div :style="{ display: 'flex', alignItems: 'center', gap: '8px' }">
                    <Icon name="starF" :size="12" color="#F59E0B" />
                    <div>
                      <div :style="{ fontWeight: 600, fontSize: '13px' }">{{ h.name }}</div>
                      <div :style="{ fontSize: '10px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace' }">{{ h.code }} · {{ h.sector }}</div>
                    </div>
                  </div>
                </td>
                <td :style="{ padding: '11px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: h.price >= h.cost ? A2.up : A2.down }">{{ h.price.toFixed(2) }}</td>
                <td :style="{ padding: '11px 6px', textAlign: 'right' }"><PctChip :pct="((h.price - h.cost) / h.cost) * 100" size="sm" /></td>
                <td :style="{ padding: '11px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub, fontSize: '11px' }">{{ h.qty.toLocaleString() }}</td>
                <td :style="{ padding: '11px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textMuted, fontSize: '11px' }">{{ h.cost.toFixed(2) }}</td>
                <td :style="{ padding: '11px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: (h.price - h.cost) * h.qty >= 0 ? A2.up : A2.down }">{{ (h.price - h.cost) * h.qty >= 0 ? '+' : '' }}{{ Math.round((h.price - h.cost) * h.qty).toLocaleString() }}</td>
                <td :style="{ padding: '11px 6px', textAlign: 'right' }">
                  <div :style="{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '6px' }">
                    <div :style="{ width: '36px', height: '4px', background: A2.bgDeep, borderRadius: '2px', overflow: 'hidden' }">
                      <div :style="{ width: `${Math.min(100, h.weight * 3)}%`, height: '100%', background: A2.qwen }" />
                    </div>
                    <span :style="{ fontFamily: 'IBM Plex Mono, monospace', fontSize: '11px', color: A2.textSub, fontWeight: 600 }">{{ h.weight.toFixed(1) }}%</span>
                  </div>
                </td>
                <td :style="{ padding: '11px 12px', minWidth: '220px' }">
                  <div :style="{ display: 'flex', flexDirection: 'column', gap: '3px' }">
                    <span :style="{ fontSize: '10px', padding: '2px 7px', background: toneColor(h.qwen.tone) + '15', color: toneColor(h.qwen.tone), borderRadius: '4px', fontWeight: 600, whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'center', gap: '3px', alignSelf: 'flex-start' }">
                      <Icon name="sparkle" :size="9" /> {{ h.qwen.tag }}
                    </span>
                    <span :style="{ fontSize: '11px', color: A2.textMuted, lineHeight: 1.45 }">{{ h.qwen.note }}</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Right column -->
        <div :style="{ display: 'flex', flexDirection: 'column', gap: '10px' }">
          <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', padding: '14px', boxShadow: A2.shadow }">
            <div :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }">
              <div :style="{ display: 'flex', alignItems: 'center', gap: '6px' }">
                <div :style="{ fontSize: '13px', fontWeight: 700 }">行业配置</div>
                <span :style="{ fontSize: '9px', padding: '2px 6px', background: A2.amberSoft, color: A2.amber, borderRadius: '3px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace' }">DEMO</span>
              </div>
              <span :style="{ fontSize: '10px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace' }">8 持仓</span>
            </div>
            <div :style="{ display: 'flex', alignItems: 'center', gap: '12px' }">
              <svg :width="donutArcs.size" :height="donutArcs.size" :viewBox="`0 0 ${donutArcs.size} ${donutArcs.size}`">
                <path v-for="(a, i) in donutArcs.arcs" :key="i" :d="a.d" :fill="a.c" />
                <circle :cx="donutArcs.cx" :cy="donutArcs.cy" :r="donutArcs.r * 0.62" fill="#fff" />
                <text :x="donutArcs.cx" :y="donutArcs.cy - 2" text-anchor="middle" font-size="10" fill="#7A776F" font-weight="500">总市值</text>
                <text :x="donutArcs.cx" :y="donutArcs.cy + 12" text-anchor="middle" font-size="13" fill="#0E0E0C" font-weight="700" font-family="IBM Plex Mono, monospace">128.5万</text>
              </svg>
              <div :style="{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }">
                <div v-for="s in sectorAlloc" :key="s.l" :style="{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px' }">
                  <div :style="{ width: '8px', height: '8px', background: s.c, borderRadius: '2px' }" />
                  <span :style="{ flex: 1, color: A2.textSub }">{{ s.l }}</span>
                  <span :style="{ fontFamily: 'IBM Plex Mono, monospace', color: A2.text, fontWeight: 600 }">{{ s.v }}%</span>
                </div>
              </div>
            </div>
          </div>

          <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', overflow: 'hidden', boxShadow: A2.shadow, flex: 1 }">
            <div :style="{ padding: '12px 16px', borderBottom: `1px solid ${A2.borderHair}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }">
              <div :style="{ display: 'flex', alignItems: 'center', gap: '6px' }">
                <div :style="{ fontSize: '13px', fontWeight: 700 }">千问预警</div>
                <span :style="{ fontSize: '9px', padding: '2px 6px', background: A2.amberSoft, color: A2.amber, borderRadius: '3px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace' }">DEMO</span>
              </div>
              <span :style="{ fontSize: '10px', padding: '2px 6px', background: A2.upSoft, color: A2.up, borderRadius: '3px', fontWeight: 600, fontFamily: 'IBM Plex Mono, monospace' }">3 条新</span>
            </div>
            <div>
              <div v-for="(a, i) in alerts" :key="i" :style="{ padding: '10px 16px', borderTop: i ? `1px solid ${A2.borderHair}` : 'none', display: 'flex', gap: '8px' }">
                <div :style="{ width: '3px', alignSelf: 'stretch', background: a.tone, borderRadius: '2px', flexShrink: 0 }" />
                <div style="flex:1">
                  <div :style="{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }">
                    <span :style="{ fontSize: '9px', padding: '1px 6px', background: a.tone + '15', color: a.tone, borderRadius: '3px', fontWeight: 700 }">{{ a.tag }}</span>
                    <span :style="{ fontSize: '12px', fontWeight: 700 }">{{ a.stock }}</span>
                    <span :style="{ marginLeft: 'auto', fontSize: '10px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace' }">{{ a.time }}</span>
                  </div>
                  <div :style="{ fontSize: '11px', color: A2.textSub, lineHeight: 1.5 }">{{ a.desc }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Shell>
</template>

<style scoped>
.row-hover { transition: background 0.15s; }
.row-hover:hover { background: #EFEDE6; }
</style>
