<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import Sparkline from '../components/charts/Sparkline.vue'
import PctChip from '../components/charts/PctChip.vue'
import PctText from '../components/charts/PctText.vue'
import StarButton from '../components/StarButton.vue'
import { A2 } from '../shared/theme.js'
import { STOCKS, SECTORS, INDICES, genKline, seededRand } from '../shared/data.js'

const router = useRouter()

// Boosted minimum intensity (0.55) so the white text stays legible on the lightest tiles.
function heatBg(s) {
  const positive = s.change >= 0
  const intensity = Math.min(1, Math.abs(s.change) / 5)
  return positive
    ? `rgba(200,49,42,${0.55 + intensity * 0.35})`
    : `rgba(14,138,102,${0.55 + intensity * 0.35})`
}

function gotoDetail(code) {
  router.push(`/detail/${code}`)
}

const idxData = computed(() =>
  INDICES.map((_, i) => Array.from({ length: 30 }, (_, j) => 100 + Math.sin(j / 3 + i) * 5 + (((i * 7 + j) * 9301 + 49297) % 233280) / 233280 * 3))
)
const stockKline = computed(() => STOCKS.slice(0, 8).map((_, i) => genKline(100, 30, 0.02, i + 1)))

// deterministic capital flow per sector
const capFlow = computed(() => {
  const rand = seededRand(7)
  return SECTORS.map(() => (rand() - 0.3) * 50)
})
</script>

<template>
  <Shell>
    <div :style="{ flex: 1, overflow: 'auto', padding: '16px' }">

      <!-- Index hero strip -->
      <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px', marginBottom: '14px' }">
        <div v-for="(idx, i) in INDICES" :key="idx.code"
             class="card-hover"
             :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, padding: '16px', borderRadius: '10px', position: 'relative', overflow: 'hidden', boxShadow: A2.shadow, cursor: 'pointer' }">
          <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '8px' }">
            <div>
              <div :style="{ fontSize: '12px', color: A2.textSub, fontWeight: 600 }">{{ idx.name }}</div>
              <div :style="{ fontSize: '10px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace' }">{{ idx.code }}</div>
            </div>
            <Sparkline :data="idxData[i]" :width="64" :height="26" />
          </div>
          <div :style="{ display: 'flex', alignItems: 'baseline', gap: '8px' }">
            <div :style="{ fontSize: '26px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '-0.5px', color: idx.change >= 0 ? A2.up : A2.down }">
              {{ idx.value.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}
            </div>
            <PctText :pct="idx.changePct" :size="13" />
          </div>
        </div>
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
              <div v-for="(t, i) in ['涨幅榜', '跌幅榜', '主力净流入', '换手']" :key="t"
                   :style="{ padding: '5px 11px', background: i === 0 ? A2.surface : 'transparent', color: i === 0 ? A2.text : A2.textMuted, fontSize: '11px', fontWeight: i === 0 ? 600 : 500, cursor: 'pointer', borderRadius: '5px', boxShadow: i === 0 ? A2.shadow : 'none' }">
                {{ t }}
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
              <tr v-for="(s, i) in STOCKS.slice(0, 8)" :key="s.code" class="row-hover row-clickable" @click="gotoDetail(s.code)" :style="{ borderTop: `1px solid ${A2.borderHair}` }">
                <td :style="{ padding: '11px 16px', fontFamily: 'IBM Plex Mono, monospace', color: A2.textMuted, fontSize: '11px' }">{{ s.code }}</td>
                <td :style="{ padding: '11px 8px', fontWeight: 600, fontSize: '13px' }">
                  <div :style="{ display: 'flex', alignItems: 'center', gap: '4px' }">
                    <StarButton :stock="{ code: s.code, name: s.name, sector: s.sector, refPrice: s.price }" :size="13" />
                    {{ s.name }}
                  </div>
                </td>
                <td :style="{ padding: '11px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: s.change >= 0 ? A2.up : A2.down }">{{ s.price.toFixed(2) }}</td>
                <td :style="{ padding: '11px 8px', textAlign: 'right' }"><PctChip :pct="s.changePct" size="sm" /></td>
                <td :style="{ padding: '11px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub, fontSize: '11px' }">{{ s.vol.toFixed(1) }}亿</td>
                <td :style="{ padding: '11px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub, fontSize: '11px' }">{{ s.pe > 0 ? s.pe.toFixed(1) : '—' }}</td>
                <td :style="{ padding: '11px 8px' }">
                  <span :style="{ fontSize: '10px', padding: '2px 7px', background: A2.bgDeep, color: A2.textSub, borderRadius: '4px', fontWeight: 500 }">{{ s.sector }}</span>
                </td>
                <td :style="{ padding: '11px 8px' }">
                  <Sparkline :data="stockKline[i].map(d => d.c)" :width="84" :height="22" />
                </td>
                <td :style="{ padding: '11px 16px', minWidth: '280px', fontSize: '11.5px', lineHeight: 1.55, color: A2.textSub }">
                  <div :style="{ display: 'flex', alignItems: 'flex-start', gap: '6px' }">
                    <div :style="{ width: '12px', height: '12px', background: A2.qwenGrad, borderRadius: '3px', display: 'grid', placeItems: 'center', flexShrink: 0, marginTop: '2px' }">
                      <span :style="{ fontSize: '7px', color: '#fff', fontWeight: 800 }">千</span>
                    </div>
                    <span>{{ s.ai }}</span>
                  </div>
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
            <div :style="{ fontSize: '12px', lineHeight: 1.7, color: A2.textSub, marginBottom: '10px' }">
              市场延续<strong>结构性行情</strong>。<span :style="{ color: A2.up, fontWeight: 700 }">科技 +3.4%</span> 领涨，<span :style="{ color: A2.down, fontWeight: 700 }">地产 -1.4%</span> 调整。AI 算力链与电池储能是今日两条主线。
            </div>
            <div :style="{ paddingTop: '10px', borderTop: `1px dashed ${A2.borderHair}` }">
              <div v-for="t in [
                { i: '01', t: 'AI 算力链 — 寒武纪 +5.55% 带动板块走强' },
                { i: '02', t: '机构调研密集 — 迈瑞医疗本周 12 家' },
                { i: '03', t: '北向资金回流 — 加仓 5G + 新能源' },
              ]" :key="t.i" :style="{ display: 'flex', gap: '8px', padding: '5px 0', fontSize: '11px', color: A2.textSub }">
                <span :style="{ color: A2.qwen, fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700 }">{{ t.i }}</span>
                <span>{{ t.t }}</span>
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
              <div :style="{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '6px' }">
                <div v-for="s in SECTORS" :key="s.name"
                     class="heat-tile"
                     :style="{ background: heatBg(s), padding: '10px 12px', borderRadius: '7px', color: '#fff', minHeight: '56px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }">
                  <div :style="{ fontSize: '12px', fontWeight: 600 }">{{ s.name }}</div>
                  <div :style="{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }">
                    <span :style="{ fontSize: '14px', fontWeight: 800, fontFamily: 'IBM Plex Mono, monospace', letterSpacing: '-0.3px' }">{{ s.change >= 0 ? '+' : '' }}{{ s.change.toFixed(2) }}%</span>
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
          <div v-for="(s, i) in SECTORS" :key="s.name" :style="{ padding: '12px 14px', background: A2.surface, fontSize: '11px' }">
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
