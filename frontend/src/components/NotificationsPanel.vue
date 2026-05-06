<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useNotificationsStore } from '../stores/notifications'
import { A2 } from '../shared/theme.js'
import Icon from './Icon.vue'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['close'])

const notif = useNotificationsStore()
const router = useRouter()
const permState = ref(typeof Notification !== 'undefined' ? Notification.permission : 'unsupported')

const items = computed(() => notif.items)

function fmtTime(ts) {
  const d = new Date(ts * 1000)
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  if (sameDay) return `${hh}:${mm}`
  return `${d.getMonth() + 1}-${d.getDate()} ${hh}:${mm}`
}

function toneColor(t) {
  return { up: A2.up, down: A2.down, amber: A2.amber, qwen: A2.qwen }[t] || A2.textSub
}

async function requestPerm() {
  permState.value = await notif.ensurePermission()
}

function openItem(n) {
  if (n.code) router.push(`/detail/${n.code}`)
  notif.markRead(n.id)
  emit('close')
}

// click-outside to close
const panelRef = ref(null)
function onDocClick(e) {
  if (!props.open) return
  if (panelRef.value && !panelRef.value.contains(e.target) && !e.target.closest('[data-bell]')) {
    emit('close')
  }
}
onMounted(() => document.addEventListener('mousedown', onDocClick))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocClick))
</script>

<template>
  <Transition name="page-fade">
    <div v-if="open" ref="panelRef"
         :style="{ position: 'absolute', top: '46px', right: '12px', width: '360px', maxHeight: '70vh', background: A2.surface, borderRadius: '10px', boxShadow: A2.shadowLg, border: `1px solid ${A2.borderHair}`, zIndex: 50, display: 'flex', flexDirection: 'column', overflow: 'hidden' }">

      <div :style="{ padding: '12px 14px', borderBottom: `1px solid ${A2.borderHair}`, display: 'flex', alignItems: 'center', gap: '8px' }">
        <Icon name="bell" :size="14" :color="A2.text" />
        <div :style="{ fontSize: '13px', fontWeight: 700 }">通知中心</div>
        <span v-if="notif.unreadCount" :style="{ fontSize: '10px', padding: '1px 7px', background: A2.upSoft, color: A2.up, borderRadius: '999px', fontWeight: 700, fontFamily: 'IBM Plex Mono, monospace' }">{{ notif.unreadCount }} 新</span>
        <div style="flex:1" />
        <button v-if="items.length" class="btn-ghost" :style="{ width: 'auto', padding: '0 8px', fontSize: '11px', color: A2.textMuted }" @click="notif.markAllRead">全部已读</button>
      </div>

      <!-- 桌面通知权限 -->
      <div v-if="permState === 'default'" :style="{ padding: '10px 14px', borderBottom: `1px solid ${A2.borderHair}`, fontSize: '11.5px', color: A2.textSub, background: A2.qwenGradSoft, display: 'flex', alignItems: 'center', gap: '8px' }">
        <Icon name="alert" :size="13" :color="A2.qwen" />
        <span style="flex:1">开启浏览器通知，离开页面也能收到提醒</span>
        <button class="btn-primary" :style="{ padding: '4px 10px', fontSize: '11px' }" @click="requestPerm">开启</button>
      </div>
      <div v-else-if="permState === 'denied'" :style="{ padding: '8px 14px', borderBottom: `1px solid ${A2.borderHair}`, fontSize: '11px', color: A2.textMuted, background: A2.bgDeep }">
        浏览器通知已被禁用 · 仅站内提醒
      </div>

      <div :style="{ overflow: 'auto', flex: 1 }">
        <div v-if="!items.length" :style="{ padding: '40px 16px', textAlign: 'center', color: A2.textMuted, fontSize: '12px' }">
          <div :style="{ fontSize: '24px', marginBottom: '6px' }">🔔</div>
          暂无通知
          <div :style="{ fontSize: '11px', color: A2.textDim, marginTop: '4px' }">在自选股上加预警即可在此收到提醒</div>
        </div>

        <div v-for="n in items" :key="n.id" @click="openItem(n)"
             class="notif-item"
             :style="{ padding: '10px 14px', borderTop: `1px solid ${A2.borderHair}`, display: 'flex', gap: '8px', cursor: 'pointer', background: n.read ? 'transparent' : A2.qwenGradSoft }">
          <div :style="{ width: '3px', alignSelf: 'stretch', background: toneColor(n.tone), borderRadius: '2px', flexShrink: 0 }" />
          <div style="flex:1; min-width: 0">
            <div :style="{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '3px' }">
              <span :style="{ fontSize: '9px', padding: '1px 6px', background: toneColor(n.tone) + '18', color: toneColor(n.tone), borderRadius: '3px', fontWeight: 700, whiteSpace: 'nowrap' }">{{ n.tag }}</span>
              <span :style="{ fontSize: '12px', fontWeight: 700, color: A2.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }">{{ n.stock }}</span>
              <span :style="{ marginLeft: 'auto', fontSize: '10px', color: A2.textDim, fontFamily: 'IBM Plex Mono, monospace', flexShrink: 0 }">{{ fmtTime(n.ts) }}</span>
            </div>
            <div :style="{ fontSize: '11.5px', color: A2.textSub, lineHeight: 1.45 }">{{ n.desc }}</div>
          </div>
        </div>
      </div>

      <div v-if="items.length" :style="{ padding: '8px 14px', borderTop: `1px solid ${A2.borderHair}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px', background: '#FBFBF9' }">
        <span :style="{ color: A2.textMuted }">最近 {{ items.length }} 条</span>
        <button class="btn-ghost" :style="{ width: 'auto', padding: '4px 8px', fontSize: '11px', color: A2.textMuted }" @click="notif.clear">清空</button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.notif-item:hover { background: rgba(36, 86, 216, 0.06) !important; }
</style>
