<script setup>
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NGi,
  NGrid,
  NPagination,
  NSelect,
  NSkeleton,
  NSpace,
  NStatistic,
  NTag,
} from 'naive-ui'
import Shell from '../components/Shell.vue'
import Sparkline from '../components/charts/Sparkline.vue'
import StarButton from '../components/StarButton.vue'
import { Preview } from '../shared/theme.js'
import { screen } from '../api/screener'
import { useKlineCache } from '../composables/useKlineCache.js'

const router = useRouter()
const route = useRoute()
const AGENT_RESULTS_KEY = 'qwen.results.agent.v1'
const resultModes = new Set(['balanced', 'value', 'sized', 'all'])
let suppressNextRouteSync = false

function isExplicitAllStocksQuery(query) {
  const q = String(query || '').trim().toLowerCase()
  return [
    '全部股票',
    '所有股票',
    '全市场股票',
    '查看全市场',
    '显示全市场',
    '不设条件',
    '不限条件',
    '无条件筛选',
    '放宽全部条件',
  ].some((term) => q.includes(term))
}

function readAgentContext(query = route.query) {
  if (query.source !== 'agent') return null
  try {
    const raw = sessionStorage.getItem(AGENT_RESULTS_KEY) || localStorage.getItem(AGENT_RESULTS_KEY)
    const context = JSON.parse(raw || 'null')
    return context && Array.isArray(context.conditions)
      ? context
      : null
  } catch {
    return null
  }
}

function persistAgentContext(context) {
  const payload = JSON.stringify(context)
  try { sessionStorage.setItem(AGENT_RESULTS_KEY, payload) } catch { /* ignore storage quota */ }
  try { localStorage.setItem(AGENT_RESULTS_KEY, payload) } catch { /* ignore storage quota */ }
}

function routeFilterMode(query = route.query, hasAgent = false) {
  if (hasAgent) return 'agent'
  return typeof query.mode === 'string' && resultModes.has(query.mode) ? query.mode : null
}

const agentContext = ref(readAgentContext())
const filterMode = ref(routeFilterMode(route.query, Boolean(agentContext.value)))
const sortableFields = new Set(['score', 'close', 'change_pct', 'pe', 'pb', 'roe', 'dividend_yield', 'market_cap', 'turnover'])
const sortLabels = {
  score: '综合分',
  close: '现价',
  change_pct: '涨跌幅',
  pe: 'PE',
  pb: 'PB',
  roe: 'ROE',
  dividend_yield: '股息率',
  market_cap: '总市值',
  turnover: '换手率',
}

function positiveInt(value, fallback) {
  const parsed = Number.parseInt(value, 10)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

const initialSort = typeof route.query.sort === 'string'
  ? route.query.sort
  : agentContext.value?.sort_by
const page = ref(positiveInt(route.query.page, 1))
const pageSize = ref([20, 50, 100].includes(positiveInt(route.query.size, 20)) ? positiveInt(route.query.size, 20) : 20)
const sortBy = ref(sortableFields.has(initialSort) ? initialSort : 'score')
const sortDesc = ref(route.query.order === 'asc'
  ? false
  : (route.query.order === 'desc' ? true : (filterMode.value === 'agent' && agentContext.value?.sort_desc !== false)))
const conditionSets = {
  balanced: [
    { field: 'pe', op: 'between', value: [0, 500] },
  ],
  value: [
    { field: 'pe', op: 'between', value: [0, 80] },
    { field: 'roe', op: 'gt', value: 5 },
  ],
  sized: [
    { field: 'pe', op: 'between', value: [0, 500] },
    { field: 'market_cap', op: 'gt', value: 100 },
  ],
  all: [],
}

const fieldLabels = {
  pe: 'PE(TTM)',
  pb: 'PB',
  roe: 'ROE',
  market_cap: '总市值',
  dividend_yield: '股息率',
  debt_ratio: '资产负债率',
  gross_margin: '毛利率',
  profit_yoy: '净利润同比',
  revenue_yoy: '营收同比',
  industry: '行业',
}
const opLabels = {
  lt: '<',
  lte: '≤',
  gt: '>',
  gte: '≥',
  eq: '=',
  between: '范围',
  in: '包含',
}

function formatFilterValue(condition) {
  const value = Array.isArray(condition.value) ? condition.value.join(' — ') : condition.value
  return `${opLabels[condition.op] || condition.op} ${value}`
}

const filterGroups = computed(() => {
  if (filterMode.value === 'agent' && agentContext.value) {
    return [{
      cat: '本轮条件',
      items: agentContext.value.conditions.map((condition) => ({
        l: fieldLabels[condition.field] || condition.field,
        v: formatFilterValue(condition),
      })),
    }]
  }
  const map = {
    balanced: [
      { cat: '基础', items: [{ l: '股票池', v: '全市场' }, { l: '数据', v: '最近交易日' }] },
      { cat: '估值', items: [{ l: 'PE(TTM)', v: '0 — 500' }] },
      { cat: '规模', items: [{ l: '总市值', v: '不限制' }] },
    ],
    value: [
      { cat: '估值', items: [{ l: 'PE(TTM)', v: '0 — 80' }] },
      { cat: '盈利', items: [{ l: 'ROE', v: '> 5%' }] },
      { cat: '规模', items: [{ l: '总市值', v: '不限制' }] },
    ],
    sized: [
      { cat: '估值', items: [{ l: 'PE(TTM)', v: '0 — 500' }] },
      { cat: '规模', items: [{ l: '总市值', v: '> 100 亿' }] },
    ],
    all: [
      { cat: '基础', items: [{ l: '条件', v: '全部放宽' }] },
      { cat: '排序', items: [{ l: '字段', v: '现价 / 代码' }] },
    ],
  }
  return map[filterMode.value]
})

const items = ref([])
const total = ref(0)
const tradeDate = ref(null)
const loading = ref(true)
const errorMsg = ref('')
let loadRequestId = 0

const hasRunnableFilter = computed(() => {
  if (filterMode.value === 'agent') {
    return Boolean(agentContext.value?.conditions?.length)
      || Boolean(agentContext.value?.last_result && isExplicitAllStocksQuery(agentContext.value?.query))
  }
  return Boolean(filterMode.value && conditionSets[filterMode.value])
})

const { load: loadResultKlines, get: resultSpark } = useKlineCache(30)
watch(items, () => loadResultKlines(items.value.map((s) => s.code)))

const stats = computed(() => {
  const arr = items.value
  if (!arr.length) return []
  const avg = (k) => {
    const xs = arr.map((x) => x[k]).filter((v) => v != null)
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null
  }
  const fmt = (v, d = 1) => v == null ? '—' : v.toFixed(d)
  return [
    { l: '命中数量', v: total.value, sub: `已展示 ${arr.length} 只`, unit: '只' },
    { l: '平均 PE', v: fmt(avg('pe')), sub: '当前页均值', unit: 'x' },
    { l: '平均市值', v: fmt(avg('market_cap'), 0), sub: '当前页均值', unit: '亿' },
    { l: '平均股息率', v: fmt(avg('dividend_yield')), sub: '当前页均值', unit: '%' },
    { l: '平均 ROE', v: fmt(avg('roe')), sub: '当前页均值', unit: '%' },
  ]
})

const resultSubtitle = computed(() => {
  if (filterMode.value === 'agent') {
    return agentContext.value?.query || '本轮智能筛选'
  }
  const map = {
    balanced: '全市场基础视图',
    value: '价值因子 · PE + ROE',
    sized: '大市值 · 按市值排序',
    all: '全部股票 · 已放宽条件',
  }
  return map[filterMode.value] || '等待筛选条件'
})

const activeSortLabel = computed(() => `${sortLabels[sortBy.value] || sortBy.value} ${sortDesc.value ? '降序' : '升序'}`)
const sortOptions = Object.entries(sortLabels).map(([value, label]) => ({ value, label }))
const pageStart = computed(() => total.value ? (page.value - 1) * pageSize.value + 1 : 0)
const pageEnd = computed(() => Math.min(page.value * pageSize.value, total.value))

const fmtNum = (v, d = 2) => v != null ? v.toFixed(d) : '—'
const fmtPositive = (v, d = 2) => v != null && v > 0 ? v.toFixed(d) : '—'

function remoteSort(key) {
  return {
    sorter: true,
    sortOrder: sortBy.value === key ? (sortDesc.value ? 'descend' : 'ascend') : false,
  }
}

function rightMonoCell(text, extra = {}) {
  return h('span', {
    style: {
      display: 'block',
      textAlign: 'right',
      fontFamily: 'IBM Plex Mono, monospace',
      ...extra,
    },
  }, text)
}

const columns = computed(() => [
  {
    title: '#',
    key: 'index',
    width: 46,
    render: (_, i) => h('span', { style: { color: Preview.textMuted, fontFamily: 'IBM Plex Mono, monospace', fontSize: '10px' } }, String((page.value - 1) * pageSize.value + i + 1).padStart(2, '0')),
  },
  {
    title: '代码',
    key: 'code',
    width: 92,
    render: (s) => h('span', { style: { fontFamily: 'IBM Plex Mono, monospace', color: Preview.textMuted, fontSize: '10.5px' } }, s.code),
  },
  {
    title: '名称',
    key: 'name',
    minWidth: 120,
    render: (s) => h('div', { style: { display: 'flex', alignItems: 'center', gap: '4px', fontWeight: 600 } }, [
      h(StarButton, { stock: { code: s.code, name: s.name, sector: s.industry, refPrice: s.close }, size: 12 }),
      h('span', s.name),
    ]),
  },
  {
    title: '行业',
    key: 'industry',
    minWidth: 90,
    render: (s) => h(NTag, { size: 'small', bordered: false, style: { maxWidth: '118px' } }, { default: () => s.industry || '—' }),
  },
  {
    title: '综合分',
    key: 'score',
    align: 'right',
    width: 82,
    ...remoteSort('score'),
    render: (s) => rightMonoCell(s.score != null ? s.score.toFixed(1) : '—', {
      color: s.score >= 70 ? Preview.positive : Preview.textMuted,
      fontWeight: s.score >= 70 ? 700 : 600,
    }),
  },
  {
    title: '现价',
    key: 'close',
    align: 'right',
    width: 76,
    ...remoteSort('close'),
    render: (s) => rightMonoCell(fmtNum(s.close), { color: Preview.textMain, fontWeight: 700 }),
  },
  {
    title: '涨跌幅',
    key: 'change_pct',
    align: 'right',
    width: 84,
    ...remoteSort('change_pct'),
    render: (s) => rightMonoCell(
      s.change_pct == null ? '—' : `${s.change_pct >= 0 ? '+' : ''}${s.change_pct.toFixed(2)}%`,
      {
        color: s.change_pct == null ? Preview.textMuted : (s.change_pct >= 0 ? Preview.positive : Preview.negative),
        fontWeight: s.change_pct == null ? 500 : 700,
      },
    ),
  },
  {
    title: 'PE',
    key: 'pe',
    align: 'right',
    width: 70,
    ...remoteSort('pe'),
    render: (s) => rightMonoCell(fmtPositive(s.pe)),
  },
  {
    title: 'PB',
    key: 'pb',
    align: 'right',
    width: 70,
    ...remoteSort('pb'),
    render: (s) => rightMonoCell(fmtNum(s.pb)),
  },
  {
    title: 'ROE',
    key: 'roe',
    align: 'right',
    width: 76,
    ...remoteSort('roe'),
    render: (s) => rightMonoCell(s.roe != null ? `${s.roe.toFixed(2)}%` : '—', {
      color: s.roe > 10 ? Preview.negative : Preview.textMuted,
      fontWeight: s.roe > 10 ? 600 : 500,
    }),
  },
  {
    title: '股息率',
    key: 'dividend_yield',
    align: 'right',
    width: 82,
    ...remoteSort('dividend_yield'),
    render: (s) => rightMonoCell(s.dividend_yield != null ? `${s.dividend_yield.toFixed(2)}%` : '—', {
      color: s.dividend_yield > 4 ? Preview.negative : Preview.textMuted,
      fontWeight: s.dividend_yield > 4 ? 600 : 500,
    }),
  },
  {
    title: '总市值',
    key: 'market_cap',
    align: 'right',
    width: 96,
    ...remoteSort('market_cap'),
    render: (s) => h('span', {
      style: { display: 'block', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace' },
    }, [
      s.market_cap != null ? Math.round(s.market_cap).toLocaleString() : '—',
      h('span', { style: { color: Preview.textMuted, fontSize: '9px' } }, '亿'),
    ]),
  },
  {
    title: '换手率',
    key: 'turnover',
    align: 'right',
    width: 82,
    ...remoteSort('turnover'),
    render: (s) => rightMonoCell(s.turnover != null ? `${s.turnover.toFixed(2)}%` : '—'),
  },
  {
    title: '30日走势',
    key: 'trend',
    width: 94,
    render: (s) => h(Sparkline, { data: resultSpark(s.code), width: 64, height: 20 }),
  },
  {
    title: '操作',
    key: 'actions',
    align: 'right',
    width: 74,
    render: (s) => h(NButton, {
      text: true,
      size: 'tiny',
      type: 'primary',
      onClick: (e) => { e.stopPropagation(); gotoDetail(s.code) },
    }, { default: () => '详情 →' }),
  },
])

async function load() {
  const requestId = ++loadRequestId
  if (!hasRunnableFilter.value) {
    items.value = []
    total.value = 0
    tradeDate.value = null
    errorMsg.value = ''
    loading.value = false
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const usingAgentContext = filterMode.value === 'agent' && agentContext.value
    const data = await screen(usingAgentContext ? agentContext.value.conditions : conditionSets[filterMode.value], {
      sort_by: sortBy.value,
      sort_desc: sortDesc.value,
      offset: (page.value - 1) * pageSize.value,
      limit: pageSize.value,
    })
    if (requestId !== loadRequestId) return
    const maxPage = Math.max(1, Math.ceil(data.total / pageSize.value))
    if (page.value > maxPage) {
      page.value = maxPage
      syncRouteState()
      return await load()
    }
    items.value = data.items
    total.value = data.total
    tradeDate.value = data.trade_date || data.items?.[0]?.trade_date || null
    if (usingAgentContext && agentContext.value) {
      persistAgentContext({
        ...agentContext.value,
        page: page.value,
        size: pageSize.value,
        total: data.total,
        sort_by: sortBy.value,
        sort_desc: sortDesc.value,
        last_result: {
          total: data.total,
          offset: data.offset || (page.value - 1) * pageSize.value,
          limit: data.limit || pageSize.value,
          trade_date: data.trade_date || data.items?.[0]?.trade_date || null,
          items: (data.items || []).slice(0, 8),
          parsed_conditions: data.parsed_conditions || agentContext.value.conditions,
        },
      })
    }
  } catch (e) {
    if (requestId !== loadRequestId) return
    errorMsg.value = e.response?.data?.detail || e.message
  } finally {
    if (requestId === loadRequestId) {
      loading.value = false
    }
  }
}

function syncRouteState() {
  const query = {
    page: String(page.value),
    size: String(pageSize.value),
    sort: sortBy.value,
    order: sortDesc.value ? 'desc' : 'asc',
  }
  if (filterMode.value === 'agent') {
    query.source = 'agent'
    if (agentContext.value) {
      agentContext.value.sort_by = sortBy.value
      agentContext.value.sort_desc = sortDesc.value
      agentContext.value.page = page.value
      agentContext.value.size = pageSize.value
      agentContext.value.total = total.value
      persistAgentContext(agentContext.value)
    }
  } else {
    query.mode = filterMode.value
  }
  suppressNextRouteSync = true
  router.push({ path: '/results', query })
    .catch(() => {})
    .finally(() => {
      suppressNextRouteSync = false
    })
}

function applyRouteState(query = route.query) {
  const nextAgent = readAgentContext(query)
  agentContext.value = nextAgent
  filterMode.value = routeFilterMode(query, Boolean(nextAgent))
  page.value = positiveInt(query.page, 1)
  const nextSize = positiveInt(query.size, 20)
  pageSize.value = [20, 50, 100].includes(nextSize) ? nextSize : 20
  const nextSort = typeof query.sort === 'string' ? query.sort : nextAgent?.sort_by
  sortBy.value = sortableFields.has(nextSort) ? nextSort : 'score'
  sortDesc.value = query.order === 'asc'
    ? false
    : (query.order === 'desc' ? true : (filterMode.value === 'agent' && nextAgent?.sort_desc !== false))
}

function applyMode(mode) {
  filterMode.value = mode
  page.value = 1
  sortBy.value = mode === 'sized' ? 'market_cap' : 'score'
  sortDesc.value = true
  syncRouteState()
  load()
}

function handleSortSelect(value) {
  if (!sortableFields.has(value)) return
  sortBy.value = value
  page.value = 1
  syncRouteState()
  load()
}

function toggleSortOrder() {
  sortDesc.value = !sortDesc.value
  page.value = 1
  syncRouteState()
  load()
}

function handleSorterChange(sorter) {
  if (!sorter?.columnKey || !sorter?.order || !sortableFields.has(sorter.columnKey)) return
  sortBy.value = sorter.columnKey
  sortDesc.value = sorter.order === 'descend'
  page.value = 1
  syncRouteState()
  load()
}

function handlePageChange(nextPage) {
  page.value = nextPage
  syncRouteState()
  load()
}

function handlePageSizeChange(nextSize) {
  pageSize.value = nextSize
  page.value = 1
  syncRouteState()
  load()
}

function gotoDetail(code) {
  router.push(`/detail/${code}`)
}

function backToAgentChat() {
  const sessionId = agentContext.value?.session_id
  const target = sessionId
    ? `/chat?session=${encodeURIComponent(sessionId)}`
    : '/chat'
  window.location.assign(target)
}

function rowProps(row) {
  return {
    style: 'cursor: pointer;',
    onClick: () => gotoDetail(row.code),
  }
}

onMounted(load)

watch(
  () => route.fullPath,
  () => {
    if (suppressNextRouteSync) return
    applyRouteState(route.query)
    load()
  }
)
</script>

<template>
  <Shell>
    <div class="results-page">
      <!-- Top Bar: Title + Filter Tags + Actions -->
      <div class="results-topbar">
        <div class="results-title-row">
          <h2 class="results-title">筛选结果</h2>
          <NTag v-if="filterMode === 'agent'" type="info" size="small" :bordered="false">
            本轮智能筛选
          </NTag>
          <span class="results-total">
            <template v-if="hasRunnableFilter">
              共 <strong>{{ total }}</strong> 只 · {{ resultSubtitle }}
            </template>
            <template v-else>
              {{ resultSubtitle }}
            </template>
          </span>
        </div>
        <NSpace size="small">
          <NButton text size="small" type="primary" @click="router.push('/chat')">
            自然语言筛选
          </NButton>
          <NButton
            v-if="filterMode === 'agent'"
            text
            size="small"
            type="primary"
            @click="backToAgentChat"
          >
            返回对话
          </NButton>
          <NButton v-if="hasRunnableFilter" type="primary" size="small" :loading="loading" @click="load">
            重新筛选
          </NButton>
        </NSpace>
      </div>

      <NCard v-if="!hasRunnableFilter" :bordered="false" class="results-card empty-results-card">
        <NEmpty description="还没有筛选结果">
          <template #extra>
            <div class="empty-results-actions">
              <span>先在智能筛选里输入条件，再进入这里查看完整列表、分页和排序。</span>
              <NButton type="primary" size="small" @click="router.push('/chat')">去智能筛选</NButton>
            </div>
          </template>
        </NEmpty>
      </NCard>

      <!-- Filter Condition Tags -->
      <NCard v-if="hasRunnableFilter" size="small" class="results-card filter-card">
        <div class="filter-tags">
          <template v-for="g in filterGroups" :key="g.cat">
            <span class="filter-cat-name">{{ g.cat }}</span>
            <NTag v-for="it in g.items" :key="it.l" size="small" :bordered="false" class="filter-tag-pill">
              {{ it.l }}: {{ it.v }}
            </NTag>
          </template>
        </div>
        <div class="result-meta">
          <span>数据日期 {{ tradeDate || '—' }}</span>
          <span>排序 {{ activeSortLabel }}</span>
        </div>
        <div class="sort-controls">
          <span>排序</span>
          <NSelect
            :value="sortBy"
            :options="sortOptions"
            size="small"
            class="sort-select"
            @update:value="handleSortSelect"
          />
          <NButton size="small" secondary class="sort-order-btn" @click="toggleSortOrder">
            {{ sortDesc ? '降序' : '升序' }}
          </NButton>
        </div>
      </NCard>

      <!-- Error -->
      <NAlert v-if="hasRunnableFilter && errorMsg" type="error" :bordered="false" class="error-alert">
        <div class="error-row">
          <span>{{ errorMsg }}</span>
          <NButton size="tiny" secondary :loading="loading" @click="load">重试</NButton>
        </div>
      </NAlert>

      <!-- Stats -->
      <NGrid v-if="hasRunnableFilter" cols="2 m:3 l:5" responsive="screen" :x-gap="10" :y-gap="10" class="stats-grid">
        <NGi v-for="s in stats" :key="s.l">
          <NCard size="small" :bordered="false" class="results-card stat-card">
            <NStatistic :label="s.l">
              <template #default>
                <span class="stat-value">
                  {{ s.v }}
                  <span class="stat-unit">{{ s.unit }}</span>
                </span>
              </template>
            </NStatistic>
            <div class="stat-sub">{{ s.sub }}</div>
          </NCard>
        </NGi>
      </NGrid>

      <!-- Table -->
      <NCard v-if="hasRunnableFilter" :bordered="false" class="results-card table-card">
        <div v-if="loading" class="results-skeleton">
          <div v-for="n in 8" :key="'sk' + n" class="skeleton-row">
            <NSkeleton v-for="(_, ci) in 12" :key="ci" :height="12" :width="55" :sharp="false" />
          </div>
        </div>
        <NDataTable
          v-else
          :columns="columns"
          :data="items"
          :row-key="(row) => row.code"
          :row-props="rowProps"
          :pagination="false"
          :bordered="false"
          :single-line="false"
          :scroll-x="1240"
          size="small"
          remote
          @update:sorter="handleSorterChange"
        >
          <template #empty>
            <div class="empty-panel">
              <NEmpty description="没有命中任何股票">
                <template #extra>
                  <span class="empty-extra">当前条件可能依赖缺失字段，建议先放宽规模或估值条件</span>
                </template>
              </NEmpty>
              <NButton size="small" type="primary" secondary @click="applyMode('all')">放宽全部条件</NButton>
            </div>
          </template>
        </NDataTable>
        <div class="table-footer">
          <span class="pagination-summary">第 {{ pageStart }}–{{ pageEnd }} 条，共 {{ total }} 条</span>
          <NPagination
            :page="page"
            :page-size="pageSize"
            :item-count="total"
            :page-sizes="[20, 50, 100]"
            show-size-picker
            :page-slot="5"
            @update:page="handlePageChange"
            @update:page-size="handlePageSizeChange"
          />
        </div>
      </NCard>
    </div>
  </Shell>
</template>

<style scoped>
.results-page {
  color: #111111;
}

.results-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 22px;
  padding-top: 2px;
  flex-wrap: wrap;
}

.results-title-row {
  display: flex;
  align-items: baseline;
  gap: 14px;
}

.results-title {
  margin: 0;
  font-size: 28px;
  font-weight: 800;
  color: #111111;
  letter-spacing: 0;
}

.results-total {
  font-size: 14px;
  color: #71717A;
}

.results-total strong {
  color: #111111;
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 700;
}

.results-card {
  background: #F7F7F7;
  border: 0;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
}

.empty-results-card {
  display: grid;
  min-height: 360px;
  place-items: center;
  background: #FFFFFF;
  border-radius: 0;
  border-top: 1px solid #EDEDED;
  box-shadow: none;
}

.empty-results-card :deep(.n-card__content) {
  width: 100%;
}

.empty-results-actions {
  display: grid;
  justify-items: center;
  gap: 14px;
  max-width: 420px;
  color: #71717A;
  font-size: 13px;
  line-height: 1.6;
  text-align: center;
}

.filter-card {
  margin-bottom: 0;
  background: #FFFFFF;
  border-top: 1px solid #EDEDED;
  border-bottom: 1px solid #EDEDED;
  border-radius: 0;
  box-shadow: none;
}

.error-alert,
.stats-grid {
  margin: 12px 0;
}

.error-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.error-row span {
  flex: 1;
}

.filter-card :deep(.n-card__content) {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px 18px;
  align-items: center;
  padding: 14px 0;
}

.filter-tags {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  grid-column: 1 / 2;
}

.result-meta {
  display: flex;
  gap: 16px;
  color: #71717A;
  font-size: 12px;
  grid-column: 1 / 2;
}

.sort-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #71717A;
  font-size: 12px;
  grid-column: 2 / 3;
  grid-row: 1 / span 2;
  white-space: nowrap;
}

.sort-select {
  width: 116px;
}

.sort-order-btn {
  min-width: 58px;
}

.filter-cat-name {
  font-size: 12px;
  font-weight: 700;
  color: #111111;
  letter-spacing: 0;
}

.filter-tag-pill {
  font-size: 12px;
  background: #F5F5F5;
  color: #52525B;
  border-radius: 4px;
}

.stat-card :deep(.n-card__content) {
  padding: 16px 18px;
}

.stat-value {
  font-size: 24px;
  font-weight: 800;
  font-family: 'IBM Plex Mono', monospace;
  color: #111111;
}

.stat-unit {
  font-size: 11px;
  color: #71717A;
  font-weight: 500;
}

.stat-sub {
  font-size: 10px;
  color: #71717A;
  margin-top: 4px;
}

.table-card {
  overflow: hidden;
  background: #FFFFFF;
  border-radius: 0;
  border-top: 1px solid #EDEDED;
}

.table-card :deep(.n-card__content) {
  padding: 0;
}

.table-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-top: 1px solid #EDEDED;
}

.pagination-summary {
  color: #71717A;
  font-size: 12px;
}

.table-card :deep(.n-data-table-th) {
  background: #FFFFFF;
  color: #71717A;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0;
  white-space: nowrap;
  border-bottom: 1px solid #EDEDED;
}

.table-card :deep(.n-data-table-td) {
  font-size: 14px;
  padding: 14px 8px;
  border-bottom: 1px solid #F1F1F1;
}

.table-card :deep(.n-data-table-tr:hover td) {
  background: #FAFAFA;
}

.results-skeleton {
  padding: 4px;
}

.skeleton-row {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid #edf1f7;
}

.empty-panel {
  display: grid;
  place-items: center;
  gap: 10px;
  padding: 38px 0;
}

.empty-extra {
  color: #71717a;
  font-size: 12px;
}

@media (max-width: 640px) {
  .filter-card :deep(.n-card__content) {
    grid-template-columns: 1fr;
  }

  .filter-tags,
  .result-meta,
  .sort-controls {
    grid-column: 1;
  }

  .sort-controls {
    grid-row: auto;
    justify-content: space-between;
  }

  .sort-select {
    flex: 1;
    min-width: 0;
  }

  .table-footer {
    align-items: flex-start;
    flex-direction: column;
  }

  .result-meta {
    gap: 6px;
    flex-direction: column;
  }
}
</style>
