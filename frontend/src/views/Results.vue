<script setup>
import { computed, h, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NGi,
  NGrid,
  NProgress,
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

const filterMode = ref('balanced')
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

const filterGroups = computed(() => {
  const map = {
    balanced: [
      { cat: '基础', items: [{ l: '股票池', v: '全市场' }, { l: '数据', v: '最近交易日' }] },
      { cat: '估值', items: [{ l: 'PE(TTM)', v: '0 — 500' }] },
      { cat: '规模', items: [{ l: '总市值', v: '不限制' }] },
      { cat: '提示', items: [{ l: 'baostock', v: '市值缺失时自动跳过规模过滤' }] },
    ],
    value: [
      { cat: '估值', items: [{ l: 'PE(TTM)', v: '0 — 80' }] },
      { cat: '盈利', items: [{ l: 'ROE', v: '> 5%' }] },
      { cat: '规模', items: [{ l: '总市值', v: '不限制' }] },
    ],
    sized: [
      { cat: '估值', items: [{ l: 'PE(TTM)', v: '0 — 500' }] },
      { cat: '规模', items: [{ l: '总市值', v: '> 100 亿' }] },
      { cat: '注意', items: [{ l: '数据源', v: '需要市值字段' }] },
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
const loading = ref(true)
const errorMsg = ref('')

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
    { l: '平均 PE', v: fmt(avg('pe')), sub: '组内中位', unit: 'x' },
    { l: '平均市值', v: fmt(avg('market_cap'), 0), sub: '亿元', unit: '亿' },
    { l: '平均股息率', v: fmt(avg('dividend_yield')), sub: '组内中位', unit: '%' },
    { l: '平均 ROE', v: fmt(avg('roe')), sub: '组内中位', unit: '%' },
  ]
})

const resultSubtitle = computed(() => {
  const map = {
    balanced: '全市场 · PE 由低到高',
    value: '价值因子 · PE + ROE',
    sized: '大市值 · 按市值排序',
    all: '全部股票 · 已放宽条件',
  }
  return map[filterMode.value]
})

function bullScore(it) {
  let s = 60
  if (it.pe && it.pe > 0) s += Math.max(0, Math.min(20, 25 - it.pe * 0.5))
  if (it.dividend_yield) s += Math.min(15, it.dividend_yield * 2)
  if (it.roe) s += Math.min(15, it.roe)
  return Math.round(Math.max(0, Math.min(99, s)))
}

const fmtNum = (v, d = 2) => v != null ? v.toFixed(d) : '—'
const fmtPositive = (v, d = 2) => v != null && v > 0 ? v.toFixed(d) : '—'

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
    render: (_, i) => h('span', { style: { color: Preview.textMuted, fontFamily: 'IBM Plex Mono, monospace', fontSize: '10px' } }, String(i + 1).padStart(2, '0')),
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
    title: '现价',
    key: 'close',
    align: 'right',
    width: 76,
    render: (s) => rightMonoCell(fmtNum(s.close), { color: Preview.textMain, fontWeight: 700 }),
  },
  {
    title: '涨跌幅',
    key: 'change_pct',
    align: 'right',
    width: 84,
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
    render: (s) => rightMonoCell(fmtPositive(s.pe)),
  },
  {
    title: 'PB',
    key: 'pb',
    align: 'right',
    width: 70,
    render: (s) => rightMonoCell(fmtNum(s.pb)),
  },
  {
    title: 'ROE',
    key: 'roe',
    align: 'right',
    width: 76,
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
    render: (s) => h('span', {
      style: { display: 'block', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace' },
    }, [
      s.market_cap != null ? Math.round(s.market_cap).toLocaleString() : '—',
      h('span', { style: { color: Preview.textMuted, fontSize: '9px' } }, '亿'),
    ]),
  },
  {
    title: '价值分',
    key: 'score',
    align: 'right',
    width: 96,
    render: (s) => h('div', {
      title: '价值分 = 60 + 低 PE 加分 + 股息率 + ROE',
      style: { display: 'inline-flex', alignItems: 'center', gap: '4px', justifyContent: 'flex-end', width: '100%' },
    }, [
      h(NProgress, { type: 'line', percentage: bullScore(s), height: 4, showIndicator: false, style: { width: '36px' } }),
      h('span', { style: { fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, fontSize: '10.5px' } }, bullScore(s)),
    ]),
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
  loading.value = true
  errorMsg.value = ''
  try {
    const data = await screen(conditionSets[filterMode.value], {
      sort_by: filterMode.value === 'sized' ? 'market_cap' : 'pe',
      sort_desc: filterMode.value === 'sized',
      limit: 50,
    })
    items.value = data.items
    total.value = data.total
  } catch (e) {
    errorMsg.value = e.response?.data?.detail || e.message
  } finally {
    loading.value = false
  }
}

function applyMode(mode) {
  filterMode.value = mode
  load()
}

function gotoDetail(code) {
  router.push(`/detail/${code}`)
}

function rowProps(row) {
  return {
    style: 'cursor: pointer;',
    onClick: () => gotoDetail(row.code),
  }
}

onMounted(load)
</script>

<template>
  <Shell>
    <div class="results-page">
      <!-- Top Bar: Title + Filter Tags + Actions -->
      <div class="results-topbar">
        <div class="results-title-row">
          <h2 class="results-title">筛选结果</h2>
          <span class="results-total">
            共 <strong>{{ total }}</strong> 只 · {{ resultSubtitle }}
          </span>
        </div>
        <NSpace size="small">
          <NButton
            :type="filterMode === 'balanced' ? 'primary' : 'default'"
            size="small"
            secondary
            @click="applyMode('balanced')"
          >
            平衡
          </NButton>
          <NButton
            :type="filterMode === 'value' ? 'primary' : 'default'"
            size="small"
            secondary
            @click="applyMode('value')"
          >
            价值
          </NButton>
          <NButton
            :type="filterMode === 'sized' ? 'primary' : 'default'"
            size="small"
            secondary
            @click="applyMode('sized')"
          >
            大市值
          </NButton>
          <NButton text size="small" type="primary" @click="router.push('/chat')">
            自然语言筛选
          </NButton>
          <NButton type="primary" size="small" :loading="loading" @click="load">
            重新筛选
          </NButton>
        </NSpace>
      </div>

      <!-- Filter Condition Tags -->
      <NCard size="small" class="results-card filter-card">
        <div class="filter-tags">
          <template v-for="g in filterGroups" :key="g.cat">
            <span class="filter-cat-name">{{ g.cat }}</span>
            <NTag v-for="it in g.items" :key="it.l" size="small" :bordered="false" class="filter-tag-pill">
              {{ it.l }}: {{ it.v }}
            </NTag>
          </template>
        </div>
      </NCard>

      <!-- Error -->
      <NAlert v-if="errorMsg" type="error" :bordered="false" class="error-alert">
        <div class="error-row">
          <span>{{ errorMsg }}</span>
          <NButton size="tiny" secondary :loading="loading" @click="load">重试</NButton>
        </div>
      </NAlert>

      <!-- Stats -->
      <NGrid :cols="5" :x-gap="10" :y-gap="10" class="stats-grid">
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
      <NCard :bordered="false" class="results-card table-card">
        <div v-if="loading" class="results-skeleton">
          <div v-for="n in 8" :key="'sk' + n" class="skeleton-row">
            <NSkeleton v-for="(_, ci) in 13" :key="ci" :height="12" :width="55" :sharp="false" />
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
          size="small"
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
  font-size: 34px;
  font-weight: 800;
  color: #111111;
  letter-spacing: -0.8px;
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
  padding: 14px 0;
}

.filter-tags {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
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
</style>
