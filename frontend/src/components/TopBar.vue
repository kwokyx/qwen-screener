<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { A2 } from '../shared/theme.js'
import { useNotificationsStore } from '../stores/notifications'
import { useAuthStore } from '../stores/auth'
import Icon from './Icon.vue'
import NotificationsPanel from './NotificationsPanel.vue'
import CommandPalette from './CommandPalette.vue'
import DataFreshness from './DataFreshness.vue'

const route = useRoute()
const router = useRouter()
const notif = useNotificationsStore()
const auth = useAuthStore()

const userInitial = computed(() => {
  const u = auth.user?.username
  return u ? u.charAt(0).toUpperCase() : '?'
})
const isLoggedIn = computed(() => !!auth.token)
const userMenuOpen = ref(false)

function logout() {
  auth.logout()
  userMenuOpen.value = false
  router.push('/login')
}

function gotoLogin() {
  userMenuOpen.value = false
  router.push('/login')
}

function onDocClickAvatar(e) {
  if (!userMenuOpen.value) return
  if (!e.target.closest('[data-user-menu]')) userMenuOpen.value = false
}

const tabs = [
  { id: 'dashboard', label: '行情' },
  { id: 'chat', label: '千问筛选' },
  { id: 'results', label: '因子' },
  { id: 'detail', label: '详情' },
  { id: 'portfolio', label: '自选监控' },
  { id: 'strategy', label: '策略' },
]

const tabRefs = ref([])
const indicator = ref({ left: 0, width: 0, visible: false })
const bellOpen = ref(false)
const paletteOpen = ref(false)

function navTo(id) {
  if (id === 'detail') {
    if (route.name !== 'detail') router.push('/detail/600519.SH')
  } else {
    router.push('/' + id)
  }
}

function updateIndicator() {
  const idx = tabs.findIndex(t => t.id === route.name)
  if (idx < 0) {
    indicator.value = { left: 0, width: 0, visible: false }
    return
  }
  const el = tabRefs.value[idx]
  if (!el || !el.offsetParent) return
  indicator.value = {
    left: el.offsetLeft + 12,
    width: el.offsetWidth - 24,
    visible: true,
  }
}

function onKey(e) {
  // ⌘K / Ctrl+K → command palette
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    paletteOpen.value = !paletteOpen.value
  }
}

onMounted(async () => {
  await nextTick()
  updateIndicator()
  window.addEventListener('keydown', onKey)
  document.addEventListener('mousedown', onDocClickAvatar)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  document.removeEventListener('mousedown', onDocClickAvatar)
})
watch(() => route.name, async () => {
  await nextTick()
  updateIndicator()
})
</script>

<template>
  <div :style="{ position: 'relative' }">
    <div :style="{ display: 'flex', alignItems: 'center', height: '46px', background: A2.surface, boxShadow: '0 1px 0 ' + A2.borderHair, padding: '0 16px', flexShrink: 0 }">
      <div :style="{ display: 'flex', alignItems: 'center', gap: '8px', marginRight: '22px' }">
        <img src="/logo.png" alt="logo"
             :style="{ width: '36px', height: '36px', objectFit: 'contain', filter: 'drop-shadow(0 1px 2px rgba(36,86,216,0.25))' }" />
        <div :style="{ fontWeight: 700, fontSize: '13px', letterSpacing: '-0.2px' }">
          Qwen
          <span :style="{ color: A2.textMuted, fontWeight: 500, fontSize: '10px', letterSpacing: '1.2px', marginLeft: '2px' }">TERMINAL</span>
        </div>
      </div>
      <div class="topbar-tabs" :style="{ position: 'relative', display: 'flex', gap: 0 }">
        <div v-for="(t, i) in tabs" :key="t.id"
             :ref="el => tabRefs[i] = el"
             class="tab-link"
             :class="{ active: route.name === t.id }"
             @click="navTo(t.id)">
          {{ t.label }}
        </div>
        <div v-if="indicator.visible" class="tab-indicator"
             :style="{ left: indicator.left + 'px', width: indicator.width + 'px' }" />
      </div>
      <div style="flex:1" />
      <div :style="{ display: 'flex', gap: '8px', alignItems: 'center' }">
        <DataFreshness />
        <button class="btn-ghost cmdk-btn" title="搜索 ⌘K" @click="paletteOpen = true">
          <Icon name="search" :size="15" />
          <span class="kbd">⌘K</span>
        </button>
        <button class="btn-ghost" title="通知" data-bell :style="{ position: 'relative' }" @click="bellOpen = !bellOpen">
          <Icon name="bell" :size="15" />
          <span v-if="notif.unreadCount > 0" :style="{ position: 'absolute', top: '4px', right: '3px', minWidth: '14px', height: '14px', padding: '0 3px', background: A2.up, color: '#fff', borderRadius: '7px', border: '1.5px solid #fff', fontSize: '9px', fontWeight: 700, display: 'grid', placeItems: 'center', fontFamily: 'IBM Plex Mono, monospace' }">{{ notif.unreadCount > 99 ? '99+' : notif.unreadCount }}</span>
        </button>
        <div data-user-menu :style="{ position: 'relative', marginLeft: '4px' }">
          <button @click="userMenuOpen = !userMenuOpen"
                  :title="isLoggedIn ? auth.user?.username : '点击登录'"
                  :style="{ width: '26px', height: '26px', borderRadius: '50%', background: isLoggedIn ? A2.qwenGrad : '#B8B4A8', color: '#fff', display: 'grid', placeItems: 'center', fontSize: '11px', fontWeight: 700, border: 'none', cursor: 'pointer', padding: 0 }">
            {{ userInitial }}
          </button>
          <Transition name="page-fade">
            <div v-if="userMenuOpen"
                 :style="{ position: 'absolute', top: '34px', right: 0, minWidth: '180px', background: A2.surface, borderRadius: '10px', boxShadow: A2.shadowLg, border: `1px solid ${A2.borderHair}`, zIndex: 50, overflow: 'hidden' }">
              <div v-if="isLoggedIn" :style="{ padding: '10px 14px', borderBottom: `1px solid ${A2.borderHair}` }">
                <div :style="{ fontSize: '12px', fontWeight: 700 }">{{ auth.user?.username }}</div>
                <div :style="{ fontSize: '10px', color: A2.textMuted, marginTop: '2px', fontFamily: 'IBM Plex Mono, monospace' }">{{ auth.user?.email || '已登录' }}</div>
              </div>
              <div v-else :style="{ padding: '10px 14px', fontSize: '11.5px', color: A2.textMuted, borderBottom: `1px solid ${A2.borderHair}` }">
                未登录
              </div>
              <button v-if="isLoggedIn" @click="logout"
                      :style="{ width: '100%', padding: '10px 14px', background: 'transparent', border: 'none', textAlign: 'left', fontSize: '12px', color: A2.text, cursor: 'pointer' }">
                退出登录
              </button>
              <button v-else @click="gotoLogin"
                      :style="{ width: '100%', padding: '10px 14px', background: 'transparent', border: 'none', textAlign: 'left', fontSize: '12px', color: A2.qwen, fontWeight: 600, cursor: 'pointer' }">
                登录 / 注册
              </button>
            </div>
          </Transition>
        </div>
      </div>
    </div>

    <NotificationsPanel :open="bellOpen" @close="bellOpen = false" />
    <CommandPalette :open="paletteOpen" @close="paletteOpen = false" />
  </div>
</template>

<style scoped>
.cmdk-btn {
  width: auto !important;
  padding: 0 8px !important;
  gap: 5px;
}
.kbd {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9.5px;
  padding: 1px 4px;
  background: rgba(14,14,12,0.06);
  border-radius: 3px;
  color: #7A776F;
}
.cmdk-btn:hover .kbd { background: rgba(14,14,12,0.12); }
</style>
