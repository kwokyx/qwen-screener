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
function goToScreener(query) { router.push({ path: '/chat', query: { q: query } }) }

const indices = ref([])
const sectors = ref([])
const movers = ref(null)
const tickerInfo = ref(null)
const moverTab = ref('gainers')
const loadingIndices = ref(true)
const loadingSectors = ref(true)
const loadingMovers = ref(true)
const errorMsg = ref('')

const moversShown = computed(() => (movers.value ? movers.value[moverTab.value] || [] : []))
const idxSpark = computed(() => indices.value.map((idx) => idx.spark || []))

const sectorsUp = computed(() => [...sectors.value].filter((s) => s.change_pct >= 0).sort((a, b) => b.change_pct - a.change_pct))
const sectorsDown = computed(() => [...sectors.value].filter((s) => s.change_pct < 0).sort((a, b) => a.change_pct - b.change_pct))

const marketStats = computed(() => {
  const t = tickerInfo.value
  if (!t) return null
  return {
    advancers: t.advancers || 0,
    decliners: t.decliners || 0,
    amount: t.total_amount_yi || 0,
    tradeDate: t.trade_date,
  }
})

async function loadAll() {
  errorMsg.value = ''
  loadingIndices.value = true
  loadingSectors.value = true
  loadingMovers.value = true

  Promise.allSettled([
    marketApi.indices().then((d) => { indices.value = d }).finally(() => { loadingIndices.value = false }),
    marketApi.sectors(20).then((d) => { sectors.value = d }).finally(() => { loadingSectors.value = false }),
    marketApi.movers(10).then((d) => {
      movers.value = d
    }).finally(() => { loadingMovers.value = false }),
    marketApi.ticker().then((d) => { tickerInfo.value = d }).catch(() => {}),
  ]).then((rs) => {
    const failed = rs.filter((r) => r.status === 'rejected')
    if (failed.length === rs.length) errorMsg.value = friendlyError(failed[0].reason)
  })
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
    title: 'PE',
    key: 'pe',
    align: 'right',
    width: 76,
    render: (s) => mono(s.pe != null && s.pe > 0 ? s.pe.toFixed(1) : '—', { color: Preview.textMuted }),
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

function sectorColumns(type) {
  const positive = type === 'up'
  return [
    {
      title: positive ? '上涨板块' : '下跌板块',
      key: 'name',
      render: (s) => h('button', {
        class: 'sector-link',
        onClick: () => goToScreener(`${s.name} 板块基本面好的股票`),
      }, s.name),
    },
    {
      title: '涨跌幅',
      key: 'change_pct',
      align: 'right',
      width: 92,
      render: (s) => h(PctText, { pct: s.change_pct, size: 12 }),
    },
  ]
}

const sectorStrengthColumns = [
  {
    title: '板块',
    key: 'name',
    width: 120,
    ellipsis: { tooltip: true },
  },
  {
    title: '强度',
    key: 'bar',
    render: (s) => h('div', { class: 'strength-track' }, [
      h('span', { class: 'strength-axis' }),
      h('span', {
        class: ['strength-bar', s.change_pct >= 0 ? 'is-up' : 'is-down'],
        style: {
          width: `${Math.min(50, Math.abs(s.change_pct) * 8)}%`,
          left: s.change_pct >= 0 ? '50%' : 'auto',
          right: s.change_pct >= 0 ? 'auto' : '50%',
        },
      }),
    ]),
  },
  {
    title: '涨跌幅',
    key: 'change_pct',
    align: 'right',
    width: 92,
    render: (s) => h(PctText, { pct: s.change_pct, size: 12 }),
  },
]

onMounted(loadAll)
</script>

<template>
  <Shell>
    <div class="dashboard-page">
      <div class="market-overview-grid">
        <template v-if="loadingIndices && !indices.length">
          <NCard v-for="(_, n) in 4" :key="'idx-sk-' + n" class="terminal-card index-card" :bordered="false">
            <div class="index-skeleton">
              <span class="sk-line short"></span>
              <span class="sk-line value"></span>
              <span class="sk-line mini"></span>
            </div>
          </NCard>
        </template>
        <template v-else>
          <NCard v-for="(idx, i) in indices" :key="idx.code" class="terminal-card index-card" :bordered="false">
            <div class="index-head">
              <div>
                <div class="index-name">{{ idx.name }}</div>
                <div class="index-code">{{ idx.code }} · {{ idx.constituents }} 只</div>
              </div>
              <Sparkline :data="idxSpark[i] || []" :width="64" :height="24" />
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

        <NCard class="terminal-card market-card" :bordered="false">
          <div class="card-title-row">
            <span>市场概况</span>
            <NTag size="tiny" :bordered="false">{{ marketStats?.tradeDate || '—' }}</NTag>
          </div>
          <div v-if="!marketStats" class="market-stats-skeleton">
            <span class="sk-metric"></span>
            <span class="sk-metric"></span>
            <span class="sk-metric wide"></span>
          </div>
          <div v-else class="market-stats">
            <div class="market-metric">
              <span>上涨</span>
              <strong>{{ formatInt(marketStats.advancers) }}</strong>
            </div>
            <div class="market-metric">
              <span>下跌</span>
              <strong>{{ formatInt(marketStats.decliners) }}</strong>
            </div>
            <div class="market-metric">
              <span>总成交</span>
              <strong>{{ formatInt(marketStats.amount) }}<small>亿</small></strong>
            </div>
          </div>
        </NCard>
      </div>

      <NAlert v-if="errorMsg" type="error" :bordered="false" class="dashboard-alert">
        <div class="alert-content">
          <span>{{ errorMsg }}</span>
          <NButton size="tiny" secondary :loading="loadingIndices || loadingSectors || loadingMovers" @click="loadAll">重试</NButton>
        </div>
      </NAlert>

      <NGrid :cols="24" :x-gap="12" :y-gap="12" responsive="screen" class="main-grid">
        <NGi :span="16">
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
              <NTabs v-model:value="moverTab" type="segment" size="small" animated>
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
            <NDataTable
              v-else
              :columns="moverColumns"
              :data="moversShown"
              :loading="loadingMovers"
              :pagination="false"
              :bordered="false"
              :single-line="false"
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

        <NGi :span="8">
          <NCard class="terminal-card sector-card" :bordered="false">
            <template #header>
              <div>
                <div class="card-title">板块涨跌</div>
                <div class="card-subtitle">申万一级 · 点击让千问深挖</div>
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
            <NGrid v-else :cols="2" :x-gap="10">
              <NGi>
                <NDataTable
                  :columns="sectorColumns('up')"
                  :data="sectorsUp.slice(0, 8)"
                  :loading="loadingSectors"
                  :pagination="false"
                  :bordered="false"
                  size="small"
                >
                  <template #empty>
                    <NEmpty size="small" description="无上涨板块" />
                  </template>
                </NDataTable>
              </NGi>
              <NGi>
                <NDataTable
                  :columns="sectorColumns('down')"
                  :data="sectorsDown.slice(0, 8)"
                  :loading="loadingSectors"
                  :pagination="false"
                  :bordered="false"
                  size="small"
                >
                  <template #empty>
                    <NEmpty size="small" description="无下跌板块" />
                  </template>
                </NDataTable>
              </NGi>
            </NGrid>
          </NCard>
        </NGi>

        <NGi :span="24">
          <NCard class="terminal-card strength-card" :bordered="false">
            <template #header>
              <div>
                <div class="card-title">板块涨跌幅强度</div>
                <div class="card-subtitle">条形长度按涨跌幅绝对值映射，流通市值加权</div>
              </div>
            </template>
            <template #header-extra>
              <NTag size="small" :bordered="false">{{ sectors.length }} 个行业</NTag>
            </template>
            <div v-if="loadingSectors && !sectors.length" class="table-skeleton strength-skeleton-list">
              <div v-for="n in 10" :key="'strength-sk-' + n" class="strength-skeleton-row">
                <span class="sk-cell sector"></span>
                <span class="sk-cell bar"></span>
                <span class="sk-cell chip"></span>
              </div>
            </div>
            <NDataTable
              v-else
              :columns="sectorStrengthColumns"
              :data="sectors"
              :loading="loadingSectors"
              :pagination="false"
              :bordered="false"
              size="small"
            >
              <template #empty>
                <NEmpty description="暂无板块数据" />
              </template>
            </NDataTable>
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
  gap: 12px;
}

.market-overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 12px;
  align-items: stretch;
}

.terminal-card {
  background: #F7F7F7;
  border-radius: 8px;
}

.terminal-card :deep(.n-card-header) {
  padding: 16px 18px 8px;
}

.terminal-card :deep(.n-card__content) {
  padding: 14px 18px 18px;
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
  gap: 10px;
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
  min-height: 118px;
}

.card-title-row {
  margin-bottom: 12px;
  font-size: 14px;
  font-weight: 800;
}

.market-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 16px;
}

.market-metric {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.market-metric:last-child {
  grid-column: 1 / -1;
}

.market-metric span {
  color: #71717A;
  font-size: 12px;
}

.market-metric strong {
  min-width: 0;
  color: #3F3F46;
  white-space: nowrap;
  font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 21px;
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
.sector-skeleton-row,
.strength-skeleton-row {
  display: grid;
  align-items: center;
  min-height: 40px;
  border-top: 1px solid #ECECEC;
  column-gap: 12px;
}

.dashboard-skeleton-row:first-child,
.sector-skeleton-row:first-child,
.strength-skeleton-row:first-child {
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

.strength-skeleton-row {
  grid-template-columns: 120px minmax(0, 1fr) 72px;
}

.sk-cell {
  height: 10px;
}

.sk-cell.code { width: 54px; }
.sk-cell.name { width: 76%; }
.sk-cell.num { width: 58px; justify-self: end; }
.sk-cell.chip { width: 62px; height: 18px; justify-self: end; border-radius: 5px; }
.sk-cell.sector { width: 88px; }
.sk-cell.bar { width: 100%; height: 8px; border-radius: 3px; }

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

.main-grid {
  align-items: start;
}

.table-card,
.sector-card,
.strength-card {
  overflow: hidden;
}

.table-card :deep(.n-card__content),
.sector-card :deep(.n-card__content),
.strength-card :deep(.n-card__content) {
  padding-top: 4px;
}

.table-card :deep(.n-data-table-th),
.sector-card :deep(.n-data-table-th),
.strength-card :deep(.n-data-table-th) {
  background: transparent;
  color: #71717A;
  font-size: 12px;
  font-weight: 600;
}

.table-card :deep(.n-data-table-td),
.sector-card :deep(.n-data-table-td),
.strength-card :deep(.n-data-table-td) {
  background: transparent;
  font-size: 13px;
  padding: 10px 8px;
}

.table-card :deep(.n-data-table-tr:hover td),
.sector-card :deep(.n-data-table-tr:hover td),
.strength-card :deep(.n-data-table-tr:hover td) {
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

:deep(.sector-link) {
  width: 100%;
  display: block;
  overflow: hidden;
  padding: 0;
  border: 0;
  background: transparent;
  color: #111111;
  font: inherit;
  font-weight: 700;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

:deep(.sector-link:hover) {
  text-decoration: underline;
}

.strength-track {
  position: relative;
  height: 8px;
  overflow: hidden;
  border-radius: 3px;
  background: #ECECEC;
}

.strength-axis {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 1px;
  background: #D4D4D8;
}

.strength-bar {
  position: absolute;
  top: 0;
  bottom: 0;
  border-radius: 3px;
}

.strength-bar.is-up {
  background: #E04F76;
}

.strength-bar.is-down {
  background: #16A35C;
}

@media (max-width: 960px) {
  .market-overview-grid {
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  }

  .main-grid > * {
    grid-column: span 24 / span 24 !important;
  }
}
</style>
