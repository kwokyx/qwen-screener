<script setup>
import { computed, ref } from 'vue'
import {
  NButton,
  NCheckbox,
  NDivider,
  NEmpty,
  NInputNumber,
  NPopover,
  NSelect,
  NSpace,
  NTag,
} from 'naive-ui'
import { useWatchlistStore } from '../stores/watchlist'
import { useNotificationsStore } from '../stores/notifications'
import { toast } from '../stores/toast'
import { Preview } from '../shared/theme.js'

const props = defineProps({
  code: { type: String, required: true },
})

const wl = useWatchlistStore()
const notif = useNotificationsStore()

const item = computed(() => wl.get(props.code))
const open = ref(false)
const newRule = ref({ type: 'pct_up', threshold: 20 })

const ruleTypes = [
  { value: 'pct_up', label: '累计涨幅 >=', unit: '%', placeholder: '20' },
  { value: 'pct_down', label: '累计跌幅 >=', unit: '%', placeholder: '15' },
  { value: 'price_gt', label: '现价突破 >=', unit: '元', placeholder: '100' },
  { value: 'price_lt', label: '现价跌破 <=', unit: '元', placeholder: '50' },
  { value: 'day_pct', label: '日内涨跌 >=', unit: '%', placeholder: '5' },
]

const currentType = computed(() => ruleTypes.find((t) => t.value === newRule.value.type))
const ruleOptions = computed(() => ruleTypes.map(({ value, label }) => ({ value, label })))

function add() {
  const threshold = Number(newRule.value.threshold)
  if (!Number.isFinite(threshold)) {
    toast.warning('请输入有效阈值')
    return
  }
  wl.addAlert(props.code, {
    type: newRule.value.type,
    threshold,
  })
  toast.success('预警已添加')
  newRule.value.threshold = null
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
  <div v-if="item" class="alert-editor" @click.stop>
    <NPopover v-model:show="open" trigger="click" placement="bottom-end" :width="380" :show-arrow="false">
      <template #trigger>
        <NButton size="small" secondary class="alert-trigger">
          <NSpace align="center" :size="6">
            <span>预警</span>
            <NTag v-if="item.alerts.length" size="small" :bordered="false" type="success" class="alert-count">
              {{ item.alerts.length }}
            </NTag>
          </NSpace>
        </NButton>
      </template>

      <div class="alert-pop">
        <div class="pop-head">
          <div>
            <div class="pop-title">预警规则</div>
            <div class="pop-code mono">{{ item.code }}</div>
          </div>
          <NButton size="tiny" secondary @click="fireTest">测试</NButton>
        </div>

        <NDivider class="compact-divider" />

        <NEmpty v-if="!item.alerts.length" description="还没有规则" class="empty-rule">
          <template #extra>
            <span class="hint">在下方添加一条</span>
          </template>
        </NEmpty>

        <NSpace v-else vertical :size="6">
          <div v-for="a in item.alerts" :key="a.id" class="rule-row">
            <NCheckbox :checked="a.enabled" @update:checked="v => wl.setAlertEnabled(item.code, a.id, v)" />
            <span class="rule-text">{{ fmtRule(a) }}</span>
            <NTag v-if="a.lastTriggered" size="small" round :bordered="false">已触发</NTag>
            <NButton size="tiny" quaternary @click="removeRule(a.id)">删除</NButton>
          </div>
        </NSpace>

        <NDivider class="compact-divider" />

        <NSpace align="center" :size="8" class="rule-form">
          <NSelect
            v-model:value="newRule.type"
            :options="ruleOptions"
            size="small"
            class="rule-select"
          />
          <NInputNumber
            v-model:value="newRule.threshold"
            size="small"
            :show-button="false"
            :placeholder="currentType?.placeholder"
            class="rule-input"
          />
          <span class="unit">{{ currentType?.unit }}</span>
          <NButton size="small" type="primary" @click="add">添加</NButton>
        </NSpace>

        <div class="tip">
          提示：累计涨/跌幅以“加入自选时的价格”
          <span v-if="item.refPrice" class="mono">({{ item.refPrice.toFixed(2) }})</span>
          为基准
        </div>
      </div>
    </NPopover>
  </div>
</template>

<style scoped>
.alert-editor {
  display: inline-block;
}
.alert-trigger {
  border-radius: 6px;
  font-weight: 650;
}
.alert-count {
  border-radius: 4px;
}
.alert-pop {
  padding: 4px;
}
.pop-head,
.rule-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.pop-head {
  justify-content: space-between;
}
.pop-title {
  color: #111111;
  font-size: 13px;
  font-weight: 800;
}
.pop-code,
.hint,
.unit,
.tip {
  color: #71717a;
}
.pop-code {
  margin-top: 2px;
  font-size: 11px;
}
.compact-divider {
  margin: 10px 0;
}
.empty-rule {
  padding: 12px 0;
}
.rule-row {
  min-height: 34px;
  padding: 6px 8px;
  border-radius: 8px;
  background: #f7f7f7;
}
.rule-text {
  flex: 1;
  color: #111111;
  font-size: 12px;
}
.rule-form {
  width: 100%;
}
.rule-select {
  flex: 1;
  min-width: 148px;
}
.rule-input {
  width: 86px;
}
.unit {
  min-width: 18px;
  font-size: 12px;
}
.tip {
  margin-top: 8px;
  font-size: 11px;
  line-height: 1.5;
}
.mono {
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
</style>
