<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import Sparkline from '../components/charts/Sparkline.vue'
import PctChip from '../components/charts/PctChip.vue'
import StarButton from '../components/StarButton.vue'
import Skeleton from '../components/Skeleton.vue'
import EmptyState from '../components/EmptyState.vue'
import { A2 } from '../shared/theme.js'
import { screen } from '../api/screener'
import { useKlineCache } from '../composables/useKlineCache.js'

const router = useRouter()

// 默认筛选条件：低估值 + 大中盘
const defaultConditions = [
  { field: 'pe', op: 'between', value: [0, 50] },
  { field: 'market_cap', op: 'gt', value: 100 },
]

const filterGroups = [
  { cat: '基础', items: [{ l: '股票池', v: '沪深 300' }, { l: '上市', v: '> 2 年' }] },
  { cat: '估值', items: [{ l: 'PE(TTM)', v: '0 — 50' }] },
  { cat: '规模', items: [{ l: '总市值', v: '> 100 亿' }] },
  { cat: '盈利', items: [{ l: 'ROE', v: '不限' }, { l: '股息率', v: '不限' }] },
  { cat: '成长', items: [{ l: '营收 YoY', v: '不限' }, { l: '净利 YoY', v: '不限' }] },
]

const items = ref([])      // API 返回的股票列表
const total = ref(0)
const loading = ref(true)
const errorMsg = ref('')

// 真实 sparkline：composable 缓存，items 变化时只拉新出现的代码
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
    { l: '命中数量', v: total.value, sub: `已展示 ${arr.length}`, col: A2.qwenDeep, unit: '只' },
    { l: '平均 PE', v: fmt(avg('pe')), sub: '组内中位', unit: 'x' },
    { l: '平均市值', v: fmt(avg('market_cap'), 0), sub: '亿元', unit: '亿' },
    { l: '平均股息率', v: fmt(avg('dividend_yield')), sub: '组内中位', unit: '%' },
    { l: '平均 ROE', v: fmt(avg('roe')), sub: '组内中位', unit: '%' },
  ]
})

// 千问推荐度——简易合成分（PE 越低、股息率越高、ROE 越高分越高）
function bullScore(it) {
  let s = 60
  if (it.pe && it.pe > 0) s += Math.max(0, Math.min(20, 25 - it.pe * 0.5))
  if (it.dividend_yield) s += Math.min(15, it.dividend_yield * 2)
  if (it.roe) s += Math.min(15, it.roe)
  return Math.round(Math.max(0, Math.min(99, s)))
}

const headers = ['#', '代码', '名称', '行业', '现价', 'PE', 'PB', 'ROE', '股息率', '总市值', '千问', '30日走势', '操作']

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const data = await screen(defaultConditions, { sort_by: 'market_cap', limit: 50 })
    items.value = data.items
    total.value = data.total
  } catch (e) {
    errorMsg.value = e.response?.data?.detail || e.message
  } finally {
    loading.value = false
  }
}

function gotoDetail(code) {
  router.push(`/detail/${code}`)
}

onMounted(load)
</script>

<template>
  <Shell>
    <div :style="{ flex: 1, display: 'grid', gridTemplateColumns: '280px 1fr', overflow: 'hidden' }">
      <!-- Left filter panel -->
      <div :style="{ background: A2.surface, padding: '16px', fontSize: '12px', overflow: 'auto', borderRight: `1px solid ${A2.borderHair}` }">
        <div :style="{ fontSize: '13px', fontWeight: 700, marginBottom: '12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }">
          <span>因子筛选器</span>
          <span :style="{ fontSize: '11px', color: A2.qwen, cursor: 'pointer', fontWeight: 500 }" @click="load">刷新</span>
        </div>
        <div :style="{ padding: '10px', background: A2.qwenGradSoft, borderRadius: '8px', fontSize: '11px', color: A2.qwenDeep, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px', border: `1px solid ${A2.borderHair}` }">
          <Icon name="sparkle" :size="11" /> 想用自然语言筛选？
          <span :style="{ textDecoration: 'underline', cursor: 'pointer', fontWeight: 600 }" @click="router.push('/chat')">去对话筛选</span>
        </div>

        <div v-for="g in filterGroups" :key="g.cat" :style="{ marginBottom: '14px' }">
          <div :style="{ fontSize: '10px', fontWeight: 700, color: A2.textDim, letterSpacing: '1.4px', marginBottom: '6px' }">{{ g.cat.toUpperCase() }}</div>
          <div v-for="it in g.items" :key="it.l" :style="{ display: 'flex', justifyContent: 'space-between', padding: '7px 10px', fontSize: '11.5px', background: A2.bgDeep, borderRadius: '6px', marginBottom: '3px' }">
            <span :style="{ color: A2.textMuted }">{{ it.l }}</span>
            <span :style="{ fontWeight: 600, fontFamily: 'IBM Plex Mono, monospace', color: A2.text }">{{ it.v }}</span>
          </div>
        </div>

        <button :style="{ width: '100%', padding: '10px 12px', background: A2.surface, color: A2.text, border: `1px dashed ${A2.borderHair}`, fontSize: '12px', fontWeight: 600, cursor: 'pointer', borderRadius: '8px', marginTop: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '5px' }"><Icon name="plus" :size="11" /> 添加因子</button>
      </div>

      <!-- Right results area -->
      <div :style="{ background: A2.bg, padding: '16px', overflow: 'auto' }">
        <div :style="{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }">
          <div>
            <div :style="{ fontSize: '16px', fontWeight: 700, letterSpacing: '-0.2px' }">筛选结果</div>
            <div :style="{ fontSize: '11px', color: A2.textMuted, marginTop: '1px' }">
              共 <span :style="{ color: A2.qwenDeep, fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace' }">{{ total }}</span> 只
              · 沪深300 · 千问推荐排序
            </div>
          </div>
          <div style="flex:1" />
          <button @click="load" :style="{ padding: '7px 14px', fontSize: '11.5px', background: A2.qwenGrad, color: '#fff', border: 'none', cursor: 'pointer', fontWeight: 600, borderRadius: '7px', boxShadow: '0 2px 8px rgba(14,14,12,0.10)' }">
            {{ loading ? '加载中...' : '重新筛选 →' }}
          </button>
        </div>

        <div v-if="errorMsg" :style="{ marginBottom: '12px', padding: '10px 14px', background: A2.upSoft, color: A2.up, borderRadius: '8px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '10px' }">
          <Icon name="alert" :size="14" />
          <span style="flex:1">{{ errorMsg }}</span>
          <button class="btn-outline" :style="{ padding: '4px 10px', fontSize: '11px' }" @click="load">
            <Icon name="refresh" :size="11" /> 重试
          </button>
        </div>

        <!-- Stats -->
        <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '10px', marginBottom: '12px' }">
          <div v-for="s in stats" :key="s.l" :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, padding: '12px 14px', borderRadius: '8px', boxShadow: A2.shadow }">
            <div :style="{ fontSize: '10.5px', color: A2.textMuted, marginBottom: '4px', fontWeight: 500 }">{{ s.l }}</div>
            <div :style="{ fontSize: '22px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', color: s.col || A2.text, letterSpacing: '-0.5px', lineHeight: 1 }">
              {{ s.v }}<span :style="{ fontSize: '11px', color: A2.textDim, fontWeight: 500 }">{{ s.unit }}</span>
            </div>
            <div :style="{ fontSize: '10px', color: A2.textDim, marginTop: '4px' }">{{ s.sub }}</div>
          </div>
        </div>

        <!-- Table -->
        <div :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', overflow: 'hidden', boxShadow: A2.shadow }">
          <table :style="{ width: '100%', borderCollapse: 'collapse', fontSize: '11px' }">
            <thead>
              <tr :style="{ background: '#F4F1E9', color: A2.textMuted, fontSize: '10px' }">
                <th v-for="(h, i) in headers" :key="i" :style="{ padding: '9px 8px', fontWeight: 600, textAlign: i > 3 && i < headers.length - 1 ? 'right' : 'left', whiteSpace: 'nowrap', letterSpacing: '0.3px' }">{{ h }}</th>
              </tr>
            </thead>
            <tbody>
              <template v-if="loading">
                <tr v-for="n in 8" :key="'sk' + n" :style="{ borderTop: `1px solid ${A2.borderHair}` }">
                  <td v-for="(_, ci) in headers" :key="ci" :style="{ padding: '11px 8px' }">
                    <Skeleton :height="ci === 11 ? 16 : 12" :width="ci === 2 ? '70%' : (ci === 12 ? '90%' : '60%')" :style="{ marginLeft: ci > 3 && ci < 12 ? 'auto' : 0 }" />
                  </td>
                </tr>
              </template>
              <tr v-else-if="!items.length">
                <td :colspan="headers.length" :style="{ padding: 0 }">
                  <EmptyState icon="filter" title="没有命中任何股票" subtitle="试着放宽 PE / 市值 等条件" />
                </td>
              </tr>
              <tr v-for="(s, i) in items" :key="s.code" class="row-hover"
                  :style="{ borderTop: `1px solid ${A2.borderHair}`, cursor: 'pointer' }"
                  @click="gotoDetail(s.code)">
                <td :style="{ padding: '9px 8px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace', fontSize: '10px' }">{{ String(i+1).padStart(2,'0') }}</td>
                <td :style="{ padding: '9px 8px', fontFamily: 'IBM Plex Mono, monospace', color: A2.textMuted, fontSize: '10.5px' }">{{ s.code }}</td>
                <td :style="{ padding: '9px 8px', fontWeight: 600 }">
                  <div :style="{ display: 'flex', alignItems: 'center', gap: '4px' }">
                    <StarButton :stock="{ code: s.code, name: s.name, sector: s.industry, refPrice: s.close }" :size="12" />
                    {{ s.name }}
                  </div>
                </td>
                <td :style="{ padding: '9px 8px', color: A2.textSub, fontSize: '11px' }">{{ s.industry || '—' }}</td>
                <td :style="{ padding: '9px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: A2.text }">{{ s.close != null ? s.close.toFixed(2) : '—' }}</td>
                <td :style="{ padding: '9px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ s.pe != null && s.pe > 0 ? s.pe.toFixed(2) : '—' }}</td>
                <td :style="{ padding: '9px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ s.pb != null ? s.pb.toFixed(2) : '—' }}</td>
                <td :style="{ padding: '9px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: s.roe > 10 ? A2.up : A2.textSub, fontWeight: s.roe > 10 ? 600 : 500 }">{{ s.roe != null ? s.roe.toFixed(2) + '%' : '—' }}</td>
                <td :style="{ padding: '9px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: s.dividend_yield > 4 ? A2.up : A2.textSub, fontWeight: s.dividend_yield > 4 ? 600 : 500 }">{{ s.dividend_yield != null ? s.dividend_yield.toFixed(2) + '%' : '—' }}</td>
                <td :style="{ padding: '9px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ s.market_cap != null ? Math.round(s.market_cap).toLocaleString() : '—' }}<span :style="{ color: A2.textDim, fontSize: '9px' }">亿</span></td>
                <td :style="{ padding: '9px 8px', textAlign: 'right' }">
                  <div :style="{ display: 'inline-flex', alignItems: 'center', gap: '4px' }">
                    <div :style="{ width: '36px', height: '4px', background: A2.bgDeep, borderRadius: '2px', overflow: 'hidden' }">
                      <div :style="{ width: `${bullScore(s)}%`, height: '100%', background: A2.qwenGrad }" />
                    </div>
                    <span :style="{ fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: A2.qwenDeep, fontSize: '10.5px' }">{{ bullScore(s) }}</span>
                  </div>
                </td>
                <td :style="{ padding: '7px 8px' }"><Sparkline :data="resultSpark(s.code)" :width="64" :height="20" /></td>
                <td :style="{ padding: '9px 8px', textAlign: 'right' }">
                  <span :style="{ color: A2.qwen, fontSize: '11px', fontWeight: 600 }">详情 →</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </Shell>
</template>

<style scoped>
.row-hover { transition: background 0.15s; }
.row-hover:hover { background: #EFEDE6; }
</style>
