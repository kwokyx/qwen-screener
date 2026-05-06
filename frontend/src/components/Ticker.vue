<script setup>
import { onMounted, ref } from 'vue'
import { A2 } from '../shared/theme.js'
import { INDICES as MOCK_INDICES } from '../shared/data.js'
import { ticker as fetchTicker } from '../api/market'

// 模块级缓存：跨路由切换不重复拉
let cache = null
let pending = null

const indices = ref(MOCK_INDICES.map((i) => ({ name: i.name, code: i.code, value: i.value, change: i.change, change_pct: i.changePct })))
const totalAmount = ref(8247)
const advancers = ref(null)
const decliners = ref(null)
const tradeDate = ref('2026-05-01 14:32')

async function load() {
  if (cache) {
    indices.value = cache.indices
    totalAmount.value = cache.totalAmount
    advancers.value = cache.advancers
    decliners.value = cache.decliners
    tradeDate.value = cache.tradeDate
    return
  }
  if (!pending) pending = fetchTicker().catch(() => null)
  const r = await pending
  if (!r) return
  cache = {
    indices: r.indices.map((i) => ({ name: i.name, code: i.code, value: i.value, change: i.change, change_pct: i.change_pct })),
    totalAmount: r.total_amount_yi,
    advancers: r.advancers,
    decliners: r.decliners,
    tradeDate: r.trade_date,
  }
  indices.value = cache.indices
  totalAmount.value = cache.totalAmount
  advancers.value = cache.advancers
  decliners.value = cache.decliners
  tradeDate.value = cache.tradeDate
}

onMounted(load)
</script>

<template>
  <div :style="{ background: '#EFEDE6', color: A2.textSub, height: '24px', display: 'flex', alignItems: 'center', fontSize: '10.5px', fontFamily: 'IBM Plex Mono, monospace', padding: '0 16px', gap: '22px', overflow: 'hidden', boxShadow: '0 1px 0 ' + A2.borderHair, flexShrink: 0 }">
    <div v-for="idx in indices" :key="idx.code" :style="{ display: 'flex', alignItems: 'center', gap: '5px' }">
      <span :style="{ color: A2.textMuted, fontSize: '10px' }">{{ idx.name }}</span>
      <span :style="{ color: A2.text, fontWeight: 600 }">{{ idx.value.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</span>
      <span :style="{ color: idx.change >= 0 ? A2.up : A2.down, fontWeight: 600 }">
        {{ idx.change >= 0 ? '▲' : '▼' }} {{ (idx.change >= 0 ? '+' : '') + idx.change_pct.toFixed(2) }}%
      </span>
    </div>
    <div :style="{ marginLeft: 'auto', display: 'flex', gap: '14px', color: A2.textMuted }">
      <span v-if="advancers != null">涨/跌 <span :style="{ color: A2.up, fontWeight: 600 }">{{ advancers }}</span> / <span :style="{ color: A2.down, fontWeight: 600 }">{{ decliners }}</span></span>
      <span>成交 <span :style="{ color: A2.text, fontWeight: 600 }">{{ totalAmount.toLocaleString('zh-CN') }}亿</span></span>
      <span :style="{ display: 'flex', alignItems: 'center', gap: '4px' }">
        <span :style="{ width: '5px', height: '5px', background: A2.down, borderRadius: '50%' }" />
        {{ tradeDate }}
      </span>
    </div>
  </div>
</template>
