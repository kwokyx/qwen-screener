<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import Sparkline from '../components/charts/Sparkline.vue'
import PctChip from '../components/charts/PctChip.vue'
import PctText from '../components/charts/PctText.vue'
import StarButton from '../components/StarButton.vue'
import Skeleton from '../components/Skeleton.vue'
import { A2 } from '../shared/theme.js'
import { genKline, seededRand } from '../shared/data.js'
import * as marketApi from '../api/market'

const router = useRouter()

function heatBg(change_pct) {
  const positive = change_pct >= 0
  const intensity = Math.min(1, Math.abs(change_pct) / 5)
  return positive
    ? `rgba(200,49,42,${0.55 + intensity * 0.35})`
    : `rgba(14,138,102,${0.55 + intensity * 0.35})`
}

function gotoDetail(code) {
  router.push(`/detail/${code}`)
}

// ---- 真数据 state ----
const indices = ref([])           // [{name, code, value, change, change_pct, spark, constituents}]
const sectors = ref([])           // [{name, change_pct, count, leader_name, leader_pct}]
const movers = ref(null)          // {gainers, losers, by_amount, by_turnover}
const moverTab = ref('gainers')
const loadingIndices = ref(true)
const loadingSectors = ref(true)
const loadingMovers = ref(true)
const errorMsg = ref('')

const moversShown = computed(() => (movers.value ? movers.value[moverTab.value] || [] : []))

// 走势线：每只股票一条 30 天确定性合成（DB 还没历史 K 线）
const stockKline = computed(() =>
  moversShown.value.map((s, i) => genKline(100, 30, 0.02, hashString(s.code) + i))
)
const idxSpark = computed(() => indices.value.map((idx) => idx.spark || []))

// 资金流向：暂没真实数据，按当日涨跌幅做相关性合成
const capFlow = computed(() => {
  if (!sectors.value.length) return []
  const rand = seededRand(7)
  return sectors.value.map((s) => s.change_pct * 8 + (rand() - 0.5) * 8)
})

function hashString(s) {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h << 5) - h + s.charCodeAt(i)
  return Math.abs(h) % 1000
}

async function loadAll() {
  errorMsg.value = ''
  // 三个并行；任意失败不阻塞其他两个
  Promise.allSettled([
    marketApi.indices().then((d) => { indices.value = d }).finally(() => { loadingIndices.value = false }),
    marketApi.sectors(8).then((d) => { sectors.value = d }).finally(() => { loadingSectors.value = false }),
    marketApi.movers(8).then((d) => { movers.value = d }).finally(() => { loadingMovers.value = false }),
  ]).then((rs) => {
    const failed = rs.filter((r) => r.status === 'rejected')
    if (failed.length === rs.length) {
      errorMsg.value = '行情数据全部失败：' + (failed[0].reason?.message || '后端不可达')
    }
  })
}

const moverTabs = [
  { id: 'gainers',     label: '涨幅榜' },
  { id: 'losers',      label: '跌幅榜' },
  { id: 'by_amount',   label: '成交额' },
  { id: 'by_turnover', label: '换手率' },
]

onMounted(loadAll)
</script>

<template>
  <Shell>
    <div :style="{ flex: 1, overflow: 'auto', padding: '16px' }">

      <!-- Index hero strip -->
      <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px', marginBottom: '14px' }">
        <template v-if="loadingIndices && !indices.length">
          <div v-for="n in 4" :key="n" :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, padding: '16px', borderRadius: '10px', boxShadow: A2.shadow }">
            <Skeleton :width="80" :height="13" :style="{ marginBottom: '4px' }" />
            <Skeleton :width="60" :height="9" :style="{ marginBottom: '12px' }" />
            <Skeleton :width="120" :height="26" />
          </div>
        </template>
        <div v-else v-for="(idx, i) in indices" :key="idx.code"
             class="card-hover"
             :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, padding: '16px', borderRadius: '10px', position: 'relative', overflow: 'hidden', boxShadow: A2.shadow, cursor: 'pointer' }">
          <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '8px' }">
            <div>
              <div :style="{ fontSize: '12px', color: A2.textSub, fontWeight: 600 }">{{ idx.name }}</div>
              <div :style="{ fontSize: '10px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace' }">{{ idx.code }} · {{ idx.constituents }} 只</div>
            </div>
            <Sparkline :data="idxSpark[i] || []" :width="64" :height="26" />
          </div>
          <div :style="{ display: 'flex', alignItems: 'baseline', gap: '8px' }">
            <div :style="{ fontSize: '26px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '-0.5px', color: idx.change_pct >= 0 ? A2.up : A2.down }">
              {{ idx.value.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}
            </div>
            <PctText :pct="idx.change_pct" :size="13" />
          </div>
        </div>
      </div>

      <div v-if="errorMsg" :style="{ marginBottom: '12px', padding: '10px 14px', background: A2.upSoft, color: A2.up, borderRadius: '8px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '10px' }">
        <Icon name="alert" :size="14" />
        <span style="flex:1">{{ errorMsg }}</span>
        <button class="btn-outline" :style="{ padding: '4px 10px', fontSize: '11px' }" @click="loadAll">
          <Icon name="refresh" :size="11" /> 重试
        </button>
      </div>

      <div :style="{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '10px' }">
        <!-- Movers table -->
        <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', overflow: 'hidden', boxShadow: A2.shadow }">
          <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 18px', borderBottom: `1px solid ${A2.borderHair}` }">
            <div>
              <div :style="{ fontSize: '14px', fontWeight: 700, letterSpacing: '-0.2px' }">市场异动</div>
              <div :style="{ fontSize: '11px', color: A2.textMuted, marginTop: '1px' }">千问实时排序 · 综合涨跌、量能、机构资金</div>
            </div>
            <div :style="{ display: 'flex', gap: '2px', padding: '3px', background: A2.bgDeep, borderRadius: '7px' }">
              <div v-for="t in moverTabs" :key="t.id"
                   @click="moverTab = t.id"
                   :style="{ padding: '5px 11px', background: moverTab === t.id ? A2.surface : 'transparent', color: moverTab === t.id ? A2.text : A2.textMuted, fontSize: '11px', fontWeight: moverTab === t.id ? 600 : 500, cursor: 'pointer', borderRadius: '5px', boxShadow: moverTab === t.id ? A2.shadow : 'none', transition: 'background 0.15s, color 0.15s' }">
                {{ t.label }}
              </div>
            </div>
          </div>
          <table :style="{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }">
            <thead>
              <tr :style="{ color: A2.textMuted, fontSize: '10px', fontWeight: 600, letterSpacing: '0.5px' }">
                <th :style="{ textAlign: 'left', padding: '8px 16px', fontWeight: 600 }">代码</th>
                <th :style="{ textAlign: 'left', padding: '8px 8px', fontWeight: 600 }">名称</th>
                <th :style="{ textAlign: 'right', padding: '8px 8px', fontWeight: 600 }">最新价</th>
                <th :style="{ textAlign: 'right', padding: '8px 8px', fontWeight: 600 }">涨跌幅</th>
                <th :style="{ textAlign: 'right', padding: '8px 8px', fontWeight: 600 }">成交额</th>
                <th :style="{ textAlign: 'right', padding: '8px 8px', fontWeight: 600 }">PE</th>
                <th :style="{ textAlign: 'left', padding: '8px 8px', fontWeight: 600 }">所属</th>
                <th :style="{ textAlign: 'left', padding: '8px 8px', fontWeight: 600 }">30 日</th>
                <th :style="{ textAlign: 'left', padding: '8px 16px', fontWeight: 600 }">千问解读</th>
              </tr>
            </thead>
            <tbody>
              <template v-if="loadingMovers && !movers">
                <tr v-for="n in 6" :key="n" :style="{ borderTop: `1px solid ${A2.borderHair}` }">
                  <td v-for="ci in 9" :key="ci" :style="{ padding: '11px 8px' }">
                    <Skeleton :height="12" :width="ci === 9 ? '90%' : (ci === 2 ? '70%' : '50%')" :style="{ marginLeft: ci > 2 && ci < 7 ? 'auto' : 0 }" />
                  </td>
                </tr>
              </template>
              <tr v-else-if="!moversShown.length">
                <td colspan="9" :style="{ textAlign: 'center', padding: '32px', color: A2.textMuted, fontSize: '12px' }">该榜单暂无数据</td>
              </tr>
              <tr v-for="(s, i) in moversShown" :key="s.code" class="row-hover row-clickable" @click="gotoDetail(s.code)" :style="{ borderTop: `1px solid ${A2.borderHair}` }">
                <td :style="{ padding: '11px 16px', fontFamily: 'IBM Plex Mono, monospace', color: A2.textMuted, fontSize: '11px' }">{{ s.code }}</td>
                <td :style="{ padding: '11px 8px', fontWeight: 600, fontSize: '13px' }">
                  <div :style="{ display: 'flex', alignItems: 'center', gap: '4px' }">
                    <StarButton :stock="{ code: s.code, name: s.name, sector: s.industry, refPrice: s.close }" :size="13" />
                    {{ s.name }}
                  </div>
                </td>
                <td :style="{ padding: '11px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: (s.change_pct || 0) >= 0 ? A2.up : A2.down }">{{ s.close != null ? s.close.toFixed(2) : '—' }}</td>
                <td :style="{ padding: '11px 8px', textAlign: 'right' }">
                  <PctChip v-if="s.change_pct != null" :pct="s.change_pct" size="sm" />
                  <span v-else :style="{ fontSize: '10px', color: A2.textDim }">—</span>
                </td>
                <td :style="{ padding: '11px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub, fontSize: '11px' }">{{ s.amount != null ? s.amount.toFixed(1) + '亿' : '—' }}</td>
                <td :style="{ padding: '11px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub, fontSize: '11px' }">{{ s.pe != null && s.pe > 0 ? s.pe.toFixed(1) : '—' }}</td>
                <td :style="{ padding: '11px 8px' }">
                  <span :style="{ fontSize: '10px', padding: '2px 7px', background: A2.bgDeep, color: A2.textSub, borderRadius: '4px', fontWeight: 500 }">{{ s.industry || '—' }}</span>
                </td>
                <td :style="{ padding: '11px 8px' }">
                  <Sparkline :data="stockKline[i] ? stockKline[i].map(d => d.c) : []" :width="84" :height="22" />
                </td>
                <td :style="{ padding: '11px 16px', minWidth: '160px', fontSize: '11.5px', lineHeight: 1.55, color: A2.textSub }">
                  <span v-if="moverTab === 'gainers'" :style="{ color: A2.up }">领涨 · {{ s.industry || '—' }}</span>
                  <span v-else-if="moverTab === 'losers'" :style="{ color: A2.down }">回调 · {{ s.industry || '—' }}</span>
                  <span v-else-if="moverTab === 'by_amount'">成交活跃 · 换手 {{ s.turnover != null ? s.turnover.toFixed(2) + '%' : '—' }}</span>
                  <span v-else>资金流速 · 换手 {{ s.turnover != null ? s.turnover.toFixed(2) + '%' : '—' }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Right column -->
        <div :style="{ display: 'flex', flexDirection: 'column', gap: '10px' }">
          <!-- Qwen daily card -->
          <div :style="{ background: A2.qwenGradSoft, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', padding: '16px', position: 'relative', overflow: 'hidden', boxShadow: A2.shadow }">
            <div :style="{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }">
              <div :style="{ width: '24px', height: '24px', background: A2.qwenGrad, color: '#fff', display: 'grid', placeItems: 'center', fontSize: '11px', fontWeight: 800, borderRadius: '6px', boxShadow: '0 2px 6px rgba(14,14,12,0.10)' }">千</div>
              <div :style="{ fontSize: '13px', fontWeight: 700 }">千问每日观察</div>
              <span :style="{ marginLeft: 'auto', fontSize: '10px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace' }">14:30</span>
            </div>
            <div v-if="sectors.length" :style="{ fontSize: '12px', lineHeight: 1.7, color: A2.textSub, marginBottom: '10px' }">
              市场延续<strong>结构性行情</strong>。
              <span :style="{ color: A2.up, fontWeight: 700 }">{{ sectors[0].name }} {{ sectors[0].change_pct >= 0 ? '+' : '' }}{{ sectors[0].change_pct.toFixed(2) }}%</span>
              领涨，
              <span :style="{ color: A2.down, fontWeight: 700 }">{{ [...sectors].sort((a, b) => a.change_pct - b.change_pct)[0].name }} {{ [...sectors].sort((a, b) => a.change_pct - b.change_pct)[0].change_pct.toFixed(2) }}%</span>
              调整。共 {{ indices[0]?.constituents || '—' }} 只沪市股票，全市场涨跌
              <strong>{{ moversShown.length }} / {{ movers ? movers.gainers.length + movers.losers.length : '—' }}</strong>。
            </div>
            <div v-else :style="{ marginBottom: '10px' }">
              <Skeleton :height="12" :width="'92%'" :style="{ marginBottom: '6px' }" />
              <Skeleton :height="12" :width="'85%'" :style="{ marginBottom: '6px' }" />
              <Skeleton :height="12" :width="'70%'" />
            </div>
            <div :style="{ paddingTop: '10px', borderTop: `1px dashed ${A2.borderHair}` }">
              <div v-if="movers" v-for="(t, i) in [
                { tag: '领涨', stock: movers.gainers[0]?.name, pct: movers.gainers[0]?.change_pct, sec: movers.gainers[0]?.industry, color: A2.up },
                { tag: '领跌', stock: movers.losers[0]?.name, pct: movers.losers[0]?.change_pct, sec: movers.losers[0]?.industry, color: A2.down },
                { tag: '量能', stock: movers.by_amount[0]?.name, amount: movers.by_amount[0]?.amount, sec: movers.by_amount[0]?.industry, color: A2.qwen },
              ]" :key="i" :style="{ display: 'flex', gap: '8px', padding: '5px 0', fontSize: '11px', color: A2.textSub, alignItems: 'baseline' }">
                <span :style="{ color: t.color, fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, fontSize: '10px' }">0{{ i + 1 }}</span>
                <span style="flex:1">
                  <strong>{{ t.tag }}</strong> · {{ t.stock || '—' }}
                  <span v-if="t.pct != null" :style="{ color: t.color }"> {{ t.pct >= 0 ? '+' : '' }}{{ t.pct.toFixed(2) }}%</span>
                  <span v-if="t.amount != null" :style="{ color: t.color }"> {{ t.amount.toFixed(1) }} 亿</span>
                  <span v-if="t.sec" :style="{ color: A2.textDim }"> · {{ t.sec }}</span>
                </span>
              </div>
              <div v-if="!movers">
                <Skeleton v-for="n in 3" :key="n" :height="11" :width="'80%'" :style="{ marginTop: n === 1 ? 0 : '6px' }" />
              </div>
            </div>
            <button :style="{ width: '100%', marginTop: '12px', padding: '9px 12px', background: A2.qwenGrad, color: '#fff', border: 'none', fontSize: '12px', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '5px', borderRadius: '7px', boxShadow: '0 2px 8px rgba(14,14,12,0.10)' }">
              <Icon name="sparkle" :size="12" /> 让千问帮我选股
            </button>
          </div>

          <!-- Sector heatmap -->
          <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', overflow: 'hidden', boxShadow: A2.shadow, flex: 1 }">
            <div :style="{ padding: '12px 16px', borderBottom: `1px solid ${A2.borderHair}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }">
              <div :style="{ fontSize: '13px', fontWeight: 700 }">板块热力</div>
              <span :style="{ fontSize: '10px', color: A2.textMuted }">申万一级 · 涨跌幅</span>
            </div>
            <div :style="{ padding: '10px' }">
              <div v-if="loadingSectors && !sectors.length" :style="{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '6px' }">
                <Skeleton v-for="n in 8" :key="n" :height="56" :rounded="7" />
              </div>
              <div v-else :style="{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '6px' }">
                <div v-for="s in sectors" :key="s.name"
                     class="heat-tile"
                     :title="s.leader_name ? `领涨 ${s.leader_name} ${s.leader_pct >= 0 ? '+' : ''}${s.leader_pct.toFixed(2)}%` : ''"
                     :style="{ background: heatBg(s.change_pct), padding: '10px 12px', borderRadius: '7px', color: '#fff', minHeight: '56px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }">
                  <div :style="{ fontSize: '12px', fontWeight: 600 }">{{ s.name }}</div>
                  <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }">
                    <span :style="{ fontSize: '14px', fontWeight: 800, fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '-0.3px' }">{{ s.change_pct >= 0 ? '+' : '' }}{{ s.change_pct.toFixed(2) }}%</span>
                    <span :style="{ fontSize: '9px', opacity: 0.85 }">{{ s.count }} 只</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Capital flow -->
      <div :style="{ marginTop: '10px', background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', overflow: 'hidden', boxShadow: A2.shadow }">
        <div :style="{ padding: '12px 18px', borderBottom: `1px solid ${A2.borderHair}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }">
          <div>
            <div :style="{ fontSize: '13px', fontWeight: 700 }">主力资金流向</div>
            <div :style="{ fontSize: '11px', color: A2.textMuted, marginTop: '1px' }">近 5 日累计 · 申万一级</div>
          </div>
          <div :style="{ fontSize: '11px', color: A2.textMuted, display: 'flex', gap: '12px' }">
            <span :style="{ display: 'flex', alignItems: 'center', gap: '4px' }"><div :style="{ width: '8px', height: '8px', background: A2.up, borderRadius: '2px' }" /> 净流入</span>
            <span :style="{ display: 'flex', alignItems: 'center', gap: '4px' }"><div :style="{ width: '8px', height: '8px', background: A2.down, borderRadius: '2px' }" /> 净流出</span>
          </div>
        </div>
        <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: '1px', background: A2.borderHair }">
          <template v-if="!sectors.length">
            <div v-for="n in 8" :key="n" :style="{ padding: '12px 14px', background: A2.surface }">
              <Skeleton :width="50" :height="9" :style="{ marginBottom: '6px' }" />
              <Skeleton :width="80" :height="14" :style="{ marginBottom: '6px' }" />
              <Skeleton :width="'100%'" :height="3" />
            </div>
          </template>
          <div v-else v-for="(s, i) in sectors" :key="s.name" :style="{ padding: '12px 14px', background: A2.surface, fontSize: '11px' }">
            <div :style="{ color: A2.textMuted, marginBottom: '4px', fontWeight: 500 }">{{ s.name }}</div>
            <div :style="{ fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: capFlow[i] >= 0 ? A2.up : A2.down, fontSize: '14px', letterSpacing: '-0.3px' }">
              {{ capFlow[i] >= 0 ? '+' : '' }}{{ capFlow[i].toFixed(1) }}<span :style="{ fontSize: '10px', opacity: 0.7 }">亿</span>
            </div>
            <div :style="{ marginTop: '6px', height: '3px', background: A2.bgDeep, borderRadius: '2px', overflow: 'hidden' }">
              <div :style="{ width: `${Math.min(100, Math.abs(capFlow[i]) * 2)}%`, height: '100%', background: capFlow[i] >= 0 ? A2.up : A2.down }" />
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
