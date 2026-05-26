<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import Sparkline from '../components/charts/Sparkline.vue'
import PctChip from '../components/charts/PctChip.vue'
import PctText from '../components/charts/PctText.vue'
import StarButton from '../components/StarButton.vue'
import Skeleton from '../components/Skeleton.vue'
import EmptyState from '../components/EmptyState.vue'
import { A2 } from '../shared/theme.js'
import { friendlyError } from '../shared/errors.js'
import * as marketApi from '../api/market'
import { useKlineCache } from '../composables/useKlineCache.js'

const router = useRouter()

function gotoDetail(code) { router.push(`/detail/${code}`) }
function goToScreener(query) { router.push({ path: '/chat', query: { q: query } }) }

const indices = ref([])
const sectors = ref([])
const movers = ref(null)
const tickerInfo = ref(null)              // {advancers, decliners, total_amount_yi, trade_date}
const moverTab = ref('gainers')
const loadingIndices = ref(true)
const loadingSectors = ref(true)
const loadingMovers = ref(true)
const errorMsg = ref('')

const moversShown = computed(() => (movers.value ? movers.value[moverTab.value] || [] : []))
const idxSpark = computed(() => indices.value.map((idx) => idx.spark || []))

// 涨跌榜真实 sparkline：composable 按 code 缓存 + 并行拉取
const { load: loadMoverKlines, get: moverSpark } = useKlineCache(30)

// 板块按涨跌幅切两半
const sectorsUp = computed(() => [...sectors.value].filter((s) => s.change_pct >= 0).sort((a, b) => b.change_pct - a.change_pct))
const sectorsDown = computed(() => [...sectors.value].filter((s) => s.change_pct < 0).sort((a, b) => a.change_pct - b.change_pct))

// 市场概况：上涨 / 下跌 / 总成交（涨停跌停 akshare 没接口，不编了）
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
  Promise.allSettled([
    marketApi.indices().then((d) => { indices.value = d }).finally(() => { loadingIndices.value = false }),
    marketApi.sectors(20).then((d) => { sectors.value = d }).finally(() => { loadingSectors.value = false }),
    marketApi.movers(10).then((d) => { movers.value = d; loadMoverKlines(moversShown.value.map((s) => s.code)) }).finally(() => { loadingMovers.value = false }),
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

const moversColumnLabel = computed(() => {
  if (moverTab.value === 'by_amount') return '成交额'
  if (moverTab.value === 'by_turnover') return '换手率'
  return '涨跌幅'
})

function moversValueColumn(s) {
  if (moverTab.value === 'by_amount') return s.amount != null ? s.amount.toFixed(1) + ' 亿' : '—'
  if (moverTab.value === 'by_turnover') return s.turnover != null ? s.turnover.toFixed(2) + '%' : '—'
  return null
}

onMounted(loadAll)
// 切换涨跌榜 tab 时拉新股票的 kline
watch(moverTab, () => loadMoverKlines(moversShown.value.map((s) => s.code)))
</script>

<template>
  <Shell>
    <div class="mobile-stack" :style="{ flex: 1, overflow: 'auto', padding: '12px 16px 16px' }">

      <!-- =============== Top: 4 indices · 紧凑布局 + 市场概况 =============== -->
      <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr) 280px', gap: '10px', marginBottom: '10px' }">
        <template v-if="loadingIndices && !indices.length">
          <div v-for="n in 4" :key="n" :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, padding: '12px 14px', borderRadius: '8px', boxShadow: A2.shadow }">
            <Skeleton :width="70" :height="11" :style="{ marginBottom: '6px' }" />
            <Skeleton :width="100" :height="20" :style="{ marginBottom: '4px' }" />
            <Skeleton :width="60" :height="10" />
          </div>
        </template>
        <div v-else v-for="(idx, i) in indices" :key="idx.code"
             :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, padding: '12px 14px', borderRadius: '8px', position: 'relative', overflow: 'hidden', boxShadow: A2.shadow, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: '88px' }">
          <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }">
            <div>
              <div :style="{ fontSize: '12px', color: A2.textSub, fontWeight: 600 }">{{ idx.name }}</div>
              <div :style="{ fontSize: '9.5px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace', marginTop: '1px' }">{{ idx.code }} · {{ idx.constituents }} 只</div>
            </div>
            <Sparkline :data="idxSpark[i] || []" :width="60" :height="24" />
          </div>
          <div :style="{ display: 'flex', alignItems: 'baseline', gap: '6px', marginTop: '8px' }">
            <div :style="{ fontSize: '22px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '-0.5px', color: idx.change_pct >= 0 ? A2.up : A2.down, lineHeight: 1 }">
              {{ idx.value.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}
            </div>
            <div :style="{ fontSize: '11px', color: idx.change_pct >= 0 ? A2.up : A2.down, fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700 }">
              {{ idx.change >= 0 ? '+' : '' }}{{ idx.change.toFixed(2) }}
            </div>
            <PctText :pct="idx.change_pct" :size="11" />
          </div>
        </div>

        <!-- 市场概况 -->
        <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, padding: '12px 14px', borderRadius: '8px', boxShadow: A2.shadow }">
          <div :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }">
            <div :style="{ fontSize: '11px', color: A2.textMuted, fontWeight: 600, letterSpacing: '0.4px', textTransform: 'uppercase' }">市场概况</div>
            <span :style="{ fontSize: '9.5px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace' }">{{ marketStats?.tradeDate || '—' }}</span>
          </div>
          <div v-if="!marketStats" :style="{ display: 'flex', flexDirection: 'column', gap: '5px' }">
            <Skeleton :height="13" :width="'80%'" /><Skeleton :height="13" :width="'70%'" />
          </div>
          <div v-else :style="{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '12px' }">
            <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }">
              <span :style="{ color: A2.textMuted }">上涨</span>
              <span :style="{ color: A2.up, fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace' }">{{ marketStats.advancers.toLocaleString() }}</span>
            </div>
            <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }">
              <span :style="{ color: A2.textMuted }">下跌</span>
              <span :style="{ color: A2.down, fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace' }">{{ marketStats.decliners.toLocaleString() }}</span>
            </div>
            <div :style="{ borderTop: `1px solid ${A2.borderHair}`, paddingTop: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }">
              <span :style="{ color: A2.textMuted }">总成交</span>
              <span :style="{ color: A2.text, fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace' }">{{ marketStats.amount.toLocaleString() }} 亿</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 全局错误 -->
      <div v-if="errorMsg" :style="{ marginBottom: '10px', padding: '10px 14px', background: A2.upSoft, color: A2.up, borderRadius: '8px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '10px' }">
        <Icon name="alert" :size="14" />
        <span style="flex:1">{{ errorMsg }}</span>
        <button class="btn-outline" :style="{ padding: '4px 10px', fontSize: '11px' }" @click="loadAll">
          <Icon name="refresh" :size="11" /> 重试
        </button>
      </div>

      <!-- =============== Mid: 市场异动 (主) + 板块榜 (次) =============== -->
      <div :style="{ display: 'grid', gridTemplateColumns: '1.7fr 1fr', gap: '10px', marginBottom: '10px' }">
        <!-- 市场异动 -->
        <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '8px', overflow: 'hidden', boxShadow: A2.shadow }">
          <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '11px 14px', borderBottom: `1px solid ${A2.borderHair}` }">
            <div>
              <div :style="{ fontSize: '13px', fontWeight: 700 }">市场异动</div>
              <div :style="{ fontSize: '10.5px', color: A2.textMuted, marginTop: '1px' }">{{ tipsByTab[moverTab] }} · 点击进入个股</div>
            </div>
            <div :style="{ display: 'flex', gap: '2px', padding: '3px', background: A2.bgDeep, borderRadius: '6px' }">
              <div v-for="t in moverTabs" :key="t.id" @click="moverTab = t.id"
                   :style="{ padding: '5px 11px', background: moverTab === t.id ? A2.surface : 'transparent', color: moverTab === t.id ? A2.text : A2.textMuted, fontSize: '11px', fontWeight: moverTab === t.id ? 600 : 500, cursor: 'pointer', borderRadius: '4px', boxShadow: moverTab === t.id ? A2.shadow : 'none', transition: 'background 0.15s, color 0.15s' }">
                {{ t.label }}
              </div>
            </div>
          </div>
          <table :style="{ width: '100%', borderCollapse: 'collapse', fontSize: '11.5px' }">
            <thead>
              <tr :style="{ color: A2.textMuted, fontSize: '10px', fontWeight: 600, letterSpacing: '0.5px', background: '#FBFBF9' }">
                <th :style="{ textAlign: 'left', padding: '7px 14px', fontWeight: 600 }">代码</th>
                <th :style="{ textAlign: 'left', padding: '7px 6px', fontWeight: 600 }">名称</th>
                <th :style="{ textAlign: 'right', padding: '7px 6px', fontWeight: 600 }">现价</th>
                <th :style="{ textAlign: 'right', padding: '7px 6px', fontWeight: 600 }">涨跌幅</th>
                <th :style="{ textAlign: 'right', padding: '7px 6px', fontWeight: 600 }">成交额</th>
                <th :style="{ textAlign: 'right', padding: '7px 6px', fontWeight: 600 }">换手率</th>
                <th :style="{ textAlign: 'right', padding: '7px 6px', fontWeight: 600 }">PE</th>
                <th :style="{ textAlign: 'right', padding: '7px 6px', fontWeight: 600 }">市值</th>
                <th :style="{ textAlign: 'left', padding: '7px 6px', fontWeight: 600 }">所属</th>
                <th :style="{ textAlign: 'left', padding: '7px 14px', fontWeight: 600 }">30 日</th>
              </tr>
            </thead>
            <tbody>
              <template v-if="loadingMovers && !movers">
                <tr v-for="n in 8" :key="n" :style="{ borderTop: `1px solid ${A2.borderHair}` }">
                  <td v-for="ci in 10" :key="ci" :style="{ padding: '9px 6px' }">
                    <Skeleton :height="11" :width="ci === 2 || ci === 9 ? '70%' : '50%'" :style="{ marginLeft: ci > 2 && ci < 9 ? 'auto' : 0 }" />
                  </td>
                </tr>
              </template>
              <tr v-else-if="!moversShown.length">
                <td colspan="10" :style="{ padding: 0 }">
                  <EmptyState icon="chart" title="该榜单暂无数据" subtitle="行情服务暂时不可用，请稍后再试" compact />
                </td>
              </tr>
              <tr v-for="(s, i) in moversShown" :key="s.code" class="row-hover row-clickable"
                  @click="gotoDetail(s.code)"
                  :style="{ borderTop: `1px solid ${A2.borderHair}` }">
                <td :style="{ padding: '9px 14px', fontFamily: 'IBM Plex Mono, monospace', color: A2.textMuted, fontSize: '10.5px' }">{{ s.code.replace(/\.(SH|SZ)$/, '') }}</td>
                <td :style="{ padding: '9px 6px', fontWeight: 600, fontSize: '12.5px' }">
                  <div :style="{ display: 'flex', alignItems: 'center', gap: '4px' }">
                    <StarButton :stock="{ code: s.code, name: s.name, sector: s.industry, refPrice: s.close }" :size="12" />
                    <span>{{ s.name }}</span>
                  </div>
                </td>
                <td :style="{ padding: '9px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: (s.change_pct || 0) >= 0 ? A2.up : A2.down }">{{ s.close != null ? s.close.toFixed(2) : '—' }}</td>
                <td :style="{ padding: '9px 6px', textAlign: 'right' }">
                  <PctChip v-if="s.change_pct != null" :pct="s.change_pct" size="sm" />
                  <span v-else :style="{ color: A2.textDim }">—</span>
                </td>
                <td :style="{ padding: '9px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ s.amount != null ? s.amount.toFixed(1) + '亿' : '—' }}</td>
                <td :style="{ padding: '9px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ s.turnover != null ? s.turnover.toFixed(2) + '%' : '—' }}</td>
                <td :style="{ padding: '9px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ s.pe != null && s.pe > 0 ? s.pe.toFixed(1) : '—' }}</td>
                <td :style="{ padding: '9px 6px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ s.market_cap != null ? Math.round(s.market_cap).toLocaleString() : '—' }}<span :style="{ color: A2.textDim, fontSize: '9px' }">亿</span></td>
                <td :style="{ padding: '9px 6px' }">
                  <span :style="{ fontSize: '10px', padding: '2px 7px', background: A2.bgDeep, color: A2.textSub, borderRadius: '3px', fontWeight: 500 }">{{ s.industry || '—' }}</span>
                </td>
                <td :style="{ padding: '8px 14px' }"><Sparkline :data="moverSpark(s.code)" :width="76" :height="20" /></td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 板块涨跌排行（不再用 heatmap，改为双列 ranked list） -->
        <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '8px', overflow: 'hidden', boxShadow: A2.shadow, display: 'flex', flexDirection: 'column' }">
          <div :style="{ padding: '11px 14px', borderBottom: `1px solid ${A2.borderHair}` }">
            <div :style="{ fontSize: '13px', fontWeight: 700 }">板块涨跌</div>
            <div :style="{ fontSize: '10.5px', color: A2.textMuted, marginTop: '1px' }">申万一级 · 点击让千问深挖</div>
          </div>
          <div :style="{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0', flex: 1 }">
            <div :style="{ padding: '8px 0' }">
              <div v-if="loadingSectors && !sectors.length" :style="{ padding: '0 12px' }">
                <Skeleton v-for="n in 5" :key="n" :height="20" :style="{ marginBottom: '6px' }" />
              </div>
              <div v-else-if="!sectorsUp.length" :style="{ padding: '14px', fontSize: '11px', color: A2.textDim, textAlign: 'center' }">无上涨板块</div>
              <div v-else v-for="s in sectorsUp.slice(0, 8)" :key="s.name"
                   class="sector-row"
                   @click="goToScreener(`${s.name} 板块基本面好的股票`)"
                   :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '5px 14px', cursor: 'pointer', fontSize: '11.5px' }">
                <span :style="{ color: A2.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">{{ s.name }}</span>
                <span :style="{ color: A2.up, fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', flexShrink: 0, marginLeft: '6px' }">+{{ s.change_pct.toFixed(2) }}%</span>
              </div>
            </div>
            <div :style="{ padding: '8px 0', borderLeft: `1px solid ${A2.borderHair}` }">
              <div v-if="loadingSectors && !sectors.length" :style="{ padding: '0 12px' }">
                <Skeleton v-for="n in 5" :key="n" :height="20" :style="{ marginBottom: '6px' }" />
              </div>
              <div v-else-if="!sectorsDown.length" :style="{ padding: '14px', fontSize: '11px', color: A2.textDim, textAlign: 'center' }">无下跌板块</div>
              <div v-else v-for="s in sectorsDown.slice(0, 8)" :key="s.name"
                   class="sector-row"
                   @click="goToScreener(`${s.name} 板块基本面好的股票`)"
                   :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '5px 14px', cursor: 'pointer', fontSize: '11.5px' }">
                <span :style="{ color: A2.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">{{ s.name }}</span>
                <span :style="{ color: A2.down, fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', flexShrink: 0, marginLeft: '6px' }">{{ s.change_pct.toFixed(2) }}%</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- =============== Bottom: 板块涨跌强度（全宽） =============== -->
      <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '8px', overflow: 'hidden', boxShadow: A2.shadow }">
        <div :style="{ padding: '11px 14px', borderBottom: `1px solid ${A2.borderHair}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }">
          <div>
            <div :style="{ fontSize: '13px', fontWeight: 700 }">板块涨跌幅强度</div>
            <div :style="{ fontSize: '10.5px', color: A2.textMuted, marginTop: '1px' }">条形长度 ∝ 涨跌幅绝对值，流通市值加权</div>
          </div>
          <span :style="{ fontSize: '11px', color: A2.textMuted }">{{ sectors.length }} 个行业</span>
        </div>
        <div :style="{ padding: '10px 14px', display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', columnGap: '24px', rowGap: '5px', maxHeight: '260px', overflow: 'auto' }">
          <template v-if="!sectors.length">
            <Skeleton v-for="n in 18" :key="n" :height="14" />
          </template>
          <template v-else>
            <div v-for="s in sectors" :key="s.name"
                 :style="{ display: 'grid', gridTemplateColumns: '70px 1fr 50px', alignItems: 'center', gap: '8px', fontSize: '11px' }">
              <span :style="{ color: A2.textSub, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">{{ s.name }}</span>
              <div :style="{ position: 'relative', height: '6px', background: A2.bgDeep, borderRadius: '3px', overflow: 'hidden' }">
                <div :style="{ position: 'absolute', left: s.change_pct >= 0 ? '50%' : 'auto', right: s.change_pct >= 0 ? 'auto' : '50%', top: 0, height: '100%', width: `${Math.min(50, Math.abs(s.change_pct) * 8)}%`, background: s.change_pct >= 0 ? A2.up : A2.down }" />
                <div :style="{ position: 'absolute', left: '50%', top: 0, height: '100%', width: '1px', background: A2.borderStrong }" />
              </div>
              <span :style="{ color: s.change_pct >= 0 ? A2.up : A2.down, fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', textAlign: 'right' }">{{ s.change_pct >= 0 ? '+' : '' }}{{ s.change_pct.toFixed(2) }}%</span>
            </div>
          </template>
        </div>
      </div>
    </div>
  </Shell>
</template>

<style scoped>
.row-hover { transition: background 0.15s; }
.row-hover:hover { background: #EFEDE6; }
.row-clickable { cursor: pointer; }

.sector-row { transition: background 0.12s; border-radius: 4px; margin: 0 6px; }
.sector-row:hover { background: rgba(14, 14, 12, 0.04); }
</style>
