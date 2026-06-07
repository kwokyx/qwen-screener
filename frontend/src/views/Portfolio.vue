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
  NSpace,
  NTag,
} from 'naive-ui'
import Shell from '../components/Shell.vue'
import PctChip from '../components/charts/PctChip.vue'
import StarButton from '../components/StarButton.vue'
import AlertRuleEditor from '../components/AlertRuleEditor.vue'
import { Preview } from '../shared/theme.js'
import { useWatchlistStore } from '../stores/watchlist'
import { detail as fetchDetail } from '../api/stock.js'
import { toast } from '../stores/toast'

const router = useRouter()
const gotoDetail = (code) => router.push(`/detail/${code}`)
const wl = useWatchlistStore()

const loading = ref(false)
const errorMsg = ref('')
const details = ref({})

async function loadAll() {
  if (!wl.items.length) {
    details.value = {}
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const results = await Promise.allSettled(wl.items.map(w => fetchDetail(w.code)))
    const map = {}
    results.forEach((r, i) => {
      if (r.status === 'fulfilled') map[wl.items[i].code] = r.value
    })
    details.value = map
  } catch (e) {
    errorMsg.value = e?.message || '加载失败'
    toast.error(`自选数据加载失败：${errorMsg.value}`)
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)
watch(() => wl.items.length, loadAll)

const rows = computed(() => wl.items.map((w) => {
  const d = details.value[w.code] || {}
  const latest = d.latest || {}
  const close = latest.close
  const refPrice = w.refPrice
  const sinceCost = (close != null && refPrice) ? (close - refPrice) / refPrice * 100 : null
  return {
    code: w.code,
    name: w.name || d.name || w.code,
    industry: d.industry || w.sector || null,
    close,
    changePct: d.change_pct,
    pe: latest.pe,
    pb: latest.pb,
    marketCap: latest.market_cap,
    roe: d.roe,
    refPrice,
    sinceCost,
    addedAt: w.addedAt,
    alerts: w.alerts || [],
  }
}))

const summary = computed(() => {
  const total = rows.value.length
  const withPct = rows.value.filter(r => r.changePct != null)
  const up = withPct.filter(r => r.changePct > 0).length
  const flat = withPct.filter(r => r.changePct === 0).length
  const down = withPct.filter(r => r.changePct < 0).length
  const avg = withPct.length ? withPct.reduce((s, r) => s + r.changePct, 0) / withPct.length : null
  let topGainer = null
  let topLoser = null
  withPct.forEach(r => {
    if (!topGainer || r.changePct > topGainer.changePct) topGainer = r
    if (!topLoser || r.changePct < topLoser.changePct) topLoser = r
  })
  const alertsCount = rows.value.reduce((s, r) => s + (r.alerts?.length || 0), 0)
  return { total, up, flat, down, avg, topGainer, topLoser, alertsCount }
})

const sectorAlloc = computed(() => {
  const map = new Map()
  for (const r of rows.value) {
    const k = r.industry || '未分类'
    map.set(k, (map.get(k) || 0) + 1)
  }
  const total = rows.value.length || 1
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([label, count]) => ({
      label,
      count,
      pct: Number((count / total * 100).toFixed(1)),
    }))
})

const allAlerts = computed(() => {
  const out = []
  for (const r of rows.value) {
    for (const a of r.alerts) out.push({ ...a, code: r.code, name: r.name })
  }
  return out
})

const fmtPE = (v) => v == null ? '—' : v < 0 ? '亏损' : v.toFixed(1)
const fmtROE = (v) => v == null ? '—' : `${v.toFixed(1)}%`
const fmtNum = (v, digits = 2) => v == null ? '—' : Number(v).toFixed(digits)
const fmtDate = (ts) => {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  if (Number.isNaN(d.getTime())) return '—'
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}
const alertText = (a) => {
  if (a.type === 'pct_up') return `累计涨幅 >= ${a.threshold}%`
  if (a.type === 'pct_down') return `累计跌幅 >= ${a.threshold}%`
  if (a.type === 'price_gt') return `现价 >= ${a.threshold} 元`
  if (a.type === 'price_lt') return `现价 <= ${a.threshold} 元`
  if (a.type === 'day_pct') return `日内涨跌 >= ${a.threshold}%`
  return `${a.type || '规则'} · ${a.threshold ?? '—'}`
}

function mono(text, extra = {}) {
  return h('span', { class: 'mono', style: extra }, text)
}

function pctNode(value, size = 'sm') {
  return value == null ? mono('—', { color: Preview.textFaint }) : h(PctChip, { pct: value, size })
}

const watchColumns = computed(() => [
  {
    title: '名称 / 代码',
    key: 'name',
    minWidth: 180,
    render(row) {
      return h('div', { class: 'stock-cell' }, [
        h('div', { onClick: e => e.stopPropagation() }, [
          h(StarButton, {
            stock: { code: row.code, name: row.name, sector: row.industry, refPrice: row.refPrice },
            size: 13,
          }),
        ]),
        h('div', [
          h('div', { class: 'stock-name' }, row.name),
          h('div', { class: 'stock-code mono' }, row.code),
        ]),
      ])
    },
  },
  {
    title: '现价',
    key: 'close',
    align: 'right',
    sorter: (a, b) => (a.close ?? -Infinity) - (b.close ?? -Infinity),
    render: row => mono(fmtNum(row.close), { color: row.changePct == null ? Preview.textMain : (row.changePct >= 0 ? Preview.positive : Preview.negative), fontWeight: 700 }),
  },
  {
    title: '今日',
    key: 'changePct',
    align: 'right',
    sorter: (a, b) => (a.changePct ?? -Infinity) - (b.changePct ?? -Infinity),
    render: row => pctNode(row.changePct),
  },
  { title: 'PE', key: 'pe', align: 'right', render: row => mono(fmtPE(row.pe), { color: Preview.textMuted }) },
  { title: 'PB', key: 'pb', align: 'right', render: row => mono(row.pb == null ? '—' : row.pb.toFixed(2), { color: Preview.textMuted }) },
  { title: 'ROE', key: 'roe', align: 'right', render: row => mono(fmtROE(row.roe), { color: Preview.textMuted }) },
  {
    title: '行业',
    key: 'industry',
    minWidth: 100,
    render: row => row.industry
      ? h(NTag, { size: 'small', bordered: false, round: true }, { default: () => row.industry })
      : mono('—', { color: Preview.textFaint }),
  },
  {
    title: '加入价 / 至今',
    key: 'sinceCost',
    align: 'right',
    minWidth: 125,
    render(row) {
      return h('div', { class: 'cost-cell' }, [
        mono(row.refPrice == null ? '—' : row.refPrice.toFixed(2), { color: Preview.textMuted }),
        pctNode(row.sinceCost),
      ])
    },
  },
  { title: '加入日期', key: 'addedAt', align: 'right', render: row => mono(fmtDate(row.addedAt), { color: Preview.textMuted }) },
  {
    title: '预警',
    key: 'alerts',
    align: 'right',
    minWidth: 105,
    render(row) {
      return h('div', { onClick: e => e.stopPropagation() }, [
        h(AlertRuleEditor, { code: row.code }),
      ])
    },
  },
])

const alertColumns = computed(() => [
  {
    title: '股票',
    key: 'name',
    render(row) {
      return h('div', [
        h('div', { class: 'stock-name' }, row.name),
        h('div', { class: 'stock-code mono' }, row.code),
      ])
    },
  },
  { title: '规则', key: 'rule', render: row => h('span', { class: 'muted' }, alertText(row)) },
  {
    title: '状态',
    key: 'enabled',
    align: 'right',
    width: 84,
    render: row => h(NTag, {
      size: 'small',
      type: row.enabled === false ? 'default' : 'success',
      bordered: false,
      round: true,
    }, { default: () => row.enabled === false ? '暂停' : '启用' }),
  },
])

const rowProps = (row) => ({
  style: 'cursor: pointer;',
  onClick: () => gotoDetail(row.code),
})
</script>

<template>
  <Shell>
    <div class="portfolio-page">
      <NAlert v-if="errorMsg" type="error" :bordered="false" class="section-gap">
        {{ errorMsg }}
      </NAlert>

      <NGrid :cols="4" :x-gap="12" :y-gap="12" responsive="screen" item-responsive class="section-gap">
        <NGi span="4 s:2 m:1">
          <NCard :bordered="false" class="metric-card">
            <div class="metric-label">自选数</div>
            <div class="metric-number mono">{{ summary.total }}</div>
            <div class="metric-foot">告警规则 {{ summary.alertsCount }} 条</div>
          </NCard>
        </NGi>
        <NGi span="4 s:2 m:1">
          <NCard :bordered="false" class="metric-card">
            <div class="metric-label">今日涨跌分布</div>
            <div class="trend-split">
              <span class="mono up">{{ summary.up }}</span>
              <span class="split-sep">/</span>
              <span class="mono flat">{{ summary.flat }}</span>
              <span class="split-sep">/</span>
              <span class="mono down">{{ summary.down }}</span>
            </div>
            <div class="metric-foot">涨 / 平 / 跌</div>
          </NCard>
        </NGi>
        <NGi span="4 s:2 m:1">
          <NCard :bordered="false" class="metric-card">
            <div class="metric-label">自选平均涨幅</div>
            <div class="metric-main">
              <PctChip v-if="summary.avg != null" :pct="summary.avg" size="md" />
              <span v-else class="empty-dash">—</span>
            </div>
            <div class="metric-foot">基于今日 vs 上一交易日</div>
          </NCard>
        </NGi>
        <NGi span="4 s:2 m:1">
          <NCard :bordered="false" class="metric-card">
            <div class="metric-label">今日领涨 / 领跌</div>
            <NSpace v-if="summary.topGainer || summary.topLoser" vertical :size="4" class="leader-list">
              <div v-if="summary.topGainer" class="leader-row">
                <span>{{ summary.topGainer.name }}</span>
                <PctChip :pct="summary.topGainer.changePct" size="sm" />
              </div>
              <div v-if="summary.topLoser" class="leader-row">
                <span>{{ summary.topLoser.name }}</span>
                <PctChip :pct="summary.topLoser.changePct" size="sm" />
              </div>
            </NSpace>
            <div v-else class="empty-dash">—</div>
          </NCard>
        </NGi>
      </NGrid>

      <NGrid :cols="3" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
        <NGi span="3 l:2">
          <NCard :bordered="false" title="自选明细" class="panel-card">
            <template #header-extra>
              <NButton size="small" secondary :loading="loading" @click="loadAll">刷新</NButton>
            </template>
            <NDataTable
              v-if="rows.length"
              :columns="watchColumns"
              :data="rows"
              :loading="loading"
              :row-props="rowProps"
              :bordered="false"
              :single-line="false"
              size="small"
            />
            <NEmpty v-else description="自选列表为空" class="empty-panel">
              <template #extra>
                <span class="muted">在搜索、行情、详情页点星标加入</span>
              </template>
            </NEmpty>
          </NCard>
        </NGi>

        <NGi span="3 l:1">
          <NSpace vertical :size="12">
            <NCard :bordered="false" class="panel-card">
              <template #header>
                <div class="panel-title">
                  <span>行业分布</span>
                  <NTag size="small" round :bordered="false">{{ rows.length }} 只</NTag>
                </div>
              </template>
              <NEmpty v-if="!sectorAlloc.length" description="暂无行业数据" class="small-empty" />
              <NSpace v-else vertical :size="10">
                <div v-for="s in sectorAlloc" :key="s.label" class="sector-row">
                  <div class="sector-top">
                    <span>{{ s.label }}</span>
                    <span class="mono">{{ s.count }} · {{ s.pct }}%</span>
                  </div>
                  <NProgress
                    type="line"
                    :percentage="s.pct"
                    :height="8"
                    :show-indicator="false"
                    color="#111111"
                    rail-color="#E7E7E7"
                  />
                </div>
              </NSpace>
            </NCard>

            <NCard :bordered="false" title="已设告警" class="panel-card">
              <template #header-extra>
                <NTag size="small" round :bordered="false">{{ allAlerts.length }} 条</NTag>
              </template>
              <NDataTable
                v-if="allAlerts.length"
                :columns="alertColumns"
                :data="allAlerts"
                :bordered="false"
                :single-line="false"
                :row-props="rowProps"
                size="small"
              />
              <NEmpty v-else description="暂无告警规则" class="small-empty">
                <template #extra>
                  <span class="muted">在自选明细右侧设置价格 / 涨跌幅告警</span>
                </template>
              </NEmpty>
            </NCard>
          </NSpace>
        </NGi>
      </NGrid>
    </div>
  </Shell>
</template>

<style scoped>
.portfolio-page {
  min-height: 100%;
  padding: 16px;
  background: #ffffff;
}
.section-gap {
  margin-bottom: 12px;
}
.metric-card,
.panel-card {
  border-radius: 8px;
  background: #f7f7f7;
}
.metric-card {
  height: 100%;
}
.metric-card :deep(.n-card__content) {
  min-height: 136px;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
}
.metric-label,
.metric-foot,
.muted {
  color: #71717a;
}
.metric-label {
  font-size: 12px;
  font-weight: 650;
}
.metric-number {
  margin-top: 20px;
  font-size: 26px;
  line-height: 1;
  font-weight: 800;
  color: #3f3f46;
}
.metric-foot,
.metric-card :deep(.n-card__footer) {
  margin-top: auto;
  padding-top: 14px;
  font-size: 12px;
}
.metric-main {
  margin-top: 10px;
}
.trend-split {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-top: 8px;
  font-size: 24px;
  font-weight: 800;
}
.split-sep,
.flat,
.empty-dash {
  color: #a1a1aa;
}
.up {
  color: #e04f76;
}
.down {
  color: #16a35c;
}
.leader-list {
  margin-top: 8px;
}
.leader-row,
.panel-title,
.sector-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.leader-row span:first-child,
.sector-top span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stock-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.stock-name {
  font-size: 13px;
  font-weight: 700;
  color: #111111;
}
.stock-code {
  margin-top: 2px;
  font-size: 11px;
  color: #71717a;
}
.mono {
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
.cost-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 3px;
}
.empty-panel {
  padding: 44px 0;
}
.small-empty {
  padding: 22px 0;
}
.sector-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sector-top {
  font-size: 12px;
}
.sector-top .mono {
  color: #71717a;
}
.panel-card :deep(.n-data-table-th) {
  color: #71717a;
  font-size: 12px;
  font-weight: 650;
  background: transparent;
}
.panel-card :deep(.n-data-table-td) {
  background: transparent;
}
.panel-card :deep(.n-data-table-tr:hover .n-data-table-td) {
  background: #eeeeee;
}
@media (max-width: 760px) {
  .portfolio-page {
    padding: 12px;
  }
}
</style>
