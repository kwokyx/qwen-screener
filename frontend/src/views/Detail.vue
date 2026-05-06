<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import PctChip from '../components/charts/PctChip.vue'
import Donut from '../components/charts/Donut.vue'
import FullCandle from '../components/charts/FullCandle.vue'
import { A2 } from '../shared/theme.js'
import { genKline } from '../shared/data.js'
import * as stockApi from '../api/stock'
import * as qwenApi from '../api/qwen'
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

const klineTabs = ['分时', '5日', '日K', '周K', '月K', '季K']
const indicators = ['MA', 'BOLL', 'MACD', 'KDJ', 'RSI']
const detailTabs = ['财务摘要', '估值', '基本信息']

async function load() {
  loading.value = true
  errorMsg.value = ''
  aiText.value = ''
  try {
    const [d, kl] = await Promise.all([
      stockApi.detail(code.value),
      stockApi.kline(code.value, 80).catch(() => []),
    ])
    detail.value = d
    // K 线后端返回时间倒序，需要反转给画图用
    if (Array.isArray(kl) && kl.length > 0) {
      klineData.value = [...kl].reverse().map((k) => ({
        o: k.open,
        c: k.close,
        h: k.high,
        l: k.low,
        v: k.volume,
        day: k.trade_date,
      }))
    } else {
      // 后端没历史时，用确定性 mock 占位
      const base = d.latest?.close || 100
      klineData.value = genKline(base * 0.85, 80, 0.025, 99)
    }
  } catch (e) {
    errorMsg.value = e.response?.data?.detail || e.message
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
        aiError.value = ev.message || '生成失败'
      }
    }, aiAbort.signal)
  } catch (e) {
    if (e.name !== 'AbortError') {
      aiError.value = e.response?.data?.detail || e.message || '请求失败'
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

// 8 个 header 指标
const headerMetrics = computed(() => {
  const l = detail.value?.latest
  if (!l) return []
  const fmt = (v, d = 2) => v == null ? '—' : v.toFixed(d)
  return [
    { l: '今开', v: fmt(l.open), c: A2.text },
    { l: '最高', v: fmt(l.high), c: l.high > l.open ? A2.up : A2.text },
    { l: '最低', v: fmt(l.low), c: l.low < l.open ? A2.down : A2.text },
    { l: '成交量', v: l.volume != null ? (l.volume / 1e8).toFixed(2) + '亿' : '—', c: A2.text },
    { l: '换手率', v: fmt(l.turnover) + '%', c: A2.text },
    { l: '市盈率', v: fmt(l.pe), c: A2.text },
    { l: '市净率', v: fmt(l.pb), c: A2.text },
    { l: '总市值', v: l.market_cap != null ? Math.round(l.market_cap).toLocaleString() + '亿' : '—', c: A2.text },
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
      <div :style="{ background: A2.upSoft, color: A2.up, padding: '20px 28px', borderRadius: '10px', fontSize: '13px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px', maxWidth: '460px', textAlign: 'center' }">
        <Icon name="alert" :size="18" />
        <div :style="{ fontWeight: 600 }">加载失败</div>
        <div :style="{ fontSize: '12px' }">{{ errorMsg }}</div>
        <button class="btn-primary" @click="load">
          <Icon name="refresh" :size="12" /> 重试
        </button>
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
                    :style="{ padding: '8px 16px', background: aiStreaming ? '#3F3D38' : A2.qwenGrad, color: '#fff', border: 'none', fontSize: '12px', fontWeight: 600, cursor: 'pointer', borderRadius: '7px', display: 'flex', alignItems: 'center', gap: '5px', boxShadow: '0 2px 8px rgba(14,14,12,0.12)' }">
              <Icon :name="aiStreaming ? 'x' : 'sparkle'" :size="12" />
              {{ aiStreaming ? '停止' : (aiText ? '重新生成' : '问千问') }}
            </button>
          </div>
        </div>
        <!-- Metrics row: own line, breathes -->
        <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: '12px', fontSize: '11px' }">
          <div v-for="(d, i) in headerMetrics" :key="i">
            <div :style="{ color: A2.textMuted, marginBottom: '2px', fontSize: '10px' }">{{ d.l }}</div>
            <div :style="{ fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: d.c, fontSize: '13px' }">{{ d.v }}</div>
          </div>
        </div>
      </div>

      <div :style="{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 380px', overflow: 'hidden' }">
        <!-- K-line + tabs -->
        <div :style="{ background: A2.surface, overflow: 'auto', padding: '14px', borderRight: `1px solid ${A2.borderHair}` }">
          <div :style="{ display: 'flex', gap: 0, borderBottom: `1px solid ${A2.borderHair}`, marginBottom: '10px' }">
            <div v-for="(t, i) in klineTabs" :key="t" :style="{ padding: '8px 16px', fontSize: '12px', color: i === 2 ? A2.text : A2.textMuted, fontWeight: i === 2 ? 700 : 500, cursor: 'pointer', borderBottom: i === 2 ? `2px solid ${A2.up}` : '2px solid transparent' }">{{ t }}</div>
            <div style="flex:1" />
            <div v-for="(t, i) in indicators" :key="t" :style="{ padding: '8px 12px', fontSize: '11px', color: i === 0 ? A2.qwenDeep : A2.textMuted, fontWeight: i === 0 ? 700 : 500, cursor: 'pointer' }">{{ t }}</div>
          </div>
          <div :style="{ position: 'relative', background: A2.bgDeep, borderRadius: '8px', padding: '10px' }">
            <FullCandle :data="klineData" :width="760" :height="340" />
          </div>

          <!-- Tabs below chart -->
          <div :style="{ display: 'flex', gap: 0, borderBottom: `1px solid ${A2.borderHair}`, marginTop: '18px' }">
            <div v-for="(t, i) in detailTabs" :key="t" :style="{ padding: '10px 16px', fontSize: '12px', color: i === 0 ? A2.text : A2.textMuted, fontWeight: i === 0 ? 700 : 500, cursor: 'pointer', borderBottom: i === 0 ? `2px solid ${A2.text}` : '2px solid transparent' }">{{ t }}</div>
          </div>
          <div :style="{ padding: '14px 4px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '18px' }">
            <div>
              <div :style="{ fontSize: '12px', fontWeight: 700, marginBottom: '10px' }">核心财务指标 · 最新报告期</div>
              <table :style="{ width: '100%', fontSize: '11.5px', borderCollapse: 'collapse' }">
                <tbody>
                  <tr v-for="(r, i) in finRows" :key="i" :style="{ borderTop: i === 0 ? 'none' : `1px solid ${A2.borderHair}` }">
                    <td :style="{ padding: '8px 8px', color: A2.textMuted, fontWeight: 500 }">{{ r.l }}</td>
                    <td :style="{ padding: '8px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: A2.text }">{{ r.v }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div>
              <div :style="{ fontSize: '12px', fontWeight: 700, marginBottom: '10px' }">基本信息</div>
              <div :style="{ fontSize: '11.5px', lineHeight: 1.9, color: A2.textSub }">
                <div>所属行业：<strong :style="{ color: A2.text }">{{ detail.industry || '—' }}</strong></div>
                <div>上市板块：<strong :style="{ color: A2.text }">{{ market }}</strong></div>
                <div>更新时间：<strong :style="{ color: A2.text, fontFamily: 'IBM Plex Mono, monospace' }">{{ detail.latest?.trade_date || '—' }}</strong></div>
              </div>
              <div :style="{ marginTop: '14px', padding: '10px 12px', background: A2.amberSoft, borderRadius: '7px', fontSize: '11px', color: A2.amber, lineHeight: 1.55, border: `1px solid ${A2.borderHair}` }">
                <Icon name="shield" :size="11" /> 数据仅供研究参考，不构成投资建议。
              </div>
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
                <div :style="{ fontSize: '11px', color: A2.textMuted }">综合评分（基于 PE / ROE / 股息率）</div>
                <div :style="{ fontSize: '18px', fontWeight: 800, color: A2.qwenDeep, letterSpacing: '-0.3px' }">
                  {{ bullScore >= 80 ? '强烈关注' : bullScore >= 60 ? '可关注' : '谨慎' }}
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
          <div v-if="aiText" :style="{ padding: '14px', background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', fontSize: '12.5px', lineHeight: 1.8, color: A2.textSub, whiteSpace: 'pre-wrap' }">
            {{ aiText }}<span v-if="aiStreaming" class="caret" />
          </div>
        </div>
      </div>
    </template>
  </Shell>
</template>

<style scoped>
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
