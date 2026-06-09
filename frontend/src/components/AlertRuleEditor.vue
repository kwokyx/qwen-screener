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
import Icon from './Icon.vue'

const props = defineProps({
  code: { type: String, required: true },
  compact: { type: Boolean, default: false },
})

const wl = useWatchlistStore()
const notif = useNotificationsStore()

const item = computed(() => wl.get(props.code))
const alertCount = computed(() => item.value?.alerts?.length || 0)
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
        <button
          type="button"
          class="alert-trigger"
          :class="{ 'alert-trigger-compact': compact, 'has-alerts': alertCount, 'all-paused': alertCount && !item.alerts.some(a => a.enabled !== false) }"
          :title="alertCount ? `已设 ${alertCount} 条预警` : '设置预警'"
        >
          <span v-if="compact" class="alert-icon-content">
            <Icon name="bell" :size="14" :stroke="1.8" />
            <span v-if="alertCount" class="alert-count-dot">
              {{ alertCount > 9 ? '9+' : alertCount }}
            </span>
          </span>
          <span v-else class="alert-trigger-content">
            <span>预警</span>
            <span v-if="alertCount" class="alert-count-pill">
              {{ alertCount }}
            </span>
          </span>
        </button>
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
  appearance: none;
  border: 0;
  border-radius: 6px;
  height: 28px;
  min-width: 58px;
  padding: 0 8px;
  background: #f1f1f1;
  color: #3f3f46;
  font-weight: 650;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease, transform 0.15s ease;
}
.alert-trigger:hover {
  background: #e7e7e7;
  color: #111111;
}
.alert-trigger:active {
  transform: translateY(1px);
}
.alert-trigger-content {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: 100%;
  white-space: nowrap;
  line-height: 1;
}
.alert-trigger-compact {
  display: inline-grid;
  place-items: center;
  width: 32px;
  min-width: 32px;
  height: 32px;
  padding: 0;
  border-radius: 7px;
}
.alert-trigger-compact.has-alerts {
  color: #111111;
  background: #eeeeee;
}
.alert-trigger-compact.all-paused {
  color: #a1a1aa;
  background: #f3f3f3;
}
.alert-icon-content {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
}
.alert-count-dot {
  position: absolute;
  right: -8px;
  top: -8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 15px;
  height: 15px;
  padding: 0 3px;
  border-radius: 999px;
  background: #111111;
  color: #ffffff;
  font-size: 9px;
  font-weight: 800;
  line-height: 15px;
  box-shadow: 0 0 0 2px #eeeeee;
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
.alert-trigger-compact.all-paused .alert-count-dot {
  background: #a1a1aa;
  box-shadow: 0 0 0 2px #f3f3f3;
}
.alert-count-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 15px;
  height: 15px;
  padding: 0 4px;
  border-radius: 999px;
  background: #111111;
  color: #ffffff;
  font-size: 10px;
  font-weight: 800;
  line-height: 15px;
  font-family: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
.alert-trigger.all-paused .alert-count-pill {
  background: #a1a1aa;
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
