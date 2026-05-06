<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import Shell from '../components/Shell.vue'
import Icon from '../components/Icon.vue'
import Sparkline from '../components/charts/Sparkline.vue'
import { A2 } from '../shared/theme.js'
import { genKline } from '../shared/data.js'
import { screenNL } from '../api/screener'

const router = useRouter()

const input = ref('')
const lastQuery = ref('')

const result = ref(null)         // { items, total, parsed_conditions }
const loading = ref(false)
const errorMsg = ref('')

// 历史对话（前端本地缓存）
const todayChats = ref([])
const presetPrompts = [
  '低估值高分红的银行股',
  'ROE 大于 15 且最新季度净利润同比正增长的成长股',
  '半导体行业市值 500 亿以上的龙头',
  '股息率超过 5% 的大蓝筹',
]

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

async function send() {
  const q = input.value.trim()
  if (!q || loading.value) return
  loading.value = true
  errorMsg.value = ''
  lastQuery.value = q
  try {
    const data = await screenNL(q)
    result.value = data
    todayChats.value.unshift({ t: q, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) })
    input.value = ''
  } catch (e) {
    errorMsg.value = e.response?.data?.detail || e.message || '请求失败'
  } finally {
    loading.value = false
  }
}

function pickPreset(p) {
  input.value = p
  send()
}
</script>

<template>
  <Shell>
    <div :style="{ flex: 1, display: 'grid', gridTemplateColumns: '240px 1fr 320px', overflow: 'hidden' }">
      <!-- Sidebar -->
      <div :style="{ background: A2.surface, padding: '14px', fontSize: '12px', overflow: 'auto', borderRight: `1px solid ${A2.borderHair}` }">
        <button :style="{ width: '100%', padding: '10px 12px', background: A2.qwenGrad, color: '#fff', border: 'none', fontSize: '12px', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', borderRadius: '8px', marginBottom: '16px', boxShadow: '0 2px 8px rgba(14,14,12,0.10)' }">
          <Icon name="plus" :size="12" /> 新建对话
        </button>
        <div :style="{ fontSize: '10px', color: A2.textDim, fontWeight: 700, letterSpacing: '1.2px', marginBottom: '8px' }">本次会话</div>
        <div v-if="!todayChats.length" :style="{ fontSize: '11px', color: A2.textMuted, padding: '8px 10px', lineHeight: 1.6 }">
          下方输入框试试看吧 ↓
        </div>
        <div v-for="c in todayChats" :key="c.time + c.t"
             :style="{ padding: '9px 11px', fontSize: '12px', cursor: 'pointer', background: A2.qwenSoft, color: A2.qwenDeep, borderRadius: '7px', marginBottom: '3px', fontWeight: 600, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderLeft: `2px solid ${A2.qwen}` }">
          <span :style="{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '160px' }">{{ c.t }}</span>
          <span :style="{ fontSize: '10px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace' }">{{ c.time }}</span>
        </div>

        <div :style="{ marginTop: '22px', padding: '12px', background: A2.bgDeep, borderRadius: '8px' }">
          <div :style="{ fontSize: '11px', fontWeight: 700, marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '5px' }">
            <Icon name="lightbulb" :size="11" :color="A2.amber" /> 推荐提问
          </div>
          <div v-for="t in presetPrompts" :key="t" @click="pickPreset(t)"
               :style="{ fontSize: '11px', padding: '6px 0', color: A2.textSub, cursor: 'pointer', lineHeight: 1.5 }">· {{ t }}</div>
        </div>
      </div>

      <!-- Main chat -->
      <div :style="{ background: A2.bg, display: 'flex', flexDirection: 'column', overflow: 'hidden' }">
        <div :style="{ flex: 1, overflow: 'auto', padding: '24px 36px' }">
          <!-- 起始引导 -->
          <div v-if="!lastQuery" :style="{ textAlign: 'center', padding: '60px 0', color: A2.textMuted }">
            <div :style="{ fontSize: '28px', marginBottom: '8px' }">💬</div>
            <div :style="{ fontSize: '14px', fontWeight: 600, color: A2.text, marginBottom: '4px' }">用自然语言筛选股票</div>
            <div :style="{ fontSize: '12px' }">例如：找出 PE 低于 15、ROE 大于 15% 的消费股</div>
          </div>

          <!-- User msg -->
          <div v-if="lastQuery" :style="{ display: 'flex', justifyContent: 'flex-end', marginBottom: '18px' }">
            <div :style="{ maxWidth: '70%', background: A2.surface, color: A2.text, padding: '12px 16px', borderRadius: '14px 14px 4px 14px', fontSize: '13px', lineHeight: 1.65, boxShadow: A2.shadow, border: `1px solid ${A2.borderHair}` }">
              {{ lastQuery }}
            </div>
          </div>

          <!-- AI thinking -->
          <div v-if="loading" :style="{ display: 'flex', gap: '12px', marginBottom: '14px' }">
            <div :style="{ width: '28px', height: '28px', background: A2.qwenGrad, color: '#fff', display: 'grid', placeItems: 'center', fontSize: '11px', fontWeight: 700, borderRadius: '8px', flexShrink: 0, boxShadow: '0 2px 6px rgba(14,14,12,0.10)' }">千</div>
            <div :style="{ flex: 1, background: A2.surface, padding: '12px 14px', fontSize: '12px', color: A2.textMuted, borderRadius: '8px', border: `1px solid ${A2.borderHair}` }">
              <div :style="{ display: 'flex', alignItems: 'center', gap: '6px', color: A2.text, fontWeight: 600 }">
                <Icon name="brain" :size="11" :color="A2.qwen" /> 千问思考中…
              </div>
              <div :style="{ marginTop: '6px', fontSize: '11px' }">解析自然语言 → 生成结构化筛选条件 → 引擎执行</div>
            </div>
          </div>

          <!-- Error -->
          <div v-if="errorMsg" :style="{ marginBottom: '18px', padding: '12px 16px', background: A2.upSoft, color: A2.up, borderRadius: '8px', fontSize: '12px', display: 'flex', alignItems: 'flex-start', gap: '10px' }">
            <Icon name="shield" :size="14" />
            <div style="flex:1">
              {{ errorMsg }}
              <div v-if="errorMsg.includes('OPENAI') || errorMsg.includes('DASHSCOPE') || errorMsg.includes('API_KEY')" :style="{ marginTop: '6px', fontSize: '11px', color: A2.textMuted }">
                请在 backend/.env 中配置 OPENAI_API_KEY 后重启 uvicorn。
              </div>
            </div>
            <button class="btn-outline" :style="{ padding: '4px 10px', fontSize: '11px' }" @click="lastQuery && (input = lastQuery, send())">
              <Icon name="refresh" :size="11" /> 重试
            </button>
          </div>

          <!-- Result -->
          <template v-if="result && !loading">
            <div :style="{ display: 'flex', gap: '12px', marginBottom: '16px' }">
              <div :style="{ width: '28px', flexShrink: 0 }" />
              <div :style="{ flex: 1, fontSize: '13.5px', lineHeight: 1.75 }">
                我已将你的需求拆解为结构化条件，命中
                <span :style="{ color: A2.qwenDeep, fontWeight: 800, fontSize: '16px' }">{{ result.total }}</span>
                只股票：
              </div>
            </div>

            <!-- Parsed conditions -->
            <div :style="{ marginLeft: '40px', marginBottom: '20px', display: 'flex', flexWrap: 'wrap', gap: '7px' }">
              <div v-for="(c, i) in (result.parsed_conditions || [])" :key="i"
                   :style="{ background: A2.surface, border: `1px solid ${A2.borderHair}`, padding: '7px 12px', fontSize: '11.5px', display: 'flex', alignItems: 'center', gap: '7px', borderRadius: '999px', boxShadow: A2.shadow }">
                <span :style="{ fontFamily: 'IBM Plex Mono, monospace', fontWeight: 600 }">{{ fmtCond(c) }}</span>
              </div>
              <div v-if="!result.parsed_conditions?.length" :style="{ fontSize: '11.5px', color: A2.textDim, padding: '7px 12px' }">
                （后端未回显条件）
              </div>
            </div>

            <!-- Result table -->
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
              <div v-else :style="{ padding: '40px 20px', textAlign: 'center', color: A2.textMuted, fontSize: '12px' }">
                没有命中股票，请放宽条件再试。
              </div>
            </div>
          </template>
        </div>

        <!-- Input -->
        <div :style="{ borderTop: `1px solid ${A2.borderHair}`, padding: '20px', background: A2.surface }">
          <div :style="{ border: `1px solid ${A2.borderHair}`, padding: '12px', background: A2.surface, borderRadius: '12px', boxShadow: A2.shadowMd }">
            <textarea v-model="input" @keydown.enter.exact.prevent="send" placeholder="例如：找出 PE 低于 15、ROE > 15%、近三年净利润复合增速 > 20% 的消费股…"
                      :style="{ width: '100%', height: '40px', border: 'none', outline: 'none', fontSize: '13.5px', fontFamily: 'IBM Plex Sans, Noto Sans SC, sans-serif', resize: 'none', background: 'transparent' }" />
            <div :style="{ display: 'flex', alignItems: 'center', gap: '6px', paddingTop: '8px', borderTop: `1px solid ${A2.borderHair}` }">
              <span :style="{ fontSize: '10px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace' }">Qwen-Plus · 沪深300 数据池</span>
              <div style="flex:1" />
              <button @click="send" :disabled="loading" :style="{ padding: '7px 14px', background: A2.qwenGrad, color: '#fff', border: 'none', fontSize: '12px', fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '5px', borderRadius: '7px', boxShadow: '0 2px 8px rgba(14,14,12,0.12)', opacity: loading ? 0.6 : 1 }">
                {{ loading ? '处理中...' : '发送' }} <Icon name="send" :size="12" />
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Right inspector -->
      <div :style="{ background: A2.surface, padding: '16px', fontSize: '11px', overflow: 'auto', borderLeft: `1px solid ${A2.borderHair}` }">
        <div :style="{ fontSize: '12px', fontWeight: 700, marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }">
          <Icon name="tools" :size="12" :color="A2.qwen" /> 解析过程
        </div>
        <div v-if="!result" :style="{ fontSize: '11px', color: A2.textMuted, lineHeight: 1.6 }">
          发送一条自然语言需求，将在这里展示千问的工具调用步骤。
        </div>
        <template v-else>
          <div v-for="step in [
            { t: 'parse_nl_query', s: 'success', out: `解析出 ${result.parsed_conditions?.length || 0} 个条件` },
            { t: 'apply_filters',  s: 'success', out: `命中 ${result.total} 只` },
            { t: 'build_response', s: 'success', out: `返回前 ${result.items.length} 只` },
          ]" :key="step.t" :style="{ padding: '8px 10px', borderLeft: `2px solid ${A2.up}`, background: A2.bgDeep, marginBottom: '5px', fontSize: '10.5px', borderRadius: '0 6px 6px 0' }">
            <div :style="{ fontFamily: 'IBM Plex Mono, monospace', color: A2.text, fontWeight: 600 }">{{ step.t }}()</div>
            <div :style="{ color: A2.textMuted, marginTop: '3px' }">{{ step.out }}</div>
          </div>
        </template>

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
</style>
