<script setup>
import { computed, ref } from 'vue'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import { A2 } from '../shared/theme.js'
import { seededRand } from '../shared/data.js'

function heatBg(r, yi, mi) {
  if (yi === 1 && mi > 4) return '#EFEDE6'
  const intensity = Math.min(1, Math.abs(r) / 6)
  return r >= 0
    ? `rgba(220,38,38,${0.18 + intensity * 0.6})`
    : `rgba(5,150,105,${0.18 + intensity * 0.6})`
}

const activeStrategy = ref(0)

const strategies = [
  { id: 0, name: '高股息防御', ret: 18.4, dd: -6.2, sharpe: 1.62, tag: '稳健', tone: 'up', author: '千问出品' },
  { id: 1, name: '动量突破 60D', ret: 42.8, dd: -14.8, sharpe: 1.94, tag: '激进', tone: 'amber', author: '千问出品' },
  { id: 2, name: '低估值 + 机构买入', ret: 26.1, dd: -9.4, sharpe: 1.78, tag: '平衡', tone: 'qwen', author: '我的策略' },
  { id: 3, name: 'AI 算力链龙头轮动', ret: 58.2, dd: -22.6, sharpe: 1.71, tag: '主题', tone: 'up', author: '我的策略' },
]

const equityData = computed(() => {
  const r1 = seededRand(101 + activeStrategy.value)
  const r2 = seededRand(202 + activeStrategy.value)
  const strat = []
  const bench = []
  let v = 1.0, b = 1.0
  for (let i = 0; i < 250; i++) {
    v *= 1 + (r1() - 0.43) * 0.018
    b *= 1 + (r2() - 0.495) * 0.012
    strat.push(v)
    bench.push(b)
  }
  return { strat, bench }
})

const monthlyRets = [
  [3.2, 1.8, -2.1, 4.5, 2.2, -0.8, 5.1, 3.8, -1.4, 2.9, 4.2, 3.1],
  [-1.4, 2.6, 3.9, 1.2, -3.2, 4.8, 2.1, 5.5, 3.4, -2.1, 1.8, 6.2],
]
const monthLabels = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']

const summary = [
  { l: '累计收益', v: '+58.2%', s: 'vs 沪深 +12.4%', tone: A2.up, big: true },
  { l: '年化收益', v: '+24.6%', s: 'α +9.8%', tone: A2.up },
  { l: '最大回撤', v: '-8.6%', s: '2025-04-12', tone: A2.down },
  { l: '夏普比率', v: '1.84', s: '> 1.5 优秀', tone: A2.text },
  { l: '胜率', v: '64.2%', s: '212 / 330 笔', tone: A2.text },
  { l: '盈亏比', v: '2.18', s: '平均盈/亏', tone: A2.qwen },
]

const entryRules = [
  { k: '股息率', op: '≥', v: '4%' },
  { k: 'PE (TTM)', op: '<', v: '20' },
  { k: 'ROE', op: '≥', v: '12%' },
  { k: '市值', op: '>', v: '500 亿' },
]

const sizingCells = [
  { l: '持仓数', v: '15 只' },
  { l: '权重', v: '等权' },
  { l: '调仓周期', v: '月度' },
  { l: '止损线', v: '-15%' },
]

const trades = [
  { d: '2026-04-28', side: 'SELL', stock: '寒武纪', code: '688256.SH', px: 412.80, qty: 200, hold: 42, pnl: 18420, trigger: '触发止盈线 +20%' },
  { d: '2026-04-25', side: 'BUY', stock: '迈瑞医疗', code: '300760.SZ', px: 285.60, qty: 200, hold: 0, pnl: 0, trigger: 'PE<25 + 机构买入信号' },
  { d: '2026-04-22', side: 'SELL', stock: '隆基绿能', code: '601012.SH', px: 21.45, qty: 1500, hold: 87, pnl: -8025, trigger: '跌破止损线 -15%' },
  { d: '2026-04-18', side: 'BUY', stock: '中芯国际', code: '688981.SH', px: 78.45, qty: 500, hold: 0, pnl: 0, trigger: '60D 突破 + 量能放大' },
  { d: '2026-04-15', side: 'BUY', stock: '宁德时代', code: '300750.SZ', px: 245.30, qty: 300, hold: 0, pnl: 0, trigger: '动量因子触发' },
  { d: '2026-04-12', side: 'SELL', stock: '比亚迪', code: '002594.SZ', px: 254.20, qty: 200, hold: 28, pnl: 4280, trigger: '月度调仓再平衡' },
]

// chart paths
const chart = computed(() => {
  const { strat, bench } = equityData.value
  const w = 900, h = 240, pad = { l: 40, r: 12, t: 12, b: 26 }
  const all = [...strat, ...bench]
  const min = Math.min(...all) * 0.98, max = Math.max(...all) * 1.02
  const xStep = (w - pad.l - pad.r) / (strat.length - 1)
  const yScale = (v) => pad.t + (h - pad.t - pad.b) * (1 - (v - min) / (max - min))
  const stratPath = strat.map((v, i) => `${i === 0 ? 'M' : 'L'} ${pad.l + i * xStep} ${yScale(v)}`).join(' ')
  const benchPath = bench.map((v, i) => `${i === 0 ? 'M' : 'L'} ${pad.l + i * xStep} ${yScale(v)}`).join(' ')
  const fillPath = `${stratPath} L ${pad.l + (strat.length - 1) * xStep} ${h - pad.b} L ${pad.l} ${h - pad.b} Z`
  const peakIdx = strat.indexOf(Math.max(...strat.slice(0, 200)))
  const troughIdx = strat.indexOf(Math.min(...strat.slice(peakIdx, peakIdx + 30)), peakIdx)

  const yTicks = 5
  const yLines = []
  for (let i = 0; i < yTicks; i++) {
    const v = min + (max - min) * (i / (yTicks - 1))
    yLines.push({ v, y: yScale(v), edge: i === 0 || i === yTicks - 1 })
  }

  const dates = ['2024-01', '2024-06', '2024-11', '2025-04', '2025-09', '2026-04']
  const dateMarks = [0, 0.2, 0.4, 0.6, 0.8, 1].map((p, k) => ({
    x: pad.l + Math.floor(p * (strat.length - 1)) * xStep,
    label: dates[k],
    anchor: k === 0 ? 'start' : k === 5 ? 'end' : 'middle',
  }))

  return {
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
    drawdownW: (troughIdx - peakIdx) * xStep,
    midX: pad.l + ((peakIdx + troughIdx) / 2) * xStep,
  }
})

const ddRect = computed(() => chart.value.peakIdx > 0 && chart.value.troughIdx > chart.value.peakIdx)
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
          <div :style="{ fontSize: '12px', color: A2.textMuted, marginTop: '3px' }">用千问描述策略，或从模板出发 · 回测窗口 2024-01-01 至 2026-04-30</div>
        </div>
        <div :style="{ display: 'flex', gap: '8px' }">
          <button :style="{ padding: '8px 14px', background: A2.surface, border: `1px solid ${A2.borderHair}`, color: A2.textSub, fontSize: '12px', fontWeight: 600, borderRadius: '7px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px' }">
            <Icon name="bookmark" :size="11" /> 我的策略 (4)
          </button>
          <button :style="{ padding: '8px 14px', background: A2.qwenGrad, border: 'none', color: '#fff', fontSize: '12px', fontWeight: 600, borderRadius: '7px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px', boxShadow: '0 2px 6px rgba(36,86,216,0.25)' }">
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
            <div v-for="(s, i) in strategies" :key="s.id" @click="activeStrategy = i"
                 class="strategy-item"
                 :data-active="activeStrategy === i ? 'true' : 'false'"
                 :style="{ padding: '11px 14px', borderTop: i ? `1px solid ${A2.borderHair}` : 'none', cursor: 'pointer', background: activeStrategy === i ? A2.qwenGradSoft : 'transparent', borderLeft: activeStrategy === i ? `3px solid ${A2.qwen}` : '3px solid transparent', transition: 'background 0.15s, border-color 0.15s' }">
              <div :style="{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }">
                <span :style="{ fontSize: '13px', fontWeight: 700, color: A2.text }">{{ s.name }}</span>
                <span :style="{ fontSize: '9px', padding: '1px 5px', background: A2.bgDeep, color: A2.textMuted, borderRadius: '3px', fontWeight: 600 }">{{ s.tag }}</span>
              </div>
              <div :style="{ display: 'flex', gap: '12px', fontSize: '10px', fontFamily: 'IBM Plex Mono, monospace' }">
                <span :style="{ color: A2.textMuted }">年化 <span :style="{ color: A2.up, fontWeight: 700 }">+{{ s.ret }}%</span></span>
                <span :style="{ color: A2.textMuted }">回撤 <span :style="{ color: A2.down, fontWeight: 700 }">{{ s.dd }}%</span></span>
                <span :style="{ color: A2.textMuted }">夏普 <span :style="{ color: A2.text, fontWeight: 700 }">{{ s.sharpe }}</span></span>
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
                <span :style="{ fontSize: '10px', color: A2.qwen, cursor: 'pointer' }">+ 添加</span>
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

            <div :style="{ marginBottom: '14px' }">
              <div :style="{ fontSize: '10px', color: A2.textMuted, fontWeight: 600, marginBottom: '5px', letterSpacing: '0.4px', textTransform: 'uppercase' }">回测窗口</div>
              <div :style="{ display: 'flex', gap: '4px' }">
                <div :style="{ flex: 1, padding: '6px 9px', background: A2.bgDeep, border: `1px solid ${A2.borderHair}`, borderRadius: '5px', fontSize: '11px', fontFamily: 'IBM Plex Mono, monospace', color: A2.text, fontWeight: 600 }">2024-01-01</div>
                <span :style="{ alignSelf: 'center', color: A2.textMuted, fontSize: '11px' }">至</span>
                <div :style="{ flex: 1, padding: '6px 9px', background: A2.bgDeep, border: `1px solid ${A2.borderHair}`, borderRadius: '5px', fontSize: '11px', fontFamily: 'IBM Plex Mono, monospace', color: A2.text, fontWeight: 600 }">2026-04-30</div>
              </div>
            </div>

            <button :style="{ width: '100%', padding: '10px', background: A2.text, color: '#fff', border: 'none', borderRadius: '7px', fontSize: '12px', fontWeight: 700, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }">
              <Icon name="play" :size="11" /> 运行回测
            </button>
          </div>
        </div>

        <!-- Right results -->
        <div :style="{ display: 'flex', flexDirection: 'column', gap: '10px' }">
          <!-- Summary metrics -->
          <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '8px' }">
            <div v-for="m in summary" :key="m.l" :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '9px', padding: '12px 14px', boxShadow: A2.shadow, position: 'relative', overflow: 'hidden' }">
              <div v-if="m.big" :style="{ position: 'absolute', left: 0, top: 0, bottom: 0, width: '3px', background: m.tone }" />
              <div :style="{ fontSize: '10px', color: A2.textMuted, fontWeight: 600, letterSpacing: '0.4px', textTransform: 'uppercase', marginBottom: '4px' }">{{ m.l }}</div>
              <div :style="{ fontSize: m.big ? '22px' : '18px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', color: m.tone, letterSpacing: '-0.5px' }">{{ m.v }}</div>
              <div :style="{ fontSize: '10px', color: A2.textMuted, marginTop: '2px', fontFamily: 'IBM Plex Mono, monospace' }">{{ m.s }}</div>
            </div>
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
                <text :x="chart.midX" :y="chart.pad.t + 13" font-size="9" fill="#059669" text-anchor="middle" font-weight="600" font-family="IBM Plex Mono, monospace">最大回撤 -8.6%</text>
              </g>

              <text v-for="m in chart.dateMarks" :key="m.x" :x="m.x" :y="chart.h - 8" font-size="9" fill="#7A776F" :text-anchor="m.anchor" font-family="IBM Plex Mono, monospace">{{ m.label }}</text>
            </svg>
          </div>

          <!-- Bottom row: Qwen + heatmap -->
          <div :style="{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: '10px' }">
            <div :style="{ background: A2.qwenGradSoft, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', padding: '16px', boxShadow: A2.shadow, position: 'relative', overflow: 'hidden' }">
              <div :style="{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }">
                <div :style="{ width: '26px', height: '26px', background: A2.qwenGrad, color: '#fff', display: 'grid', placeItems: 'center', fontSize: '12px', fontWeight: 800, borderRadius: '6px', boxShadow: '0 2px 6px rgba(36,86,216,0.25)' }">千</div>
                <div :style="{ fontSize: '13px', fontWeight: 700 }">千问回测点评</div>
                <span :style="{ marginLeft: 'auto', fontSize: '10px', color: A2.textMuted, padding: '2px 7px', background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '3px', fontFamily: 'IBM Plex Mono, monospace' }">评级 A-</span>
              </div>
              <div :style="{ fontSize: '12px', color: A2.textSub, lineHeight: 1.7, marginBottom: '10px' }">
                策略整体表现 <strong :style="{ color: A2.up }">优于沪深 300</strong> 共 45.8 个百分点。<strong>2025 Q3 - Q4</strong> 是主要收益来源（AI 算力链行情）；<strong>2025-04</strong> 出现最大回撤，主因美联储加息预期 + 半导体调整，但策略在 3 周内恢复。建议关注：当前持仓集中度偏高，可加入<strong :style="{ color: A2.qwen }">行业分散度因子</strong>降低单一行业风险。
              </div>
              <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', paddingTop: '10px', borderTop: `1px dashed ${A2.borderHair}` }">
                <div v-for="m in [{ l: '与沪深300相关性', v: '0.62' }, { l: '信息比率 IR', v: '1.24' }, { l: 'Calmar 比率', v: '2.86' }]" :key="m.l">
                  <div :style="{ fontSize: '9px', color: A2.textMuted, marginBottom: '2px', fontWeight: 600, letterSpacing: '0.3px' }">{{ m.l }}</div>
                  <div :style="{ fontSize: '14px', fontWeight: 700, color: A2.text, fontFamily: 'IBM Plex Mono, monospace' }">{{ m.v }}</div>
                </div>
              </div>
              <div :style="{ display: 'flex', gap: '6px', marginTop: '12px' }">
                <button :style="{ padding: '6px 12px', background: A2.qwenGrad, color: '#fff', border: 'none', borderRadius: '5px', fontSize: '11px', fontWeight: 600, cursor: 'pointer' }">采纳建议优化</button>
                <button :style="{ padding: '6px 12px', background: A2.surface, color: A2.textSub, border: `1px solid ${A2.borderHair}`, borderRadius: '5px', fontSize: '11px', fontWeight: 600, cursor: 'pointer' }">查看完整研报</button>
              </div>
            </div>

            <!-- Heatmap -->
            <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', padding: '14px', boxShadow: A2.shadow }">
              <div :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }">
                <div :style="{ fontSize: '12px', fontWeight: 700 }">月度收益</div>
                <span :style="{ fontSize: '10px', color: A2.textMuted }">%</span>
              </div>
              <div :style="{ display: 'grid', gridTemplateColumns: '36px repeat(12, 1fr)', gap: '2px', fontSize: '9px', fontFamily: 'IBM Plex Mono, monospace' }">
                <div></div>
                <div v-for="m in monthLabels" :key="m" :style="{ textAlign: 'center', color: A2.textMuted, fontSize: '8px', padding: '2px 0' }">{{ m.replace('月', '') }}</div>
                <template v-for="(rets, yi) in monthlyRets" :key="yi">
                  <div :style="{ textAlign: 'right', color: A2.textMuted, alignSelf: 'center', fontSize: '9px', paddingRight: '4px' }">{{ [2025, 2026][yi] }}</div>
                  <div v-for="(r, mi) in rets" :key="mi"
                       :style="{ background: heatBg(r, yi, mi), padding: '6px 2px', textAlign: 'center', borderRadius: '3px', color: yi === 1 && mi > 4 ? A2.textDim : '#fff', fontWeight: 700, fontSize: '9px' }">
                    {{ yi === 1 && mi > 4 ? '—' : (r >= 0 ? '+' : '') + r.toFixed(1) }}
                  </div>
                </template>
              </div>

              <div :style="{ marginTop: '12px', paddingTop: '10px', borderTop: `1px dashed ${A2.borderHair}`, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }">
                <div v-for="s in [{ l: '盈利月', v: '17 / 22', tone: A2.up }, { l: '最佳月', v: '+6.2%', tone: A2.up }, { l: '亏损月', v: '5 / 22', tone: A2.down }, { l: '最差月', v: '-3.2%', tone: A2.down }]" :key="s.l" :style="{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }">
                  <span :style="{ color: A2.textMuted }">{{ s.l }}</span>
                  <span :style="{ fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: s.tone }">{{ s.v }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Trade log -->
          <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', overflow: 'hidden', boxShadow: A2.shadow }">
            <div :style="{ padding: '11px 16px', borderBottom: `1px solid ${A2.borderHair}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }">
              <div :style="{ fontSize: '12px', fontWeight: 700 }">近期交易记录</div>
              <div :style="{ fontSize: '10px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace' }">共 330 笔 · 显示 6 笔</div>
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
                <tr v-for="t in trades" :key="t.d + t.code" :style="{ borderTop: `1px solid ${A2.borderHair}` }">
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
</style>
