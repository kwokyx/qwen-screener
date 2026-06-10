<script setup>
import { computed, h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NGi,
  NGrid,
  NTabPane,
  NTag,
  NTabs,
} from 'naive-ui'
import Shell from '../components/Shell.vue'
import Sparkline from '../components/charts/Sparkline.vue'
import PctChip from '../components/charts/PctChip.vue'
import PctText from '../components/charts/PctText.vue'
import StarButton from '../components/StarButton.vue'
import { Preview } from '../shared/theme.js'
import { friendlyError } from '../shared/errors.js'
import * as marketApi from '../api/market'

const router = useRouter()

function gotoDetail(code) { router.push(`/detail/${code}`) }

const indices = ref([])
const sectors = ref([])
const movers = ref(null)
const tickerInfo = ref(null)
const moverTab = ref('gainers')
const loadingIndices = ref(true)
const loadingSectors = ref(true)
const loadingMovers = ref(true)
const loadingTicker = ref(true)
const indicesError = ref('')
const sectorsError = ref('')
const moversError = ref('')
const tickerError = ref('')
const errorMsg = ref('')

const moversShown = computed(() => (movers.value ? movers.value[moverTab.value] || [] : []))
const idxSpark = computed(() => indices.value.map((idx) => idx.spark || []))

const sectorsUp = computed(() => [...sectors.value].filter((s) => s.change_pct >= 0).sort((a, b) => b.change_pct - a.change_pct))
const sectorsDown = computed(() => [...sectors.value].filter((s) => s.change_pct < 0).sort((a, b) => a.change_pct - b.change_pct))

const marketStats = computed(() => {
  const t = tickerInfo.value
  if (!t) return null
  const advancers = Number(t.advancers || 0)
  const decliners = Number(t.decliners || 0)
  const total = advancers + decliners
  const advancerPct = total > 0 ? Math.round((advancers / total) * 100) : 50
  const declinerPct = total > 0 ? 100 - advancerPct : 50
  const breadthLabel = advancers > decliners ? '涨多跌少' : (decliners > advancers ? '跌多涨少' : '涨跌均衡')
  return {
    advancers,
    decliners,
    amount: t.total_amount_yi || 0,
    total,
    advancerPct,
    declinerPct,
    breadthLabel,
    tradeDate: t.trade_date,
  }
})

async function loadAll() {
  errorMsg.value = ''
  indicesError.value = ''
  sectorsError.value = ''
  moversError.value = ''
  tickerError.value = ''
  loadingIndices.value = true
  loadingSectors.value = true
  loadingMovers.value = true
  loadingTicker.value = true

  try {
    const overview = await marketApi.overview({ sectorLimit: 100, moversLimit: 10 })
    indices.value = overview.indices || []
    sectors.value = overview.sectors || []
    movers.value = overview.movers || null
    tickerInfo.value = overview.ticker || null
    loadingIndices.value = false
    loadingSectors.value = false
    loadingMovers.value = false
    loadingTicker.value = false
    return
  } catch {
    // The aggregate endpoint is an optimization. Keep the older split requests
    // as a compatibility fallback during rolling Railway deploys.
  }

  const results = await Promise.allSettled([
    marketApi.indices()
      .then((d) => { indices.value = d })
      .catch((e) => {
        indices.value = []
        indicesError.value = friendlyError(e)
        throw e
      })
      .finally(() => { loadingIndices.value = false }),
    marketApi.sectors(100)
      .then((d) => { sectors.value = d })
      .catch((e) => {
        sectors.value = []
        sectorsError.value = friendlyError(e)
        throw e
      })
      .finally(() => { loadingSectors.value = false }),
    marketApi.movers(10).then((d) => {
      movers.value = d
    }).catch((e) => {
      movers.value = null
      moversError.value = friendlyError(e)
      throw e
    }).finally(() => { loadingMovers.value = false }),
    marketApi.ticker().then((d) => {
      tickerInfo.value = d
    }).catch((e) => {
      tickerInfo.value = null
      tickerError.value = friendlyError(e)
      throw e
    }).finally(() => { loadingTicker.value = false }),
  ])
  const failed = results.filter((r) => r.status === 'rejected')
  if (failed.length === results.length) errorMsg.value = friendlyError(failed[0].reason)
}

const moverTabs = [
  { id: 'gainers', label: '涨幅榜' },
  { id: 'losers', label: '跌幅榜' },
  { id: 'by_amount', label: '成交额' },
  { id: 'by_turnover', label: '换手率' },
]

const tipsByTab = {
  gainers: '今日涨幅前 10',
  losers: '今日跌幅前 10',
  by_amount: '成交额最活跃',
  by_turnover: '换手率最高',
}

function mono(text, extra = {}) {
  return h('span', {
    style: {
      fontFamily: 'IBM Plex Mono, ui-monospace, SFMono-Regular, Menlo, monospace',
      ...extra,
    },
  }, text)
}

function formatAmount(v) {
  return v != null ? `${Number(v).toFixed(1)}亿` : '—'
}

function formatInt(v) {
  return String(Math.round(Number(v || 0)))
}

function formatMarketCap(v) {
  return v != null ? `${Math.round(v).toLocaleString()}亿` : '—'
}

function formatPe(v, digits = 1) {
  if (v == null) return '—'
  return Number(v) > 0 ? Number(v).toFixed(digits) : '亏损'
}

const moverColumns = computed(() => [
  {
    title: '代码',
    key: 'code',
    width: 92,
    render: (s) => mono(s.code.replace(/\.(SH|SZ|BJ)$/, ''), { color: Preview.textMuted, fontSize: '12px' }),
  },
  {
    title: '名称',
    key: 'name',
    minWidth: 140,
    render: (s) => h('div', { class: 'stock-name-cell' }, [
      h(StarButton, { stock: { code: s.code, name: s.name, sector: s.industry, refPrice: s.close }, size: 12 }),
      h('span', { class: 'stock-name-text' }, s.name),
    ]),
  },
  {
    title: '现价',
    key: 'close',
    align: 'right',
    width: 96,
    render: (s) => mono(s.close != null ? s.close.toFixed(2) : '—', {
      color: (s.change_pct || 0) >= 0 ? Preview.positive : Preview.negative,
      fontWeight: 800,
    }),
  },
  {
    title: '涨跌幅',
    key: 'change_pct',
    align: 'right',
    width: 96,
    render: (s) => s.change_pct != null
      ? h(PctChip, { pct: s.change_pct, size: 'sm' })
      : mono('—', { color: Preview.textFaint }),
  },
  {
    title: '成交额',
    key: 'amount',
    align: 'right',
    width: 96,
    render: (s) => mono(formatAmount(s.amount), { color: Preview.textMain }),
  },
  {
    title: '换手率',
    key: 'turnover',
    align: 'right',
    width: 86,
    render: (s) => mono(s.turnover != null ? `${s.turnover.toFixed(2)}%` : '—', { color: Preview.textMuted }),
  },
  {
    title: '市盈率',
    key: 'pe',
    align: 'right',
    width: 86,
    render: (s) => mono(formatPe(s.pe), { color: Preview.textMuted }),
  },
  {
    title: '市值',
    key: 'market_cap',
    align: 'right',
    width: 110,
    render: (s) => mono(formatMarketCap(s.market_cap), { color: Preview.textMain }),
  },
])

function moverRowProps(row) {
  return {
    class: 'clickable-row',
    onClick: () => gotoDetail(row.code),
  }
}

function sectorBarWidth(pct) {
  return `${Math.min(100, Math.max(10, Math.abs(Number(pct || 0)) * 10))}%`
}

onMounted(loadAll)
</script>

<template>
  <Shell>
    <div class="dashboard-page">
      <div class="market-overview-grid">
        <div class="indices-grid">
          <template v-if="loadingIndices && !indices.length">
            <NCard v-for="(_, n) in 6" :key="'idx-sk-' + n" class="terminal-card index-card" :bordered="false">
              <div class="index-skeleton">
                <span class="sk-line short"></span>
                <span class="sk-line value"></span>
                <span class="sk-line mini"></span>
              </div>
            </NCard>
          </template>
          <NCard v-else-if="indicesError" class="terminal-card index-card status-card" :bordered="false">
            <div class="status-title">指数加载失败</div>
            <div class="status-desc">{{ indicesError }}</div>
            <NButton size="tiny" secondary @click="loadAll">重试</NButton>
          </NCard>
          <template v-else>
            <NCard v-for="(idx, i) in indices" :key="idx.code" class="terminal-card index-card" :bordered="false">
              <div class="index-head">
                <div>
                  <div class="index-name">{{ idx.name }}</div>
                  <div class="index-code">{{ idx.code }} · {{ idx.constituents }} 只</div>
                </div>
                <Sparkline :data="idxSpark[i] || []" :color="idx.change_pct >= 0 ? '#C8312A' : '#0E8A66'" :fill="idx.change_pct >= 0 ? '#C8312A22' : '#0E8A6622'" :width="64" :height="24" />
              </div>
              <div class="index-value-row">
                <span class="index-value" :class="idx.change_pct >= 0 ? 'up' : 'down'">
                  {{ idx.value.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}
                </span>
                <span class="index-change" :class="idx.change_pct >= 0 ? 'up' : 'down'">
                  {{ idx.change >= 0 ? '+' : '' }}{{ idx.change.toFixed(2) }}
                </span>
                <PctText :pct="idx.change_pct" :size="11" />
              </div>
            </NCard>
          </template>
        </div>

        <NCard class="terminal-card market-card" :bordered="false">
          <div class="card-title-row">
            <span>市场概况</span>
            <NTag size="tiny" :bordered="false">{{ marketStats?.tradeDate || '—' }}</NTag>
          </div>
          <div v-if="loadingTicker && !marketStats" class="market-stats-skeleton">
            <span class="sk-metric"></span>
            <span class="sk-metric"></span>
            <span class="sk-metric wide"></span>
          </div>
          <div v-else-if="tickerError" class="status-block">
            <div class="status-title">概况加载失败</div>
            <div class="status-desc">{{ tickerError }}</div>
            <NButton size="tiny" secondary @click="loadAll">重试</NButton>
          </div>
          <div v-else-if="marketStats" class="market-summary">
            <div class="market-breadth-head">
              <span>市场宽度</span>
              <strong :class="marketStats.advancers >= marketStats.decliners ? 'up' : 'down'">
                {{ marketStats.breadthLabel }}
              </strong>
            </div>
            <div class="market-breadth-bar" aria-hidden="true">
              <span class="breadth-up" :style="{ width: marketStats.advancerPct + '%' }"></span>
              <span class="breadth-down" :style="{ width: marketStats.declinerPct + '%' }"></span>
            </div>
            <div class="market-breadth-counts">
              <span>上涨 {{ formatInt(marketStats.advancers) }}</span>
              <span>下跌 {{ formatInt(marketStats.decliners) }}</span>
            </div>
            <div class="market-stats">
              <div class="market-metric">
                <span>上涨占比</span>
                <strong>{{ marketStats.advancerPct }}<small>%</small></strong>
              </div>
              <div class="market-metric">
                <span>样本股票</span>
                <strong>{{ formatInt(marketStats.total) }}</strong>
              </div>
              <div class="market-metric">
                <span>总成交</span>
                <strong>{{ formatInt(marketStats.amount) }}<small>亿</small></strong>
              </div>
            </div>
          </div>
          <NEmpty v-else size="small" description="暂无市场概况" />
        </NCard>
      </div>

      <NAlert v-if="errorMsg" type="error" :bordered="false" class="dashboard-alert">
        <div class="alert-content">
          <span>{{ errorMsg }}</span>
          <NButton size="tiny" secondary :loading="loadingIndices || loadingSectors || loadingMovers" @click="loadAll">重试</NButton>
        </div>
      </NAlert>

      <NGrid :cols="24" :x-gap="20" :y-gap="20" responsive="screen" class="main-grid">
        <NGi :span="16" class="main-grid-item">
          <NCard class="terminal-card table-card" :bordered="false">
            <template #header>
              <div class="card-heading">
                <div>
                  <div class="card-title">市场异动</div>
                  <div class="card-subtitle">{{ tipsByTab[moverTab] }} · 点击进入个股</div>
                </div>
              </div>
            </template>
            <template #header-extra>
              <NTabs v-model:value="moverTab" type="bar" size="medium" animated>
                <NTabPane v-for="t in moverTabs" :key="t.id" :name="t.id" :tab="t.label" />
              </NTabs>
            </template>

            <div v-if="loadingMovers && !movers" class="table-skeleton movers-skeleton">
              <div v-for="n in 10" :key="'mv-sk-' + n" class="dashboard-skeleton-row">
                <span class="sk-cell code"></span>
                <span class="sk-cell name"></span>
                <span class="sk-cell num"></span>
                <span class="sk-cell chip"></span>
                <span class="sk-cell num"></span>
              </div>
            </div>
            <NAlert v-else-if="moversError" type="warning" :bordered="false" class="section-alert">
              <div class="alert-content">
                <span>市场异动加载失败：{{ moversError }}</span>
                <NButton size="tiny" secondary @click="loadAll">重试</NButton>
              </div>
            </NAlert>
            <NDataTable
              v-else
              :columns="moverColumns"
              :data="moversShown"
              :loading="loadingMovers"
              :pagination="false"
              :bordered="false"
              :single-line="false"
              :scroll-x="850"
              :row-key="(row) => row.code"
              :row-props="moverRowProps"
              size="small"
            >
              <template #empty>
                <NEmpty description="该榜单暂无数据" />
              </template>
            </NDataTable>
          </NCard>
        </NGi>

        <NGi :span="8" class="main-grid-item">
          <NCard class="terminal-card sector-card" :bordered="false">
            <template #header>
              <div>
                <div class="card-title">板块涨跌</div>
                <div class="card-subtitle">
                  本地行业 · 共 {{ sectors.length || '—' }} 个
                </div>
              </div>
            </template>

            <div v-if="loadingSectors && !sectors.length" class="sector-skeleton-grid">
              <div v-for="side in 2" :key="'sector-side-' + side" class="table-skeleton">
                <div v-for="n in 8" :key="'sector-sk-' + side + '-' + n" class="sector-skeleton-row">
                  <span class="sk-cell name"></span>
                  <span class="sk-cell chip"></span>
                </div>
              </div>
            </div>
            <NAlert v-else-if="sectorsError" type="warning" :bordered="false" class="section-alert">
              <div class="alert-content">
                <span>板块涨跌加载失败：{{ sectorsError }}</span>
                <NButton size="tiny" secondary @click="loadAll">重试</NButton>
              </div>
            </NAlert>
            <div v-else class="sector-rank-scroll">
              <div class="sector-rank-grid">
                <section class="sector-rank-group">
                  <div class="sector-rank-title">
                    <span>强势板块</span>
                    <span class="sector-count-pill is-up">{{ sectorsUp.length }}</span>
                  </div>
                  <div v-if="sectorsUp.length" class="sector-rank-list">
                    <div
                      v-for="(s, n) in sectorsUp"
                      :key="'sector-up-' + s.name"
                      class="sector-rank-row is-up"
                    >
                      <span class="sector-rank-num">{{ n + 1 }}</span>
                      <span class="sector-rank-main">
                        <span class="sector-rank-name">{{ s.name }}</span>
                        <span class="sector-rank-track">
                          <span class="sector-rank-bar" :style="{ width: sectorBarWidth(s.change_pct) }"></span>
                        </span>
                      </span>
                      <PctText :pct="s.change_pct" :size="12" />
                    </div>
                  </div>
                  <NEmpty v-else size="small" description="无上涨板块" />
                </section>

                <section class="sector-rank-group">
                  <div class="sector-rank-title">
                    <span>弱势板块</span>
                    <span class="sector-count-pill is-down">{{ sectorsDown.length }}</span>
                  </div>
                  <div v-if="sectorsDown.length" class="sector-rank-list">
                    <div
                      v-for="(s, n) in sectorsDown"
                      :key="'sector-down-' + s.name"
                      class="sector-rank-row is-down"
                    >
                      <span class="sector-rank-num">{{ n + 1 }}</span>
                      <span class="sector-rank-main">
                        <span class="sector-rank-name">{{ s.name }}</span>
                        <span class="sector-rank-track">
                          <span class="sector-rank-bar" :style="{ width: sectorBarWidth(s.change_pct) }"></span>
                        </span>
                      </span>
                      <PctText :pct="s.change_pct" :size="12" />
                    </div>
                  </div>
                  <NEmpty v-else size="small" description="无下跌板块" />
                </section>
              </div>
            </div>
          </NCard>
        </NGi>
      </NGrid>

    </div>
  </Shell>
</template>

<style scoped>
.dashboard-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.market-overview-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 320px);
  gap: 20px;
  align-items: start;
}

.indices-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 20px;
  min-width: 0;
}

.indices-grid .status-card {
  grid-column: 1 / -1;
}

.terminal-card {
  background: #F7F7F7;
  border-radius: 10px;
}

.terminal-card :deep(.n-card-header) {
  padding: 18px 22px 10px;
}

.terminal-card :deep(.n-card__content) {
  padding: 20px 24px 24px;
}

.index-card {
  min-height: 118px;
}

.index-head,
.card-title-row,
.alert-content {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.index-name,
.card-title {
  font-size: 15px;
  font-weight: 800;
  color: #111111;
  white-space: nowrap;
}

.index-code,
.card-subtitle {
  margin-top: 3px;
  font-size: 12px;
  color: #71717A;
}

.index-value-row {
  display: flex;
  align-items: baseline;
  gap: 7px;
  margin-top: 18px;
  min-width: 0;
  flex-wrap: wrap;
}

.index-value {
  font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: clamp(19px, 3vw, 23px);
  font-weight: 800;
  letter-spacing: -0.5px;
  white-space: nowrap;
}

.index-change {
  font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  font-weight: 700;
}

.up { color: #E04F76; }
.down { color: #16A35C; }

.market-card {
  align-self: start;
  min-height: 118px;
}

.status-card,
.status-block {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 8px;
}

.status-title {
  color: #3F3F46;
  font-size: 13px;
  font-weight: 800;
}

.status-desc {
  max-width: 100%;
  overflow-wrap: anywhere;
  color: #71717A;
  font-size: 12px;
  line-height: 1.45;
}

.card-title-row {
  margin-bottom: 12px;
  font-size: 14px;
  font-weight: 800;
}

.market-summary {
  display: grid;
  gap: 14px;
}

.market-breadth-head,
.market-breadth-counts {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.market-breadth-head span,
.market-breadth-counts {
  color: #71717A;
  font-size: 12px;
}

.market-breadth-head strong {
  font-size: 17px;
  font-weight: 900;
}

.market-breadth-bar {
  display: flex;
  height: 9px;
  overflow: hidden;
  border-radius: 999px;
  background: #ECECEC;
}

.market-breadth-bar span {
  min-width: 4px;
}

.breadth-up {
  background: #E04F76;
}

.breadth-down {
  background: #16A35C;
}

.market-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 9px;
}

.market-metric {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 10px;
  border-radius: 8px;
  background: #FFFFFF;
}

.market-metric span {
  color: #71717A;
  font-size: 11px;
}

.market-metric strong {
  min-width: 0;
  color: #3F3F46;
  white-space: nowrap;
  font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 16px;
  font-weight: 800;
  line-height: 1.05;
}

.market-metric small {
  margin-left: 2px;
  color: #71717A;
  font-size: 11px;
  font-weight: 600;
}

.index-skeleton,
.market-stats-skeleton,
.table-skeleton {
  min-width: 0;
}

.index-skeleton {
  display: grid;
  gap: 12px;
}

.sk-line,
.sk-metric,
.sk-cell {
  display: block;
  overflow: hidden;
  border-radius: 999px;
  background: linear-gradient(90deg, #ECECEC 0%, #DCDCDC 46%, #F3F3F3 62%, #ECECEC 100%);
  background-size: 220% 100%;
  animation: dashboard-shimmer 1.35s ease-in-out infinite;
}

.sk-line.short { width: 86px; height: 12px; }
.sk-line.value { width: 132px; height: 24px; border-radius: 6px; }
.sk-line.mini { width: 74px; height: 10px; }

.market-stats-skeleton {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 16px;
}

.sk-metric {
  height: 40px;
  border-radius: 6px;
}

.sk-metric.wide {
  grid-column: 1 / -1;
}

.table-skeleton {
  display: grid;
  gap: 0;
}

.dashboard-skeleton-row,
.sector-skeleton-row {
  display: grid;
  align-items: center;
  min-height: 40px;
  border-top: 1px solid #ECECEC;
  column-gap: 12px;
}

.dashboard-skeleton-row:first-child,
.sector-skeleton-row:first-child {
  border-top: 0;
}

.dashboard-skeleton-row {
  grid-template-columns: 72px minmax(120px, 1fr) 72px 72px 72px;
}

.sector-skeleton-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.sector-skeleton-row {
  grid-template-columns: minmax(0, 1fr) 72px;
}

.sk-cell {
  height: 10px;
}

.sk-cell.code { width: 54px; }
.sk-cell.name { width: 76%; }
.sk-cell.num { width: 58px; justify-self: end; }
.sk-cell.chip { width: 62px; height: 18px; justify-self: end; border-radius: 5px; }

@keyframes dashboard-shimmer {
  0% { background-position: 120% 0; }
  100% { background-position: -90% 0; }
}

@media (prefers-reduced-motion: reduce) {
  .sk-line,
  .sk-metric,
  .sk-cell {
    animation: none;
  }
}

.dashboard-alert {
  border-radius: 8px;
}

.section-alert {
  border-radius: 6px;
}

.main-grid {
  align-items: stretch;
  --dashboard-main-card-height: 718px;
}

.main-grid-item {
  display: flex;
  min-width: 0;
}

.table-card,
.sector-card {
  width: 100%;
  height: var(--dashboard-main-card-height);
  overflow: hidden;
}

.sector-card {
  display: flex;
  flex-direction: column;
}

.table-card :deep(.n-card__content),
.sector-card :deep(.n-card__content) {
  padding-top: 4px;
}

.sector-card :deep(.n-card__content) {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.table-card :deep(.n-data-table-th),
.sector-card :deep(.n-data-table-th) {
  background: transparent;
  color: #71717A;
  font-size: 12px;
  font-weight: 600;
}

.table-card :deep(.n-data-table-td),
.sector-card :deep(.n-data-table-td) {
  background: transparent;
  font-size: 13px;
  padding: 18px 14px;
}

.table-card :deep(.n-data-table-tr:hover td),
.sector-card :deep(.n-data-table-tr:hover td) {
  background: #FFFFFF;
}

.stock-name-cell {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.stock-name-text {
  font-weight: 800;
  color: #111111;
}

.clickable-row {
  cursor: pointer;
}

.sector-rank-scroll {
  flex: 1 1 auto;
  height: 624px;
  max-height: 624px;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.sector-rank-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.sector-rank-group {
  min-width: 0;
}

.sector-rank-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 26px;
  margin-bottom: 8px;
  color: #3F3F46;
  font-size: 12px;
  font-weight: 800;
}

.sector-count-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  height: 20px;
  padding: 0 7px;
  border-radius: 999px;
  font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  font-weight: 800;
}

.sector-count-pill.is-up {
  background: #FCE7EE;
  color: #C8312A;
}

.sector-count-pill.is-down {
  background: #E6F5EF;
  color: #0E8A66;
}

.sector-rank-list {
  display: grid;
  gap: 6px;
}

.sector-rank-row {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  min-height: 42px;
  width: 100%;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: #FFFFFF;
  color: #111111;
  text-align: left;
}

.sector-rank-num {
  color: #A1A1AA;
  font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  font-weight: 800;
  text-align: center;
}

.sector-rank-main {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.sector-rank-name {
  overflow: hidden;
  color: #111111;
  font-size: 13px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sector-rank-track {
  display: block;
  height: 4px;
  overflow: hidden;
  border-radius: 999px;
  background: #ECECEC;
}

.sector-rank-bar {
  display: block;
  height: 100%;
  max-width: 100%;
  border-radius: inherit;
}

.sector-rank-row.is-up .sector-rank-bar {
  background: #E04F76;
}

.sector-rank-row.is-down .sector-rank-bar {
  background: #16A35C;
}

@media (max-width: 960px) {
  .market-overview-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .indices-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .market-stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .market-metric:last-child {
    grid-column: auto;
  }

  .main-grid {
    display: flex !important;
    flex-direction: column;
    gap: 20px;
  }

  .main-grid > * {
    grid-column: span 24 / span 24 !important;
  }

  .main-grid-item {
    display: block;
  }

  .main-grid :deep(.n-gi) {
    width: 100% !important;
    max-width: 100% !important;
    min-width: 0 !important;
    flex: 0 0 auto !important;
  }

  .table-card,
  .sector-card {
    width: min(100%, calc(100vw - 24px));
    max-width: 100%;
    height: auto;
    min-width: 0;
  }

  .sector-card {
    display: block;
  }

  .sector-card :deep(.n-card__content) {
    display: block;
  }

  .table-card :deep(.n-card__content),
  .sector-card :deep(.n-card__content) {
    max-width: 100%;
    min-width: 0;
    overflow-x: auto;
  }

  .table-card :deep(.n-data-table),
  .sector-card :deep(.n-data-table) {
    max-width: 100%;
    min-width: 0;
  }
}

@media (max-width: 720px) {
  .indices-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .sector-rank-scroll {
    height: auto;
    max-height: none;
    overflow-y: visible;
    padding-right: 0;
  }

  .sector-rank-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .market-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .market-metric:last-child {
    grid-column: 1 / -1;
  }
}

@media (max-width: 460px) {
  .indices-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
