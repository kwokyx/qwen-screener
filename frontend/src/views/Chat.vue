<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import Sparkline from '../components/charts/Sparkline.vue'
import EmptyState from '../components/EmptyState.vue'
import { A2 } from '../shared/theme.js'
import { genKline } from '../shared/data.js'
import { streamNL } from '../api/screener'
import { friendlyError } from '../shared/errors.js'

const router = useRouter()
const route = useRoute()

const input = ref('')
const lastQuery = ref('')

// 流式状态机：idle → thinking → parsed → screening → done | error
const phase = ref('idle')
const thinkingBuf = ref('')          // 累积 JSON token，用于"思考预览"
const parsedConditions = ref([])     // parsed 事件
const screenMeta = ref(null)         // { logic, sort_by, sort_desc, limit }
const result = ref(null)             // result 事件 { items, total, parsed_conditions }
const errorMsg = ref('')
let abortCtrl = null

// 时间戳记录每个阶段，用于在右侧 inspector 显示用时
const tStart = ref(0)
const tParsed = ref(0)
const tDone = ref(0)

const todayChats = ref([])
const presetPrompts = [
  '低估值高分红的银行股',
  'ROE 大于 15 且最新季度净利润同比正增长的成长股',
  '半导体行业市值 500 亿以上的龙头',
  '股息率超过 5% 的大蓝筹',
]

const isStreaming = computed(() =>
  phase.value === 'thinking' || phase.value === 'parsed' || phase.value === 'screening'
)

function bullScore(it) {
  let s = 60
  if (it.pe && it.pe > 0) s += Math.max(0, Math.min(20, 25 - it.pe * 0.5))
  if (it.dividend_yield) s += Math.min(15, it.dividend_yield * 2)
  if (it.roe) s += Math.min(15, it.roe)
  return Math.round(Math.max(0, Math.min(99, s)))
}

const sparkCache = new Map()
function spark(code, idx) {
  if (!sparkCache.has(code)) {
    sparkCache.set(code, genKline(100, 30, 0.02, idx + 11).map((d) => d.c))
  }
  return sparkCache.get(code)
}

const opLabel = { gt: '>', gte: '≥', lt: '<', lte: '≤', eq: '=', between: '∈', in: '∈' }
function fmtCond(c) {
  if (Array.isArray(c.value)) return `${c.field} ${opLabel[c.op] || c.op} [${c.value.join(', ')}]`
  return `${c.field} ${opLabel[c.op] || c.op} ${c.value}`
}

// 0 命中时给具体可操作建议，根据已解析的条件挑最严的一条
const zeroResultHint = computed(() => {
  const cs = parsedConditions.value
  if (!cs.length) return '试着把条件描述得更具体一些'
  // 优先去掉 industry / market 这种枚举型
  const enumCond = cs.find((c) => c.field === 'industry' || c.field === 'market')
  if (enumCond) return `当前数据池可能不含「${Array.isArray(enumCond.value) ? enumCond.value.join(' / ') : enumCond.value}」，可以去掉行业限制再试`
  // 其次找数值最严的
  const tight = cs.find((c) => c.op === 'lt' || c.op === 'lte') || cs[0]
  return `条件可能太严格，例如 "${tight.field} ${opLabel[tight.op] || tight.op} ${tight.value}" 放宽一些试试`
})

// 思考预览只显示最后 ~120 字（多了滚动太抖）；保留首尾换行更自然
const thinkingPreview = computed(() => {
  const s = thinkingBuf.value
  if (s.length <= 200) return s
  return '…' + s.slice(-200)
})

function reset() {
  phase.value = 'idle'
  thinkingBuf.value = ''
  parsedConditions.value = []
  screenMeta.value = null
  result.value = null
  errorMsg.value = ''
}

async function send() {
  const q = input.value.trim()
  if (!q || isStreaming.value) return

  reset()
  lastQuery.value = q
  phase.value = 'thinking'
  tStart.value = Date.now()
  tParsed.value = 0
  tDone.value = 0
  abortCtrl = new AbortController()

  try {
    await streamNL(q, (ev) => {
      if (ev.type === 'thinking') {
        thinkingBuf.value += ev.text
      } else if (ev.type === 'parsed') {
        parsedConditions.value = ev.conditions || []
        screenMeta.value = { logic: ev.logic, sort_by: ev.sort_by, sort_desc: ev.sort_desc, limit: ev.limit }
        phase.value = 'parsed'
        tParsed.value = Date.now()
      } else if (ev.type === 'screening') {
        phase.value = 'screening'
      } else if (ev.type === 'result') {
        result.value = {
          items: ev.items || [],
          total: ev.total || 0,
          parsed_conditions: ev.parsed_conditions || parsedConditions.value,
        }
      } else if (ev.type === 'done') {
        phase.value = 'done'
        tDone.value = Date.now()
      } else if (ev.type === 'error') {
        errorMsg.value = friendlyError(ev.message, { context: 'ai' })
        phase.value = 'error'
      }
    }, abortCtrl.signal)

    // 流正常结束但没收到 'done'
    if (phase.value !== 'error' && phase.value !== 'done') {
      phase.value = 'done'
      tDone.value = Date.now()
    }

    if (phase.value === 'done') {
      todayChats.value.unshift({
        t: q,
        time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      })
      input.value = ''
    }
  } catch (e) {
    if (e.name === 'AbortError') {
      phase.value = 'idle'
    } else {
      errorMsg.value = friendlyError(e, { context: 'ai' })
      phase.value = 'error'
    }
  } finally {
    abortCtrl = null
  }
}

function stop() {
  abortCtrl?.abort()
}

function pickPreset(p) {
  input.value = p
  send()
}

// 从其他页面跳转携带 ?q=xxx 时自动发送
onMounted(() => {
  const q = route.query.q
  if (q && typeof q === 'string') {
    input.value = q
    send()
    // 用过即清，刷新不重发
    router.replace({ path: '/chat' })
  }
})

// ---- 右侧 inspector：每阶段对应一行 ----
const stages = computed(() => {
  const items = []
  const elapsed = (a, b) => (b > a ? `${((b - a) / 1000).toFixed(1)}s` : '')
  // 1. 解析
  let s1State = 'pending'
  if (phase.value === 'thinking') s1State = 'running'
  else if (phase.value === 'parsed' || phase.value === 'screening' || phase.value === 'done') s1State = 'success'
  else if (phase.value === 'error' && !parsedConditions.value.length) s1State = 'failed'
  else if (phase.value === 'idle') s1State = 'pending'
  items.push({
    t: 'parse_nl_query',
    state: s1State,
    out: parsedConditions.value.length
      ? `识别出 ${parsedConditions.value.length} 个条件`
      : (phase.value === 'thinking' ? '千问解析中…' : '等待输入'),
    dur: tParsed.value && tStart.value ? elapsed(tStart.value, tParsed.value) : '',
  })
  // 2. 执行筛选
  let s2State = 'pending'
  if (phase.value === 'screening') s2State = 'running'
  else if (phase.value === 'done') s2State = 'success'
  else if (phase.value === 'error' && parsedConditions.value.length) s2State = 'failed'
  items.push({
    t: 'apply_filters',
    state: s2State,
    out: result.value ? `命中 ${result.value.total} 只 · 已展示 ${result.value.items.length}` : '等待解析完成',
    dur: tDone.value && tParsed.value ? elapsed(tParsed.value, tDone.value) : '',
  })
  return items
})

const stageColor = (s) => ({
  pending: A2.textDim,
  running: A2.qwen,
  success: A2.up,
  failed: A2.down,
}[s] || A2.textDim)
</script>

<template>
  <Shell>
    <div :style="{ flex: 1, display: 'grid', gridTemplateColumns: '240px 1fr 320px', overflow: 'hidden' }">
      <!-- Sidebar -->
      <div :style="{ background: A2.surface, padding: '14px', fontSize: '12px', overflow: 'auto', borderRight: `1px solid ${A2.borderHair}` }">
        <button :style="{ width: '100%', padding: '10px 12px', background: A2.qwenGrad, color: '#fff', border: 'none', fontSize: '12px', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', borderRadius: '8px', marginBottom: '16px', boxShadow: '0 2px 8px rgba(14,14,12,0.10)' }"
                @click="stop(); reset(); lastQuery = ''">
          <Icon name="plus" :size="12" /> 新建对话
        </button>
        <div :style="{ fontSize: '10px', color: A2.textDim, fontWeight: 700, letterSpacing: '1.2px', marginBottom: '8px' }">本次会话</div>
        <div v-if="!todayChats.length" :style="{ fontSize: '11px', color: A2.textMuted, padding: '8px 10px', lineHeight: 1.6 }">
          下方输入框试试看吧 ↓
        </div>
        <div v-for="c in todayChats" :key="c.time + c.t"
             @click="!isStreaming && pickPreset(c.t)"
             :title="isStreaming ? '当前对话进行中，请先停止' : '点击重新提问'"
             :style="{ padding: '9px 11px', fontSize: '12px', cursor: isStreaming ? 'wait' : 'pointer', background: A2.qwenSoft, color: A2.qwenDeep, borderRadius: '7px', marginBottom: '3px', fontWeight: 600, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderLeft: `2px solid ${A2.qwen}`, opacity: isStreaming ? 0.5 : 1 }">
          <span :style="{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '160px' }">{{ c.t }}</span>
          <span :style="{ fontSize: '10px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace' }">{{ c.time }}</span>
        </div>

        <div :style="{ marginTop: '22px', padding: '12px', background: A2.bgDeep, borderRadius: '8px' }">
          <div :style="{ fontSize: '11px', fontWeight: 700, marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '5px' }">
            <Icon name="lightbulb" :size="11" :color="A2.amber" /> 推荐提问
          </div>
          <div v-for="t in presetPrompts" :key="t"
               @click="!isStreaming && pickPreset(t)"
               :style="{ fontSize: '11px', padding: '6px 0', color: A2.textSub, cursor: isStreaming ? 'wait' : 'pointer', lineHeight: 1.5, opacity: isStreaming ? 0.5 : 1 }">· {{ t }}</div>
        </div>
      </div>

      <!-- Main chat -->
      <div :style="{ background: A2.bg, display: 'flex', flexDirection: 'column', overflow: 'hidden' }">
        <div :style="{ flex: 1, overflow: 'auto', padding: '24px 36px' }">
          <!-- 起始引导 -->
          <div v-if="!lastQuery" :style="{ textAlign: 'center', padding: '60px 0', color: A2.textMuted }">
            <div :style="{ display: 'inline-grid', placeItems: 'center', width: '52px', height: '52px', borderRadius: '50%', background: A2.qwenSoft, color: A2.qwen, marginBottom: '12px' }">
              <Icon name="sparkle" :size="24" />
            </div>
            <div :style="{ fontSize: '14px', fontWeight: 600, color: A2.text, marginBottom: '4px' }">用自然语言筛选股票</div>
            <div :style="{ fontSize: '12px' }">例如：找出 PE 低于 15、ROE 大于 15% 的消费股</div>
          </div>

          <!-- User msg -->
          <div v-if="lastQuery" :style="{ display: 'flex', justifyContent: 'flex-end', marginBottom: '18px' }">
            <div :style="{ maxWidth: '70%', background: A2.surface, color: A2.text, padding: '12px 16px', borderRadius: '14px 14px 4px 14px', fontSize: '13px', lineHeight: 1.65, boxShadow: A2.shadow, border: `1px solid ${A2.borderHair}` }">
              {{ lastQuery }}
            </div>
          </div>

          <!-- AI thinking with live JSON preview -->
          <div v-if="phase === 'thinking'" :style="{ display: 'flex', gap: '12px', marginBottom: '14px' }">
            <div :style="{ width: '28px', height: '28px', background: A2.qwenGrad, color: '#fff', display: 'grid', placeItems: 'center', fontSize: '11px', fontWeight: 700, borderRadius: '8px', flexShrink: 0, boxShadow: '0 2px 6px rgba(14,14,12,0.10)' }">千</div>
            <div :style="{ flex: 1, background: A2.surface, padding: '12px 14px', fontSize: '12px', color: A2.textMuted, borderRadius: '8px', border: `1px solid ${A2.borderHair}` }">
              <div :style="{ display: 'flex', alignItems: 'center', gap: '6px', color: A2.text, fontWeight: 600 }">
                <Icon name="brain" :size="11" :color="A2.qwen" />
                <span>正在拆解你的需求…</span>
                <span class="dot-flow"><i></i><i></i><i></i></span>
              </div>
              <pre v-if="thinkingBuf" :style="{ margin: '8px 0 0 0', fontSize: '10.5px', fontFamily: 'IBM Plex Mono, monospace', color: A2.textDim, lineHeight: 1.55, whiteSpace: 'pre-wrap', background: A2.bgDeep, padding: '8px 10px', borderRadius: '5px', maxHeight: '120px', overflow: 'hidden' }">{{ thinkingPreview }}<span class="caret-mono" /></pre>
            </div>
          </div>

          <!-- Parsed conditions（从 parsed 阶段开始展示，stagger 动画） -->
          <template v-if="parsedConditions.length">
            <div :style="{ display: 'flex', gap: '12px', marginBottom: '12px' }">
              <div :style="{ width: '28px', flexShrink: 0 }" />
              <div :style="{ flex: 1, fontSize: '13.5px', lineHeight: 1.75 }">
                我已将你的需求拆解为结构化条件<span v-if="phase === 'screening'" :style="{ color: A2.textMuted, fontWeight: 500 }">，引擎执行中…</span><span v-else-if="result">，命中 <span :style="{ color: A2.qwenDeep, fontWeight: 800, fontSize: '16px' }">{{ result.total }}</span> 只</span>：
              </div>
            </div>
            <div :style="{ marginLeft: '40px', marginBottom: '20px', display: 'flex', flexWrap: 'wrap', gap: '7px' }">
              <div v-for="(c, i) in parsedConditions" :key="i"
                   class="cond-chip"
                   :style="{ '--delay': (i * 60) + 'ms', background: A2.surface, border: `1px solid ${A2.borderHair}`, padding: '7px 12px', fontSize: '11.5px', display: 'flex', alignItems: 'center', gap: '7px', borderRadius: '999px', boxShadow: A2.shadow }">
                <span :style="{ fontFamily: 'IBM Plex Mono, monospace', fontWeight: 600 }">{{ fmtCond(c) }}</span>
              </div>
            </div>
          </template>

          <!-- Screening 中的 Skeleton 占位 -->
          <div v-if="phase === 'screening'" :style="{ marginLeft: '40px', marginBottom: '20px', background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', boxShadow: A2.shadowMd, overflow: 'hidden' }">
            <div :style="{ padding: '14px 16px', display: 'flex', alignItems: 'center', gap: '8px', color: A2.textMuted, fontSize: '12px', borderBottom: `1px solid ${A2.borderHair}` }">
              <span class="dot-flow" :style="{ '--c': A2.qwen }"><i></i><i></i><i></i></span>
              引擎正在执行筛选…
            </div>
            <div v-for="n in 4" :key="n" :style="{ display: 'grid', gridTemplateColumns: '36px 1fr 80px 80px 80px', gap: '12px', padding: '11px 16px', borderTop: n > 1 ? `1px solid ${A2.borderHair}` : 'none', alignItems: 'center' }">
              <div class="sk-bar" :style="{ height: '12px', borderRadius: '3px' }" />
              <div class="sk-bar" :style="{ height: '14px', width: '60%', borderRadius: '3px' }" />
              <div class="sk-bar" :style="{ height: '12px', borderRadius: '3px' }" />
              <div class="sk-bar" :style="{ height: '12px', borderRadius: '3px' }" />
              <div class="sk-bar" :style="{ height: '12px', borderRadius: '3px' }" />
            </div>
          </div>

          <!-- Error -->
          <div v-if="phase === 'error'" :style="{ marginBottom: '18px', padding: '12px 16px', background: A2.upSoft, color: A2.up, borderRadius: '8px', fontSize: '12px', display: 'flex', alignItems: 'flex-start', gap: '10px' }">
            <Icon name="shield" :size="14" />
            <div style="flex:1">
              {{ errorMsg }}
            </div>
            <button class="btn-outline" :style="{ padding: '4px 10px', fontSize: '11px' }" @click="lastQuery && (input = lastQuery, send())">
              <Icon name="refresh" :size="11" /> 重试
            </button>
          </div>

          <!-- Result table -->
          <template v-if="result">
            <div :style="{ marginLeft: '40px', marginBottom: '20px', background: A2.surface, border: `1px solid ${A2.borderHair}`, borderRadius: '10px', boxShadow: A2.shadowMd, overflow: 'hidden' }">
              <div :style="{ padding: '12px 16px', borderBottom: `1px solid ${A2.borderHair}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#FBFBF9' }">
                <div>
                  <div :style="{ fontSize: '13px', fontWeight: 700 }">筛选结果</div>
                  <div :style="{ fontSize: '11px', color: A2.textMuted, marginTop: '1px' }">共 <strong :style="{ color: A2.text }">{{ result.total }}</strong> 只 · 已展示前 {{ result.items.length }} 只</div>
                </div>
                <button @click="router.push('/results')" :style="{ fontSize: '11px', padding: '5px 12px', background: A2.qwenGrad, color: '#fff', border: 'none', cursor: 'pointer', borderRadius: '6px', fontWeight: 600, boxShadow: '0 1px 4px rgba(14,14,12,0.10)' }">
                  查看完整列表 →
                </button>
              </div>
              <table v-if="result.items.length" :style="{ width: '100%', borderCollapse: 'collapse', fontSize: '11.5px' }">
                <thead>
                  <tr :style="{ color: A2.textMuted, fontSize: '10px', fontWeight: 600, letterSpacing: '0.4px' }">
                    <th :style="{ textAlign: 'left', padding: '8px 16px', fontWeight: 600 }">#</th>
                    <th :style="{ textAlign: 'left', padding: '8px 8px', fontWeight: 600 }">代码 / 名称</th>
                    <th :style="{ textAlign: 'left', padding: '8px 8px', fontWeight: 600 }">行业</th>
                    <th :style="{ textAlign: 'right', padding: '8px 8px', fontWeight: 600 }">现价</th>
                    <th :style="{ textAlign: 'right', padding: '8px 8px', fontWeight: 600 }">PE</th>
                    <th :style="{ textAlign: 'right', padding: '8px 8px', fontWeight: 600 }">ROE</th>
                    <th :style="{ textAlign: 'right', padding: '8px 8px', fontWeight: 600 }">股息率</th>
                    <th :style="{ textAlign: 'right', padding: '8px 8px', fontWeight: 600 }">市值</th>
                    <th :style="{ textAlign: 'left', padding: '8px 8px', fontWeight: 600 }">千问评分</th>
                    <th :style="{ textAlign: 'left', padding: '8px 8px', fontWeight: 600 }">30 日</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(s, i) in result.items.slice(0, 10)" :key="s.code" class="row-hover"
                      :style="{ borderTop: `1px solid ${A2.borderHair}`, cursor: 'pointer' }"
                      @click="router.push(`/detail/${s.code}`)">
                    <td :style="{ padding: '11px 16px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace', fontSize: '10px' }">{{ String(i+1).padStart(2,'0') }}</td>
                    <td :style="{ padding: '11px 8px' }">
                      <div :style="{ fontWeight: 600, fontSize: '12.5px' }">{{ s.name }}</div>
                      <div :style="{ fontSize: '10px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace' }">{{ s.code }}</div>
                    </td>
                    <td :style="{ padding: '11px 8px', color: A2.textSub, fontSize: '11px' }">{{ s.industry || '—' }}</td>
                    <td :style="{ padding: '11px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: A2.text }">{{ s.close != null ? s.close.toFixed(2) : '—' }}</td>
                    <td :style="{ padding: '11px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ s.pe != null && s.pe > 0 ? s.pe.toFixed(2) : '—' }}</td>
                    <td :style="{ padding: '11px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: s.roe > 10 ? A2.up : A2.textSub, fontWeight: s.roe > 10 ? 600 : 500 }">{{ s.roe != null ? s.roe.toFixed(2) + '%' : '—' }}</td>
                    <td :style="{ padding: '11px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: s.dividend_yield > 4 ? A2.up : A2.textSub }">{{ s.dividend_yield != null ? s.dividend_yield.toFixed(2) + '%' : '—' }}</td>
                    <td :style="{ padding: '11px 8px', textAlign: 'right', fontFamily: 'IBM Plex Mono, monospace', color: A2.textSub }">{{ s.market_cap != null ? Math.round(s.market_cap).toLocaleString() : '—' }}<span :style="{ fontSize: '9px', color: A2.textDim }">亿</span></td>
                    <td :style="{ padding: '11px 8px' }">
                      <div :style="{ display: 'flex', alignItems: 'center', gap: '6px' }">
                        <div :style="{ width: '50px', height: '5px', background: A2.bgDeep, borderRadius: '3px', overflow: 'hidden' }">
                          <div :style="{ width: `${bullScore(s)}%`, height: '100%', background: A2.qwenGrad }" />
                        </div>
                        <span :style="{ fontFamily: 'IBM Plex Mono, monospace', fontWeight: 700, color: A2.qwenDeep, fontSize: '11px' }">{{ bullScore(s) }}</span>
                      </div>
                    </td>
                    <td :style="{ padding: '11px 8px' }"><Sparkline :data="spark(s.code, i)" :width="72" :height="20" /></td>
                  </tr>
                </tbody>
              </table>
              <EmptyState v-else icon="filter" title="没有命中任何股票" :subtitle="zeroResultHint" />
            </div>
          </template>
        </div>

        <!-- Input -->
        <div :style="{ borderTop: `1px solid ${A2.borderHair}`, padding: '20px', background: A2.surface }">
          <div :style="{ border: `1px solid ${A2.borderHair}`, padding: '12px', background: A2.surface, borderRadius: '12px', boxShadow: A2.shadowMd }">
            <textarea v-model="input"
                      @keydown.enter.exact.prevent="send"
                      :disabled="isStreaming"
                      placeholder="例如：找出 PE 低于 15、ROE > 15%、近三年净利润复合增速 > 20% 的消费股…"
                      :style="{ width: '100%', height: '40px', border: 'none', outline: 'none', fontSize: '13.5px', fontFamily: 'IBM Plex Sans, Noto Sans SC, sans-serif', resize: 'none', background: 'transparent', opacity: isStreaming ? 0.6 : 1 }" />
            <div :style="{ display: 'flex', alignItems: 'center', gap: '6px', paddingTop: '8px', borderTop: `1px solid ${A2.borderHair}` }">
              <span :style="{ fontSize: '10px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace' }">{{ phase === 'thinking' ? '解析中…' : phase === 'screening' ? '执行中…' : 'Stream · SSE' }}</span>
              <div style="flex:1" />
              <button v-if="isStreaming" @click="stop"
                      :style="{ padding: '7px 14px', background: '#3F3D38', color: '#fff', border: 'none', fontSize: '12px', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px', borderRadius: '7px', boxShadow: '0 2px 8px rgba(14,14,12,0.12)' }">
                <Icon name="x" :size="12" /> 停止
              </button>
              <button v-else @click="send"
                      :style="{ padding: '7px 14px', background: A2.qwenGrad, color: '#fff', border: 'none', fontSize: '12px', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px', borderRadius: '7px', boxShadow: '0 2px 8px rgba(14,14,12,0.12)' }">
                发送 <Icon name="send" :size="12" />
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Right inspector：实时阶段时间轴 -->
      <div :style="{ background: A2.surface, padding: '16px', fontSize: '11px', overflow: 'auto', borderLeft: `1px solid ${A2.borderHair}` }">
        <div :style="{ fontSize: '12px', fontWeight: 700, marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }">
          <Icon name="tools" :size="12" :color="A2.qwen" /> 实时执行
          <span v-if="phase !== 'idle'" :style="{ marginLeft: 'auto', fontSize: '10px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace' }">{{ phase }}</span>
        </div>

        <div v-if="phase === 'idle'" :style="{ fontSize: '11px', color: A2.textMuted, lineHeight: 1.6 }">
          发送一条自然语言需求，将在这里展示千问的工具调用步骤。
        </div>

        <template v-else>
          <div v-for="(stg, i) in stages" :key="stg.t"
               :style="{ padding: '8px 10px', borderLeft: `2px solid ${stageColor(stg.state)}`, background: A2.bgDeep, marginBottom: '5px', fontSize: '10.5px', borderRadius: '0 6px 6px 0' }">
            <div :style="{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontFamily: 'IBM Plex Mono, monospace', color: A2.text, fontWeight: 600 }">
              <span :style="{ display: 'flex', alignItems: 'center', gap: '6px' }">
                <span class="stage-dot" :class="stg.state" :style="{ '--c': stageColor(stg.state) }"></span>
                {{ stg.t }}()
              </span>
              <span :style="{ color: A2.textDim, fontWeight: 500 }">{{ stg.dur || (stg.state === 'running' ? '…' : '') }}</span>
            </div>
            <div :style="{ color: A2.textMuted, marginTop: '3px' }">{{ stg.out }}</div>
          </div>
        </template>

        <div v-if="screenMeta" :style="{ marginTop: '14px', padding: '10px 12px', background: A2.bgDeep, borderRadius: '6px', fontSize: '10.5px', color: A2.textSub, fontFamily: 'IBM Plex Mono, monospace', lineHeight: 1.6 }">
          <div :style="{ color: A2.textDim, fontSize: '9.5px', letterSpacing: '1px', marginBottom: '4px' }">QUERY META</div>
          logic = {{ screenMeta.logic }}<br />
          sort_by = {{ screenMeta.sort_by || '—' }}<br />
          sort_desc = {{ screenMeta.sort_desc }}<br />
          limit = {{ screenMeta.limit }}
        </div>

        <div :style="{ marginTop: '18px', padding: '12px', background: A2.qwenGradSoft, borderRadius: '8px', fontSize: '11px', lineHeight: 1.55, border: `1px solid ${A2.borderHair}` }">
          <div :style="{ fontWeight: 700, color: A2.qwenDeep, marginBottom: '5px', display: 'flex', alignItems: 'center', gap: '5px' }"><Icon name="shield" :size="11" /> 风险提示</div>
          <div :style="{ color: A2.textSub }">本结果仅供研究参考，不构成投资建议。</div>
        </div>
      </div>
    </div>
  </Shell>
</template>

<style scoped>
.row-hover { transition: background 0.15s; }
.row-hover:hover { background: #EFEDE6; }

/* 条件 chip 出现动画（stagger 由 inline --delay 控制） */
.cond-chip {
  opacity: 0;
  transform: translateY(4px);
  animation: chip-pop 0.32s cubic-bezier(0.4, 0, 0.2, 1) forwards;
  animation-delay: var(--delay, 0ms);
}
@keyframes chip-pop {
  to { opacity: 1; transform: translateY(0); }
}

/* 三点流动 */
.dot-flow {
  display: inline-flex;
  gap: 3px;
  align-items: center;
  margin-left: 2px;
}
.dot-flow i {
  width: 4px; height: 4px;
  background: var(--c, #2456D8);
  border-radius: 50%;
  animation: dot-bob 1s infinite ease-in-out;
}
.dot-flow i:nth-child(2) { animation-delay: 0.15s; }
.dot-flow i:nth-child(3) { animation-delay: 0.30s; }
@keyframes dot-bob {
  0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
  40% { opacity: 1; transform: translateY(-3px); }
}

/* 思考预览的等宽光标 */
.caret-mono {
  display: inline-block;
  width: 5px;
  height: 12px;
  margin-left: 1px;
  background: #B8B4A8;
  vertical-align: middle;
  animation: caret-blink 1s steps(2) infinite;
}
@keyframes caret-blink { 50% { opacity: 0; } }

/* skeleton 行（与全局 .sk 同样的 shimmer） */
.sk-bar {
  background: linear-gradient(90deg, rgba(14,14,12,0.05) 25%, rgba(14,14,12,0.10) 37%, rgba(14,14,12,0.05) 63%);
  background-size: 400% 100%;
  animation: sk-shimmer 1.4s ease-in-out infinite;
}
@keyframes sk-shimmer {
  0% { background-position: 100% 50%; }
  100% { background-position: 0 50%; }
}

/* inspector 阶段圆点 */
.stage-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--c);
  display: inline-block;
}
.stage-dot.running { animation: pulse-ring 1.2s infinite; }
@keyframes pulse-ring {
  0%   { box-shadow: 0 0 0 0 rgba(36,86,216,0.45); }
  70%  { box-shadow: 0 0 0 6px rgba(36,86,216,0); }
  100% { box-shadow: 0 0 0 0 rgba(36,86,216,0); }
}
</style>
