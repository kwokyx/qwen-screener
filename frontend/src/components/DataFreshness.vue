<script setup>
// 数据新鲜度指示 + 手动同步面板
// - 收起态：一个小标签显示 "数据：今日 / 1天前 / N天前"
// - 展开态：4 个任务的卡片，每张有"上次更新"+"立即同步"按钮

import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { A2 } from '../shared/theme.js'
import { dataHealth, triggerSync } from '../api/health'
import { toast } from '../stores/toast'
import { friendlyError } from '../shared/errors.js'
import Icon from './Icon.vue'

const open = ref(false)
const meta = ref({})            // sync_meta
const counts = ref(null)        // {basic, daily, financial, with_industry}
const latestDate = ref(null)
const loading = ref(false)
const running = ref({})         // {jobName: boolean}

const JOBS = [
  { name: 'daily_market',        label: '全市场行情',  desc: '5500+ 只 OHLC + 成交量', eta: '约 1 分钟' },
  { name: 'daily_value',         label: '估值快照',    desc: '沪深 300 + 中证 500 PE/PB/股息率', eta: '约 5 分钟' },
  { name: 'weekly_fundamentals', label: '行业 + 财务', desc: '行业标签 + ROE / 营收 / 净利', eta: '约 10 分钟' },
  { name: 'weekly_basic',        label: '股票池',      desc: '全 A 股代码列表更新', eta: '约 10 秒' },
]

async function refresh() {
  loading.value = true
  try {
    const r = await dataHealth()
    meta.value = r.sync_meta || {}
    counts.value = r.counts
    latestDate.value = r.latest_trade_date
  } catch (e) {
    /* 静默 */
  } finally {
    loading.value = false
  }
}

async function runJob(name) {
  if (running.value[name]) return
  running.value[name] = true
  toast.info(`${name} 已开始同步…`)
  try {
    const r = await triggerSync(name)
    if (r.meta?.status === 'success') {
      toast.success(`${labelOf(name)} 完成（${r.meta.detail || ''}）`)
    } else {
      toast.error(`${labelOf(name)} 失败：${r.meta?.detail || ''}`)
    }
    await refresh()
  } catch (e) {
    toast.error(friendlyError(e))
  } finally {
    running.value[name] = false
  }
}

function labelOf(name) {
  return JOBS.find((j) => j.name === name)?.label || name
}

function fmtRel(iso) {
  if (!iso) return '从未'
  const t = new Date(iso).getTime()
  const diff = (Date.now() - t) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`
  return new Date(iso).toLocaleDateString('zh-CN')
}

const summary = computed(() => {
  if (!latestDate.value) return { label: '加载中', tone: 'muted' }
  const d = new Date(latestDate.value)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const days = Math.round((today - d) / 86400000)
  if (days <= 0) return { label: '今日', tone: 'fresh' }
  if (days === 1) return { label: '昨日', tone: 'fresh' }
  if (days <= 3) return { label: `${days} 天前`, tone: 'meh' }
  return { label: `${days} 天前`, tone: 'stale' }
})

const summaryColor = computed(() =>
  summary.value.tone === 'fresh' ? A2.down :
  summary.value.tone === 'meh' ? A2.amber :
  summary.value.tone === 'stale' ? A2.up :
  A2.textMuted
)

function close() {
  open.value = false
}
function onDoc(e) {
  if (!open.value) return
  if (!e.target.closest('[data-data-freshness]')) close()
}

onMounted(() => {
  refresh()
  document.addEventListener('mousedown', onDoc)
})
onBeforeUnmount(() => document.removeEventListener('mousedown', onDoc))
</script>

<template>
  <div data-data-freshness :style="{ position: 'relative' }">
    <button @click="open = !open"
            :title="`数据更新于 ${latestDate || '未知'}，点击查看详情`"
            :style="{ display: 'inline-flex', alignItems: 'center', gap: '5px', padding: '4px 9px', background: 'transparent', border: `1px solid ${A2.borderHair}`, borderRadius: '999px', fontSize: '10.5px', cursor: 'pointer', color: A2.textSub, fontFamily: 'IBM Plex Mono, monospace', height: '24px' }">
      <span :style="{ width: '6px', height: '6px', borderRadius: '50%', background: summaryColor, display: 'inline-block' }" />
      数据 {{ summary.label }}
    </button>

    <Transition name="page-fade">
      <div v-if="open" :style="{ position: 'absolute', top: '32px', right: 0, width: '380px', background: A2.surface, borderRadius: '10px', boxShadow: A2.shadowLg, border: `1px solid ${A2.borderHair}`, zIndex: 50, overflow: 'hidden' }">
        <div :style="{ padding: '12px 14px', borderBottom: `1px solid ${A2.borderHair}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }">
          <div>
            <div :style="{ fontSize: '13px', fontWeight: 700 }">数据同步</div>
            <div :style="{ fontSize: '10.5px', color: A2.textMuted, marginTop: '2px' }">
              <span v-if="latestDate">最新交易日 <strong :style="{ color: A2.text, fontFamily: 'IBM Plex Mono, monospace' }">{{ latestDate }}</strong></span>
              <span v-else>未同步</span>
            </div>
          </div>
          <button class="btn-ghost" :style="{ width: '28px', height: '28px' }" @click="refresh" title="刷新状态">
            <Icon name="refresh" :size="13" :style="{ animation: loading ? 'spin 1s linear infinite' : 'none' }" />
          </button>
        </div>

        <!-- 数据覆盖度 -->
        <div v-if="counts" :style="{ padding: '10px 14px', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', borderBottom: `1px solid ${A2.borderHair}`, background: '#FBFBF9' }">
          <div v-for="c in [
            { l: '全市场', v: counts.daily },
            { l: '估值面', v: counts.financial },
            { l: '行业', v: counts.with_industry },
            { l: '股票池', v: counts.basic },
          ]" :key="c.l" :style="{ textAlign: 'center' }">
            <div :style="{ fontSize: '9.5px', color: A2.textMuted, fontWeight: 600, letterSpacing: '0.4px' }">{{ c.l }}</div>
            <div :style="{ fontSize: '14px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace', color: A2.text, marginTop: '2px' }">{{ c.v.toLocaleString() }}</div>
          </div>
        </div>

        <!-- 任务列表 -->
        <div :style="{ padding: '6px 0', maxHeight: '380px', overflowY: 'auto' }">
          <div v-for="j in JOBS" :key="j.name" :style="{ padding: '10px 14px', borderTop: `1px solid ${A2.borderHair}`, display: 'flex', alignItems: 'center', gap: '10px' }">
            <div :style="{ flex: 1, minWidth: 0 }">
              <div :style="{ display: 'flex', alignItems: 'center', gap: '6px' }">
                <span :style="{ fontSize: '12px', fontWeight: 600, color: A2.text }">{{ j.label }}</span>
                <span v-if="meta[j.name]?.status === 'failed'" :style="{ fontSize: '9px', padding: '1px 5px', background: A2.upSoft, color: A2.up, borderRadius: '3px', fontWeight: 700 }">失败</span>
                <span v-else-if="meta[j.name]?.status === 'success'" :style="{ fontSize: '9px', padding: '1px 5px', background: A2.downSoft, color: A2.down, borderRadius: '3px', fontWeight: 700 }">已同步</span>
              </div>
              <div :style="{ fontSize: '10.5px', color: A2.textMuted, marginTop: '2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">{{ j.desc }}</div>
              <div :style="{ fontSize: '10px', color: A2.textDim, marginTop: '2px', fontFamily: 'IBM Plex Mono, monospace' }">
                上次：{{ fmtRel(meta[j.name]?.last_run_at) }}<span v-if="meta[j.name]?.duration_ms"> · {{ (meta[j.name].duration_ms / 1000).toFixed(0) }}s</span>
              </div>
            </div>
            <button @click="runJob(j.name)" :disabled="running[j.name]"
                    :title="`预计 ${j.eta}`"
                    class="btn-outline" :style="{ padding: '5px 10px', fontSize: '11px', whiteSpace: 'nowrap', minWidth: '64px' }">
              <Icon name="refresh" :size="11" :style="{ animation: running[j.name] ? 'spin 1s linear infinite' : 'none' }" />
              {{ running[j.name] ? '同步中…' : '立即同步' }}
            </button>
          </div>
        </div>

        <div :style="{ padding: '8px 14px', fontSize: '10.5px', color: A2.textDim, lineHeight: 1.5, background: '#FBFBF9', borderTop: `1px solid ${A2.borderHair}` }">
          系统每个交易日 15:30（行情）/ 16:00（估值）/ 周末（财务）自动更新，也可以在这里手动触发。
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
@keyframes spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
</style>
