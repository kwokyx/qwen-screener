<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import Sparkline from '../components/charts/Sparkline.vue'
import StarButton from '../components/StarButton.vue'
import Skeleton from '../components/Skeleton.vue'
import EmptyState from '../components/EmptyState.vue'
import { A2 } from '../shared/theme.js'
import { screen } from '../api/screener'
import { useKlineCache } from '../composables/useKlineCache.js'

const router = useRouter()

const POOL_OPTIONS = [
  { value: 'all', label: '全 A 股' },
  { value: 'csi300', label: '沪深 300' },
  { value: 'csi500', label: '中证 500' },
  { value: 'sse50', label: '上证 50' },
]

const EXTRA_FIELD_OPTIONS = [
  { field: 'pb', label: 'PB' },
  { field: 'turnover', label: '换手率(%)' },
  { field: 'close', label: '现价(元)' },
  { field: 'gross_margin', label: '毛利率(%)' },
  { field: 'debt_ratio', label: '负债率(%)' },
  { field: 'revenue_yoy', label: '营收 YoY(%)' },
  { field: 'profit_yoy', label: '净利 YoY(%)' },
]

const OP_OPTIONS = [
  { value: 'gt', label: '>' },
  { value: 'gte', label: '≥' },
  { value: 'lt', label: '<' },
  { value: 'lte', label: '≤' },
  { value: 'between', label: '区间' },
]

/** 左侧可编辑筛选表单 */
const form = ref({
  pool: 'csi300',
  listYearsMin: '2',
  peEnabled: true,
  peMin: '0',
  peMax: '50',
  marketCapEnabled: true,
  marketCapMin: '100',
  roeEnabled: false,
  roeMin: '10',
  dividendEnabled: false,
  dividendMin: '3',
  revenueYoyEnabled: false,
  revenueYoyMin: '10',
  profitYoyEnabled: false,
  profitYoyMin: '10',
})

const extraRules = ref([])
let extraId = 0

const items = ref([])
const total = ref(0)
const loading = ref(true)
const errorMsg = ref('')

const { load: loadResultKlines, get: resultSpark } = useKlineCache(30)
watch(items, () => loadResultKlines(items.value.map((s) => s.code)))

const inputStyle = {
  width: '100%',
  padding: '5px 8px',
  fontSize: '11px',
  fontFamily: 'IBM Plex Mono, monospace',
  border: `1px solid ${A2.borderHair}`,
  borderRadius: '5px',
  background: A2.surface,
  color: A2.text,
  boxSizing: 'border-box',
}

const selectStyle = { ...inputStyle, cursor: 'pointer' }

function parseNum(s) {
  if (s === '' || s == null) return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

function buildConditions() {
  const conds = []
  const f = form.value

  if (f.peEnabled) {
    const lo = parseNum(f.peMin)
    const hi = parseNum(f.peMax)
    if (lo != null && hi != null) conds.push({ field: 'pe', op: 'between', value: [lo, hi] })
    else if (lo != null) conds.push({ field: 'pe', op: 'gte', value: lo })
    else if (hi != null) conds.push({ field: 'pe', op: 'lte', value: hi })
  }

  if (f.marketCapEnabled) {
    const mc = parseNum(f.marketCapMin)
    if (mc != null) conds.push({ field: 'market_cap', op: 'gt', value: mc })
  }

  if (f.roeEnabled) {
    const roe = parseNum(f.roeMin)
    if (roe != null) conds.push({ field: 'roe', op: 'gte', value: roe })
  }

  if (f.dividendEnabled) {
    const dy = parseNum(f.dividendMin)
    if (dy != null) conds.push({ field: 'dividend_yield', op: 'gte', value: dy })
  }

  if (f.revenueYoyEnabled) {
    const v = parseNum(f.revenueYoyMin)
    if (v != null) conds.push({ field: 'revenue_yoy', op: 'gte', value: v })
  }

  if (f.profitYoyEnabled) {
    const v = parseNum(f.profitYoyMin)
    if (v != null) conds.push({ field: 'profit_yoy', op: 'gte', value: v })
  }

  for (const r of extraRules.value) {
    const v1 = parseNum(r.value)
    const v2 = parseNum(r.value2)
    if (r.op === 'between') {
      if (v1 != null && v2 != null) conds.push({ field: r.field, op: 'between', value: [v1, v2] })
    } else if (v1 != null) {
      conds.push({ field: r.field, op: r.op, value: v1 })
    }
  }

  return conds
}

const poolLabel = computed(() => POOL_OPTIONS.find((p) => p.value === form.value.pool)?.label || '全市场')

const filterSummary = computed(() => {
  const parts = [poolLabel.value]
  const f = form.value
  if (f.peEnabled) parts.push(`PE ${f.peMin || '—'}~${f.peMax || '—'}`)
  if (f.marketCapEnabled && f.marketCapMin) parts.push(`市值>${f.marketCapMin}亿`)
  return parts.join(' · ')
})

const stats = computed(() => {
  const arr = items.value
  if (!arr.length) return []
  const avg = (k) => {
    const xs = arr.map((x) => x[k]).filter((v) => v != null)
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null
  }
  const fmt = (v, d = 1) => (v == null ? '—' : v.toFixed(d))
  return [
    { l: '命中数量', v: total.value, sub: `已展示 ${arr.length}`, col: A2.qwenDeep, unit: '只' },
    { l: '平均 PE', v: fmt(avg('pe')), sub: '组内中位', unit: 'x' },
    { l: '平均市值', v: fmt(avg('market_cap'), 0), sub: '亿元', unit: '亿' },
    { l: '平均股息率', v: fmt(avg('dividend_yield')), sub: '组内中位', unit: '%' },
    { l: '平均 ROE', v: fmt(avg('roe')), sub: '组内中位', unit: '%' },
  ]
})

/** 与详情页综合分一致：来自后端 score_engine（见 /qwen/score） */
function displayScore(it) {
  return it.score_total != null ? it.score_total : '—'
}

const headers = ['#', '代码', '名称', '行业', '现价', 'PE', 'PB', 'ROE', '股息率', '总市值', '综合分', '30日走势', '操作']

async function load() {
  loading.value = true
  errorMsg.value = ''
  const conditions = buildConditions()
  const listYears = parseNum(form.value.listYearsMin)
  try {
    const data = await screen(conditions, {
      sort_by: 'market_cap',
      limit: 50,
      pool: form.value.pool === 'all' ? null : form.value.pool,
      listYearsMin: listYears,
    })
    items.value = data.items
    total.value = data.total
  } catch (e) {
    errorMsg.value = e.response?.data?.detail || e.message
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function addExtraFactor() {
  extraRules.value.push({
    id: ++extraId,
    field: 'pb',
    op: 'lt',
    value: '',
    value2: '',
  })
}

function removeExtra(id) {
  extraRules.value = extraRules.value.filter((r) => r.id !== id)
}

function gotoDetail(code) {
  router.push(`/detail/${code}`)
}

function resetForm() {
  form.value = {
    pool: 'csi300',
    listYearsMin: '2',
    peEnabled: true,
    peMin: '0',
    peMax: '50',
    marketCapEnabled: true,
    marketCapMin: '100',
    roeEnabled: false,
    roeMin: '10',
    dividendEnabled: false,
    dividendMin: '3',
    revenueYoyEnabled: false,
    revenueYoyMin: '10',
    profitYoyEnabled: false,
    profitYoyMin: '10',
  }
  extraRules.value = []
  load()
}

onMounted(load)
</script>

<template>
  <Shell>
    <div :style="{ flex: 1, display: 'grid', gridTemplateColumns: '300px 1fr', overflow: 'hidden' }">
      <!-- Left filter panel -->
      <div :style="{ background: A2.surface, padding: '16px', fontSize: '12px', overflow: 'auto', borderRight: `1px solid ${A2.borderHair}` }">
        <div :style="{ fontSize: '13px', fontWeight: 700, marginBottom: '12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }">
          <span>因子筛选器</span>
          <span :style="{ fontSize: '11px', color: A2.textMuted, cursor: 'pointer' }" @click="resetForm">重置</span>
        </div>
        <div :style="{ padding: '10px', background: A2.qwenGradSoft, borderRadius: '8px', fontSize: '11px', color: A2.qwenDeep, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px', border: `1px solid ${A2.borderHair}` }">
          <Icon name="sparkle" :size="11" /> 想用自然语言筛选？
          <span :style="{ textDecoration: 'underline', cursor: 'pointer', fontWeight: 600 }" @click="router.push('/chat')">去对话筛选</span>
        </div>

        <!-- 基础 -->
        <div :style="{ marginBottom: '14px' }">
          <div :style="{ fontSize: '10px', fontWeight: 700, color: A2.textDim, letterSpacing: '1.4px', marginBottom: '6px' }">基础</div>
          <label :style="{ display: 'block', fontSize: '10.5px', color: A2.textMuted, marginBottom: '4px' }">股票池</label>
          <select v-model="form.pool" :style="selectStyle">
            <option v-for="p in POOL_OPTIONS" :key="p.value" :value="p.value">{{ p.label }}</option>
          </select>
          <label :style="{ display: 'block', fontSize: '10.5px', color: A2.textMuted, margin: '8px 0 4px' }">上市满（年，留空不限）</label>
          <input v-model="form.listYearsMin" type="number" min="0" step="0.5" placeholder="不限" :style="inputStyle" />
        </div>

        <!-- 估值 -->
        <div :style="{ marginBottom: '14px' }">
          <div :style="{ fontSize: '10px', fontWeight: 700, color: A2.textDim, letterSpacing: '1.4px', marginBottom: '6px' }">估值</div>
          <label :style="{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px', cursor: 'pointer' }">
            <input v-model="form.peEnabled" type="checkbox" />
            <span :style="{ fontSize: '11px', color: A2.textMuted }">PE(TTM) 区间</span>
          </label>
          <div v-if="form.peEnabled" :style="{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: '6px', alignItems: 'center' }">
            <input v-model="form.peMin" type="number" placeholder="最小" :style="inputStyle" />
            <span :style="{ color: A2.textDim, fontSize: '10px' }">—</span>
            <input v-model="form.peMax" type="number" placeholder="最大" :style="inputStyle" />
          </div>
        </div>

        <!-- 规模 -->
        <div :style="{ marginBottom: '14px' }">
          <div :style="{ fontSize: '10px', fontWeight: 700, color: A2.textDim, letterSpacing: '1.4px', marginBottom: '6px' }">规模</div>
          <label :style="{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px', cursor: 'pointer' }">
            <input v-model="form.marketCapEnabled" type="checkbox" />
            <span :style="{ fontSize: '11px', color: A2.textMuted }">总市值 &gt;（亿元）</span>
          </label>
          <input v-if="form.marketCapEnabled" v-model="form.marketCapMin" type="number" min="0" :style="inputStyle" />
        </div>

        <!-- 盈利 -->
        <div :style="{ marginBottom: '14px' }">
          <div :style="{ fontSize: '10px', fontWeight: 700, color: A2.textDim, letterSpacing: '1.4px', marginBottom: '6px' }">盈利</div>
          <label :style="{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px', cursor: 'pointer' }">
            <input v-model="form.roeEnabled" type="checkbox" />
            <span :style="{ fontSize: '11px', color: A2.textMuted }">ROE ≥（%）</span>
          </label>
          <input v-if="form.roeEnabled" v-model="form.roeMin" type="number" :style="{ ...inputStyle, marginBottom: '8px' }" />
          <label :style="{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px', cursor: 'pointer' }">
            <input v-model="form.dividendEnabled" type="checkbox" />
            <span :style="{ fontSize: '11px', color: A2.textMuted }">股息率 ≥（%）</span>
          </label>
          <input v-if="form.dividendEnabled" v-model="form.dividendMin" type="number" min="0" :style="inputStyle" />
        </div>

        <!-- 成长 -->
        <div :style="{ marginBottom: '14px' }">
          <div :style="{ fontSize: '10px', fontWeight: 700, color: A2.textDim, letterSpacing: '1.4px', marginBottom: '6px' }">成长</div>
          <label :style="{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px', cursor: 'pointer' }">
            <input v-model="form.revenueYoyEnabled" type="checkbox" />
            <span :style="{ fontSize: '11px', color: A2.textMuted }">营收 YoY ≥（%）</span>
          </label>
          <input v-if="form.revenueYoyEnabled" v-model="form.revenueYoyMin" type="number" :style="{ ...inputStyle, marginBottom: '8px' }" />
          <label :style="{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px', cursor: 'pointer' }">
            <input v-model="form.profitYoyEnabled" type="checkbox" />
            <span :style="{ fontSize: '11px', color: A2.textMuted }">净利 YoY ≥（%）</span>
          </label>
          <input v-if="form.profitYoyEnabled" v-model="form.profitYoyMin" type="number" :style="inputStyle" />
        </div>

        <!-- 额外因子 -->
        <div v-if="extraRules.length" :style="{ marginBottom: '10px' }">
          <div :style="{ fontSize: '10px', fontWeight: 700, color: A2.textDim, letterSpacing: '1.4px', marginBottom: '6px' }">更多</div>
          <div v-for="r in extraRules" :key="r.id" :style="{ padding: '8px', background: A2.bgDeep, borderRadius: '6px', marginBottom: '6px' }">
            <div :style="{ display: 'flex', gap: '4px', marginBottom: '4px' }">
              <select v-model="r.field" :style="{ ...selectStyle, flex: 1 }">
                <option v-for="o in EXTRA_FIELD_OPTIONS" :key="o.field" :value="o.field">{{ o.label }}</option>
              </select>
              <select v-model="r.op" :style="{ ...selectStyle, width: '52px' }">
                <option v-for="o in OP_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
              <button type="button" :style="{ border: 'none', background: 'transparent', cursor: 'pointer', color: A2.up, padding: '0 4px' }" @click="removeExtra(r.id)">×</button>
            </div>
            <div :style="{ display: 'grid', gridTemplateColumns: r.op === 'between' ? '1fr 1fr' : '1fr', gap: '4px' }">
              <input v-model="r.value" type="number" placeholder="值" :style="inputStyle" />
              <input v-if="r.op === 'between'" v-model="r.value2" type="number" placeholder="上限" :style="inputStyle" />
            </div>
          </div>
        </div>

        <button type="button"
                :style="{ width: '100%', padding: '10px 12px', background: A2.surface, color: A2.text, border: `1px dashed ${A2.borderHair}`, fontSize: '12px', fontWeight: 600, cursor: 'pointer', borderRadius: '8px', marginBottom: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '5px' }"
                @click="addExtraFactor">
          <Icon name="plus" :size="11" /> 添加因子
        </button>

        <button type="button"
                :disabled="loading"
                @click="load"
                :style="{ width: '100%', padding: '10px 12px', background: A2.qwenGrad, color: '#fff', border: 'none', fontSize: '12px', fontWeight: 600, cursor: loading ? 'wait' : 'pointer', borderRadius: '8px', opacity: loading ? 0.7 : 1 }">
          {{ loading ? '筛选中…' : '应用筛选' }}
        </button>
      </div>

      <!-- Right results area -->
      <div :style="{ background: A2.bg, padding: '16px', overflow: 'auto' }">
        <div :style="{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }">
          <div>
            <div :style="{ fontSize: '16px', fontWeight: 700, letterSpacing: '-0.2px' }">筛选结果</div>
            <div :style="{ fontSize: '11px', color: A2.textMuted, marginTop: '1px' }">
              共 <span :style="{ color: A2.qwenDeep, fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace' }">{{ total }}</span> 只
              · {{ filterSummary }}
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

        <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '10px', marginBottom: '12px' }">
          <div v-for="s in stats" :key="s.l" :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, padding: '12px 14px', borderRadius: '8px', boxShadow: A2.shadow }">
            <div :style="{ fontSize: '10.5px', color: A2.textMuted, marginBottom: '4px', fontWeight: 500 }">{{ s.l }}</div>
            <div :style="{ fontSize: '22px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', color: s.col || A2.text, letterSpacing: '-0.5px', lineHeight: 1 }">
              {{ s.v }}<span :style="{ fontSize: '11px', color: A2.textDim, fontWeight: 500 }">{{ s.unit }}</span>
            </div>
            <div :style="{ fontSize: '10px', color: A2.textDim, marginTop: '4px' }">{{ s.sub }}</div>
          </div>
        </div>

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
                  <EmptyState icon="filter" title="没有命中任何股票" subtitle="试着放宽 PE / 市值 等条件，或换更大的股票池" />
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
                <td :style="{ padding: '9px 8px', textAlign: 'right' }"
                    title="综合分 = 后端规则引擎 score_engine，与详情页「综合评分」一致（非千问打分）">
                  <div :style="{ display: 'inline-flex', alignItems: 'center', gap: '4px' }">
                    <div :style="{ width: '36px', height: '4px', background: A2.bgDeep, borderRadius: '2px', overflow: 'hidden' }">
                      <div :style="{ width: `${displayScore(s) === '—' ? 0 : displayScore(s)}%`, height: '100%', background: A2.textSub }" />
                    </div>
                    <span :style="{ fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: A2.text, fontSize: '10.5px' }">{{ displayScore(s) }}</span>
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
