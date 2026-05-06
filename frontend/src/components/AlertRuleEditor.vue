<script setup>
import { computed, ref } from 'vue'
import { useWatchlistStore } from '../stores/watchlist'
import { useNotificationsStore } from '../stores/notifications'
import { toast } from '../stores/toast'
import { A2 } from '../shared/theme.js'
import Icon from './Icon.vue'

const props = defineProps({
  code: { type: String, required: true },
})

const wl = useWatchlistStore()
const notif = useNotificationsStore()

const item = computed(() => wl.get(props.code))
const open = ref(false)

const newRule = ref({ type: 'pct_up', threshold: 20 })

const ruleTypes = [
  { value: 'pct_up',   label: '累计涨幅 ≥', unit: '%', placeholder: '20' },
  { value: 'pct_down', label: '累计跌幅 ≥', unit: '%', placeholder: '15' },
  { value: 'price_gt', label: '现价突破 ≥', unit: '元', placeholder: '100' },
  { value: 'price_lt', label: '现价跌破 ≤', unit: '元', placeholder: '50' },
  { value: 'day_pct',  label: '日内涨跌 ≥', unit: '%', placeholder: '5' },
]

const currentType = computed(() => ruleTypes.find((t) => t.value === newRule.value.type))

function add() {
  const t = parseFloat(newRule.value.threshold)
  if (isNaN(t)) {
    toast.warning('请输入有效阈值')
    return
  }
  wl.addAlert(props.code, {
    type: newRule.value.type,
    threshold: t,
  })
  toast.success('预警已添加')
  newRule.value.threshold = ''
}

function removeRule(id) {
  wl.removeAlert(props.code, id)
  toast.info('预警已删除')
}

function fmtRule(a) {
  const tt = ruleTypes.find((t) => t.value === a.type)
  return `${tt?.label || a.type} ${a.threshold}${tt?.unit || ''}`
}

function fireTest() {
  notif.push({
    kind: 'alert',
    tone: 'qwen',
    tag: '测试',
    stock: item.value?.name || props.code,
    code: props.code,
    desc: '这是一条测试通知 · 用来验证桌面通知 / 通知中心是否生效',
  })
}
</script>

<template>
  <div v-if="item" class="alert-editor">
    <button class="btn-outline" @click="open = !open">
      <Icon name="bell" :size="12" />
      预警 <span v-if="item.alerts.length" :style="{ fontFamily: 'IBM Plex Mono, monospace', color: A2.qwen, fontWeight: 700 }">{{ item.alerts.length }}</span>
    </button>

    <Transition name="page-fade">
      <div v-if="open" class="alert-pop" :style="{ background: A2.surface, boxShadow: A2.shadowLg, border: `1px solid ${A2.borderHair}` }">
        <div :style="{ padding: '12px 14px', borderBottom: `1px solid ${A2.borderHair}`, display: 'flex', alignItems: 'center', gap: '8px' }">
          <Icon name="bell" :size="13" :color="A2.qwen" />
          <div :style="{ fontSize: '13px', fontWeight: 700 }">预警规则</div>
          <span :style="{ fontSize: '10px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace' }">{{ item.code }}</span>
          <div style="flex:1" />
          <button class="btn-ghost" :style="{ width: 'auto', padding: '0 6px', fontSize: '11px' }" title="立即触发一条测试通知" @click="fireTest">
            🧪 测试
          </button>
        </div>

        <div :style="{ padding: '10px 14px' }">
          <div v-if="!item.alerts.length" :style="{ fontSize: '11.5px', color: A2.textMuted, padding: '8px 0', textAlign: 'center' }">
            还没有规则，下方添加一条
          </div>
          <div v-for="a in item.alerts" :key="a.id"
               :style="{ display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 8px', background: A2.bgDeep, borderRadius: '6px', marginBottom: '5px', fontSize: '11.5px' }">
            <input type="checkbox" :checked="a.enabled" @change="wl.setAlertEnabled(item.code, a.id, $event.target.checked)" />
            <span :style="{ flex: 1, color: A2.text }">{{ fmtRule(a) }}</span>
            <span v-if="a.lastTriggered" :style="{ fontSize: '10px', color: A2.textMuted, fontFamily: 'IBM Plex Mono, monospace' }" title="最近一次触发">
              已触发
            </span>
            <button class="btn-ghost" :style="{ width: '22px', height: '22px' }" title="删除" @click="removeRule(a.id)">
              <Icon name="x" :size="11" />
            </button>
          </div>
        </div>

        <div :style="{ padding: '10px 14px', borderTop: `1px solid ${A2.borderHair}`, background: '#FBFBF9' }">
          <div :style="{ display: 'flex', alignItems: 'center', gap: '6px' }">
            <select v-model="newRule.type" class="alert-select">
              <option v-for="t in ruleTypes" :key="t.value" :value="t.value">{{ t.label }}</option>
            </select>
            <input v-model="newRule.threshold" type="number" step="any"
                   :placeholder="currentType?.placeholder"
                   class="alert-input" />
            <span :style="{ fontSize: '11px', color: A2.textMuted, minWidth: '14px' }">{{ currentType?.unit }}</span>
            <button class="btn-primary" :style="{ padding: '6px 12px', fontSize: '11px' }" @click="add">添加</button>
          </div>
          <div :style="{ marginTop: '6px', fontSize: '10.5px', color: A2.textDim, lineHeight: 1.45 }">
            提示：累计涨/跌幅以"加入自选时的价格"<span v-if="item.refPrice" :style="{ fontFamily: 'IBM Plex Mono, monospace' }"> ({{ item.refPrice.toFixed(2) }})</span> 为基准
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.alert-editor {
  position: relative;
  display: inline-block;
}
.alert-pop {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  width: 360px;
  border-radius: 10px;
  z-index: 40;
  overflow: hidden;
}
.alert-select, .alert-input {
  font-family: inherit;
  font-size: 11.5px;
  padding: 6px 8px;
  border: 1px solid rgba(14,14,12,0.10);
  border-radius: 6px;
  background: #fff;
  color: #111110;
  outline: none;
}
.alert-select { flex: 1; }
.alert-input { width: 78px; font-family: 'IBM Plex Mono', monospace; }
.alert-input:focus, .alert-select:focus { border-color: #2456D8; }
</style>
