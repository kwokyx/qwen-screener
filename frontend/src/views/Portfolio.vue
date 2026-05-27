<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import PctChip from '../components/charts/PctChip.vue'
import StarButton from '../components/StarButton.vue'
import AlertRuleEditor from '../components/AlertRuleEditor.vue'
import EmptyState from '../components/EmptyState.vue'
import { A2 } from '../shared/theme.js'
import { useWatchlistStore } from '../stores/watchlist'
import { detail as fetchDetail } from '../api/stock.js'
import { toast } from '../stores/toast'

const router = useRouter()
const gotoDetail = (code) => router.push(`/detail/${code}`)
const wl = useWatchlistStore()

const loading = ref(false)
const errorMsg = ref('')
const details = ref({})  // { code: detailObj }

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

// 给每只自选股拼一个统一对象（合并 watchlist + detail）
const rows = computed(() => wl.items.map((w) => {
  const d = details.value[w.code] || {}
  const latest = d.latest || {}
  const close = latest.close
  const ref_price = w.refPrice
  const sinceCost = (close != null && ref_price) ? (close - ref_price) / ref_price * 100 : null
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
    refPrice: ref_price,
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
  let topGainer = null, topLoser = null
  withPct.forEach(r => {
    if (!topGainer || r.changePct > topGainer.changePct) topGainer = r
    if (!topLoser || r.changePct < topLoser.changePct) topLoser = r
  })
  const alertsCount = rows.value.reduce((s, r) => s + (r.alerts?.length || 0), 0)
  return { total, up, flat, down, avg, topGainer, topLoser, alertsCount }
})

// 行业分布（真实，自选股聚合）
const SECTOR_COLORS = ['#2456D8', '#DC2626', '#7C3AED', '#059669', '#D97706', '#0EA5E9', '#EC4899', '#9CA3AF']
const sectorAlloc = computed(() => {
  const map = new Map()
  for (const r of rows.value) {
    const k = r.industry || '未分类'
    map.set(k, (map.get(k) || 0) + 1)
  }
  const total = rows.value.length || 1
  const entries = [...map.entries()].sort((a, b) => b[1] - a[1])
  return entries.map(([l, n], i) => ({
    l,
    n,
    pct: Number((n / total * 100).toFixed(1)),
    c: SECTOR_COLORS[i % SECTOR_COLORS.length],
  }))
})

const donutArcs = computed(() => {
  const data = sectorAlloc.value
  const size = 108
  const total = data.reduce((s, d) => s + d.pct, 0) || 1
  const r = size / 2 - 6, cx = size / 2, cy = size / 2
  let acc = 0
  const arcs = data.map(d => {
    const start = (acc / total) * 2 * Math.PI - Math.PI / 2
    acc += d.pct
    const end = (acc / total) * 2 * Math.PI - Math.PI / 2
    const large = end - start > Math.PI ? 1 : 0
    const x1 = cx + r * Math.cos(start), y1 = cy + r * Math.sin(start)
    const x2 = cx + r * Math.cos(end), y2 = cy + r * Math.sin(end)
    return { d: `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`, c: d.c }
  })
  return { arcs, size, cx, cy, r }
})

// 自选股的告警规则汇总
const allAlerts = computed(() => {
  const out = []
  for (const r of rows.value) {
    for (const a of r.alerts) {
      out.push({ ...a, code: r.code, name: r.name })
    }
  }
  return out
})

const fmtMC = (v) => v == null ? '—' : (v >= 10000 ? (v / 10000).toFixed(1) + '万亿' : v >= 1 ? v.toFixed(1) + '亿' : '<1亿')
const fmtPE = (v) => v == null ? '—' : v < 0 ? '亏损' : v.toFixed(1)
const fmtROE = (v) => v == null ? '—' : (v.toFixed(1) + '%')
const fmtDays = (ts) => {
  if (!ts) return '—'
  const d = Math.floor((Date.now() / 1000 - ts) / 86400)
  return d <= 0 ? '今天' : `${d} 天`
}
</script>

<template>
  <Shell>
    <div class="mobile-stack" :style="{ flex: 1, overflow: 'auto', padding: '16px' }">
      <!-- Hero summary -->
      <div :style="{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '10px', marginBottom: '12px' }">
        <div class="card" :style="{ padding: '14px 16px' }">
          <div :style="{ fontSize: '11px', color: A2.textMuted, fontWeight: 600 }">自选数</div>
          <div :style="{ fontSize: '26px', fontWeight: 800, fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '-1px', marginTop: '4px' }">{{ summary.total }}</div>
          <div :style="{ fontSize: '11px', color: A2.textMuted, marginTop: '2px' }">告警规则 {{ summary.alertsCount }} 条</div>
        </div>
        <div class="card" :style="{ padding: '14px 16px' }">
          <div :style="{ fontSize: '11px', color: A2.textMuted, fontWeight: 600 }">今日涨跌分布</div>
          <div :style="{ display: 'flex', alignItems: 'baseline', gap: '8px', marginTop: '4px' }">
            <span :style="{ fontSize: '20px', fontWeight: 800, fontFamily: 'IBM Plex Mono, monospace', color: A2.up }">{{ summary.up }}</span>
            <span :style="{ fontSize: '13px', color: A2.textMuted }">/</span>
            <span :style="{ fontSize: '20px', fontWeight: 800, fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ summary.flat }}</span>
            <span :style="{ fontSize: '13px', color: A2.textMuted }">/</span>
            <span :style="{ fontSize: '20px', fontWeight: 800, fontFamily: 'IBM Plex Mono, monospace', color: A2.down }">{{ summary.down }}</span>
          </div>
          <div :style="{ fontSize: '11px', color: A2.textMuted, marginTop: '2px' }">涨 / 平 / 跌</div>
        </div>
        <div class="card" :style="{ padding: '14px 16px' }">
          <div :style="{ fontSize: '11px', color: A2.textMuted, fontWeight: 600 }">自选平均涨幅</div>
          <div :style="{ marginTop: '4px' }">
            <PctChip v-if="summary.avg != null" :pct="summary.avg" size="md" />
            <span v-else :style="{ color: A2.textDim, fontSize: '14px' }">—</span>
          </div>
          <div :style="{ fontSize: '11px', color: A2.textMuted, marginTop: '4px' }">基于今日 vs 上一交易日</div>
        </div>
        <div class="card" :style="{ padding: '14px 16px' }">
          <div :style="{ fontSize: '11px', color: A2.textMuted, fontWeight: 600 }">今日领涨 / 领跌</div>
          <div v-if="summary.topGainer || summary.topLoser" :style="{ marginTop: '6px', display: 'flex', flexDirection: 'column', gap: '3px', fontSize: '12px' }">
            <div v-if="summary.topGainer" :style="{ display: 'flex', justifyContent: 'space-between', gap: '8px' }">
              <span :style="{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">{{ summary.topGainer.name }}</span>
              <PctChip :pct="summary.topGainer.changePct" size="sm" />
            </div>
            <div v-if="summary.topLoser" :style="{ display: 'flex', justifyContent: 'space-between', gap: '8px' }">
              <span :style="{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">{{ summary.topLoser.name }}</span>
              <PctChip :pct="summary.topLoser.changePct" size="sm" />
            </div>
          </div>
          <div v-else :style="{ marginTop: '6px', color: A2.textDim, fontSize: '13px' }">—</div>
        </div>
      </div>

      <!-- Main grid -->
      <div :style="{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '10px' }">
        <!-- 自选明细表 -->
        <div class="card card-overflow-hidden">
          <div :style="{ display: 'flex', alignItems: 'center', padding: '12px 16px', borderBottom: `1px solid ${A2.borderHair}` }">
            <div :style="{ fontSize: '13px', fontWeight: 700 }">自选明细</div>
            <div v-if="loading" :style="{ marginLeft: '10px', fontSize: '11px', color: A2.textMuted }">加载中…</div>
            <div style="flex:1" />
            <button class="btn-outline" :style="{ padding: '4px 10px', fontSize: '11px' }" @click="loadAll" :disabled="loading">
              <Icon name="refresh" :size="11" /> 刷新
            </button>
          </div>

          <table :style="{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }">
            <thead>
              <tr :style="{ color: A2.textMuted, fontSize: '10px', fontWeight: 600, letterSpacing: '0.5px' }">
                <th :style="{ textAlign: 'left', padding: '8px 16px', fontWeight: 600 }">名称 / 代码</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">现价</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">今日</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">PE</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">PB</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">ROE</th>
                <th :style="{ textAlign: 'left', padding: '8px 12px', fontWeight: 600 }">行业</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">加入价 / 至今</th>
                <th :style="{ textAlign: 'right', padding: '8px 6px', fontWeight: 600 }">关注</th>
                <th :style="{ textAlign: 'right', padding: '8px 16px', fontWeight: 600 }">告警</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!rows.length">
                <td colspan="10" :style="{ padding: 0 }">
                  <EmptyState icon="star" title="自选列表为空"
                              subtitle="在 ⌘K 搜索 / 行情 / 条件选股 / 详情页点星标加入" />
                </td>
              </tr>
              <tr v-for="r in rows" :key="r.code" class="row-hover"
                  @click="gotoDetail(r.code)"
                  :style="{ borderTop: `1px solid ${A2.borderHair}`, cursor: 'pointer' }">
                <td :style="{ padding: '11px 16px' }">
                  <div :style="{ display: 'flex', alignItems: 'center', gap: '8px' }">
                    <StarButton :stock="{ code: r.code, name: r.name, sector: r.industry, refPrice: r.refPrice }" :size="13" @click.stop />
                    <div>
                      <div :style="{ fontWeight: 600, fontSize: '13px' }">{{ r.name }}</div>
                      <div :style="{ fontSize: '10px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace' }">{{ r.code }}</div>
                    </div>
                  </div>
                </td>
                <td :style="{ padding: '11px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700,
                              color: r.changePct == null ? A2.textSub : (r.changePct >= 0 ? A2.up : A2.down) }">
                  {{ r.close != null ? r.close.toFixed(2) : '—' }}
                </td>
                <td :style="{ padding: '11px 6px', textAlign: 'right' }">
                  <PctChip v-if="r.changePct != null" :pct="r.changePct" size="sm" />
                  <span v-else :style="{ color: A2.textDim }">—</span>
                </td>
                <td :style="{ padding: '11px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ fmtPE(r.pe) }}</td>
                <td :style="{ padding: '11px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ r.pb != null ? r.pb.toFixed(2) : '—' }}</td>
                <td :style="{ padding: '11px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ fmtROE(r.roe) }}</td>
                <td :style="{ padding: '11px 12px', color: A2.textSub, fontSize: '11.5px' }">{{ r.industry || '—' }}</td>
                <td :style="{ padding: '11px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', fontSize: '11px' }">
                  <div :style="{ color: A2.textMuted }">{{ r.refPrice != null ? r.refPrice.toFixed(2) : '—' }}</div>
                  <div v-if="r.sinceCost != null" :style="{ marginTop: '1px' }">
                    <PctChip :pct="r.sinceCost" size="sm" />
                  </div>
                </td>
                <td :style="{ padding: '11px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textMuted, fontSize: '11px' }">
                  {{ fmtDays(r.addedAt) }}
                </td>
                <td :style="{ padding: '11px 16px', textAlign: 'right' }" @click.stop>
                  <AlertRuleEditor :code="r.code" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 右栏 -->
        <div :style="{ display: 'flex', flexDirection: 'column', gap: '10px' }">
          <!-- 行业分布 -->
          <div class="card card-pad">
            <div :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }">
              <div :style="{ fontSize: '13px', fontWeight: 700 }">行业分布</div>
              <span :style="{ fontSize: '10px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace' }">{{ rows.length }} 只</span>
            </div>
            <div v-if="!rows.length" :style="{ padding: '24px 0', textAlign: 'center', color: A2.textDim, fontSize: '12px' }">无数据</div>
            <div v-else :style="{ display: 'flex', alignItems: 'center', gap: '12px' }">
              <svg :width="donutArcs.size" :height="donutArcs.size" :viewBox="`0 0 ${donutArcs.size} ${donutArcs.size}`">
                <path v-for="(a, i) in donutArcs.arcs" :key="i" :d="a.d" :fill="a.c" />
                <circle :cx="donutArcs.cx" :cy="donutArcs.cy" :r="donutArcs.r * 0.62" fill="#fff" />
                <text :x="donutArcs.cx" :y="donutArcs.cy - 2" text-anchor="middle" font-size="10" fill="#7A776F" font-weight="500">行业</text>
                <text :x="donutArcs.cx" :y="donutArcs.cy + 12" text-anchor="middle" font-size="13" fill="#0E0E0C" font-weight="700" font-family="IBM Plex Mono, monospace">{{ sectorAlloc.length }}</text>
              </svg>
              <div :style="{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }">
                <div v-for="s in sectorAlloc" :key="s.l" :style="{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px' }">
                  <div :style="{ width: '8px', height: '8px', background: s.c, borderRadius: '2px' }" />
                  <span :style="{ flex: 1, color: A2.textSub, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">{{ s.l }}</span>
                  <span :style="{ fontFamily: 'IBM Plex Mono, monospace', color: A2.text, fontWeight: 600 }">{{ s.n }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 告警规则 -->
          <div class="card card-overflow-hidden" :style="{ flex: 1 }">
            <div :style="{ padding: '12px 16px', borderBottom: `1px solid ${A2.borderHair}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }">
              <div :style="{ fontSize: '13px', fontWeight: 700 }">已设告警</div>
              <span :style="{ fontSize: '10px', padding: '2px 6px', background: A2.bgDeep, color: A2.textSub, borderRadius: '3px', fontWeight: 600, fontFamily: 'IBM Plex Mono, monospace' }">{{ allAlerts.length }} 条</span>
            </div>
            <div v-if="!allAlerts.length" :style="{ padding: '24px 16px', textAlign: 'center', color: A2.textDim, fontSize: '12px' }">
              点击表格右侧的"+"按钮设置价格 / 涨跌幅告警
            </div>
            <div v-else>
              <div v-for="(a, i) in allAlerts" :key="i" class="row-hover"
                   @click="gotoDetail(a.code)"
                   :style="{ padding: '10px 16px', borderTop: i ? `1px solid ${A2.borderHair}` : 'none', cursor: 'pointer' }">
                <div :style="{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }">
                  <span :style="{ fontSize: '12px', fontWeight: 700 }">{{ a.name }}</span>
                  <span :style="{ fontSize: '10px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace' }">{{ a.code }}</span>
                </div>
                <div :style="{ fontSize: '11px', color: A2.textSub }">
                  <span v-if="a.type === 'pct_up'">累计涨幅 ≥ {{ a.threshold }}%</span>
                  <span v-else-if="a.type === 'pct_down'">累计跌幅 ≥ {{ a.threshold }}%</span>
                  <span v-else-if="a.type === 'price_gt'">现价 ≥ ¥{{ a.threshold }}</span>
                  <span v-else-if="a.type === 'price_lt'">现价 ≤ ¥{{ a.threshold }}</span>
                  <span v-else-if="a.type === 'day_pct'">日内涨跌 ≥ {{ a.threshold }}%</span>
                  <span v-else>{{ a.type }} · {{ a.threshold }}</span>
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
