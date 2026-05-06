<script setup>
import { computed, onMounted, ref } from 'vue'
import { A2 } from '../shared/theme.js'
import { INDICES as MOCK_INDICES } from '../shared/data.js'
import { ticker as fetchTicker, movers as fetchMovers } from '../api/market'

// 模块级缓存：跨路由切换不重复拉
let cache = null
let pending = null

const indices = ref(MOCK_INDICES.map((i) => ({ name: i.name, code: i.code, value: i.value, change: i.change, change_pct: i.changePct })))
const totalAmount = ref(8247)
const advancers = ref(null)
const decliners = ref(null)
const tradeDate = ref('—')
const moversList = ref([])    // 滚动条用：领涨 / 领跌 各 6 只

const scrollItems = computed(() => {
  // 把 movers 拼成跑马条用的列表
  if (!moversList.value.length) return []
  return moversList.value.concat(moversList.value)  // 复制一遍实现无缝循环
})

async function load() {
  if (cache) {
    Object.assign({}, cache)
    indices.value = cache.indices
    totalAmount.value = cache.totalAmount
    advancers.value = cache.advancers
    decliners.value = cache.decliners
    tradeDate.value = cache.tradeDate
    moversList.value = cache.moversList
    return
  }
  if (!pending) {
    pending = Promise.allSettled([fetchTicker(), fetchMovers(6)])
  }
  const [tickRes, moversRes] = await pending
  const r = tickRes.status === 'fulfilled' ? tickRes.value : null
  const m = moversRes.status === 'fulfilled' ? moversRes.value : null

  cache = {
    indices: r ? r.indices.map((i) => ({ name: i.name, code: i.code, value: i.value, change: i.change, change_pct: i.change_pct })) : indices.value,
    totalAmount: r?.total_amount_yi ?? totalAmount.value,
    advancers: r?.advancers ?? null,
    decliners: r?.decliners ?? null,
    tradeDate: r?.trade_date ?? '—',
    moversList: m ? [...(m.gainers || []).slice(0, 6), ...(m.losers || []).slice(0, 6)] : [],
  }
  indices.value = cache.indices
  totalAmount.value = cache.totalAmount
  advancers.value = cache.advancers
  decliners.value = cache.decliners
  tradeDate.value = cache.tradeDate
  moversList.value = cache.moversList
}

onMounted(load)
</script>

<template>
  <div :style="{ background: '#EFEDE6', color: A2.textSub, height: '24px', display: 'flex', alignItems: 'center', fontSize: '10.5px', fontFamily: 'IBM Plex Mono, monospace', boxShadow: '0 1px 0 ' + A2.borderHair, flexShrink: 0, overflow: 'hidden' }">
    <!-- 左侧：4 大指数固定 -->
    <div :style="{ display: 'flex', alignItems: 'center', gap: '20px', padding: '0 14px', flexShrink: 0, borderRight: `1px solid ${A2.borderHair}`, height: '100%' }">
      <div v-for="idx in indices" :key="idx.code" :style="{ display: 'flex', alignItems: 'center', gap: '5px' }">
        <span :style="{ color: A2.textMuted, fontSize: '10px' }">{{ idx.name }}</span>
        <span :style="{ color: A2.text, fontWeight: 600 }">{{ idx.value.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</span>
        <span :style="{ color: idx.change >= 0 ? A2.up : A2.down, fontWeight: 600 }">
          {{ idx.change >= 0 ? '▲' : '▼' }} {{ (idx.change >= 0 ? '+' : '') + idx.change_pct.toFixed(2) }}%
        </span>
      </div>
    </div>

    <!-- 中间：跑马条（涨跌前 6） -->
    <div v-if="scrollItems.length" class="ticker-scroll-wrap" :style="{ flex: 1, overflow: 'hidden', position: 'relative' }">
      <div class="ticker-scroll">
        <span v-for="(s, i) in scrollItems" :key="`${s.code}-${i}`"
              :style="{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '0 14px', borderRight: `1px solid ${A2.borderHair}` }">
          <span :style="{ color: A2.textMuted, fontSize: '10px' }">{{ s.name }}</span>
          <span :style="{ color: A2.text, fontWeight: 600 }">{{ s.close != null ? s.close.toFixed(2) : '—' }}</span>
          <span :style="{ color: (s.change_pct || 0) >= 0 ? A2.up : A2.down, fontWeight: 600 }">
            {{ (s.change_pct || 0) >= 0 ? '+' : '' }}{{ (s.change_pct || 0).toFixed(2) }}%
          </span>
        </span>
      </div>
    </div>
    <div v-else style="flex:1" />

    <!-- 右侧：聚合数字 + 时间 -->
    <div :style="{ display: 'flex', alignItems: 'center', gap: '14px', padding: '0 14px', flexShrink: 0, color: A2.textMuted, borderLeft: `1px solid ${A2.borderHair}`, height: '100%' }">
      <span v-if="advancers != null">涨/跌 <span :style="{ color: A2.up, fontWeight: 600 }">{{ advancers }}</span> / <span :style="{ color: A2.down, fontWeight: 600 }">{{ decliners }}</span></span>
      <span>成交 <span :style="{ color: A2.text, fontWeight: 600 }">{{ totalAmount.toLocaleString('zh-CN') }}亿</span></span>
      <span :style="{ display: 'flex', alignItems: 'center', gap: '4px' }">
        <span class="dot-pulse" />
        {{ tradeDate }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.ticker-scroll-wrap::before,
.ticker-scroll-wrap::after {
  content: '';
  position: absolute;
  top: 0; bottom: 0;
  width: 32px;
  z-index: 2;
  pointer-events: none;
}
.ticker-scroll-wrap::before { left: 0; background: linear-gradient(to right, #EFEDE6, transparent); }
.ticker-scroll-wrap::after  { right: 0; background: linear-gradient(to left, #EFEDE6, transparent); }
.ticker-scroll {
  white-space: nowrap;
  height: 100%;
  display: inline-flex;
  align-items: center;
  animation: ticker-roll 60s linear infinite;
}
.ticker-scroll-wrap:hover .ticker-scroll { animation-play-state: paused; }
@keyframes ticker-roll {
  from { transform: translateX(0); }
  to   { transform: translateX(-50%); }
}
.dot-pulse {
  width: 6px; height: 6px;
  background: #C8312A;
  border-radius: 50%;
  display: inline-block;
  animation: dot-pulse 1.6s ease-in-out infinite;
}
@keyframes dot-pulse {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.2); }
}
</style>
