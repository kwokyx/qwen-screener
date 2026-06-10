<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { A2 } from '../shared/theme.js'
import { useNotificationsStore } from '../stores/notifications'
import { useAuthStore } from '../stores/auth'
import Icon from './Icon.vue'
import NotificationsPanel from './NotificationsPanel.vue'
import CommandPalette from './CommandPalette.vue'
import DataFreshness from './DataFreshness.vue'
import { NAvatar, NBadge, NButton, NDropdown, NLayoutHeader, NMenu, NSpace } from 'naive-ui'

const route = useRoute()
const router = useRouter()
const notif = useNotificationsStore()
const auth = useAuthStore()

const userInitial = computed(() => {
  const u = auth.user?.username
  return u ? u.charAt(0).toUpperCase() : '?'
})
const isLoggedIn = computed(() => !!auth.token)

const tabs = [
  { id: 'dashboard', label: '行情' },
  { id: 'chat', label: '千问筛选' },
  { id: 'detail', label: '详情' },
  { id: 'portfolio', label: '自选监控' },
  { id: 'strategy', label: '策略' },
]
const menuOptions = tabs.map((t) => ({ key: t.id, label: t.label }))
const bellOpen = ref(false)
const paletteOpen = ref(false)

const userMenuOptions = computed(() => {
  if (isLoggedIn.value) {
    return [
      { key: 'profile', label: auth.user?.username || '已登录', disabled: true },
      { key: 'logout', label: '退出登录' },
    ]
  }
  return [{ key: 'login', label: '登录 / 注册' }]
})

function navTo(id) {
  if (id === 'detail') {
    if (route.name !== 'detail') router.push('/detail/600519.SH')
  } else {
    router.push('/' + id)
  }
}

function logout() {
  auth.logout()
  router.push('/dashboard')
}

function handleUserMenu(key) {
  if (key === 'logout') logout()
  if (key === 'login') router.push({ name: 'login', query: { redirect: route.fullPath } })
}

function onKey(e) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    paletteOpen.value = !paletteOpen.value
  }
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div :style="{ position: 'relative' }">
    <n-layout-header
      bordered
      class="topbar-header"
      :style="{ height: '46px', display: 'flex', alignItems: 'center', padding: '0 16px', background: '#fff' }"
    >
      <div class="brand" :style="{ display: 'flex', alignItems: 'center', gap: '8px', marginRight: '18px', flexShrink: 0 }">
        <img
          src="/logo.png"
          alt="logo"
          class="brand-logo"
          :style="{ width: '36px', height: '36px', objectFit: 'contain', filter: 'drop-shadow(0 1px 2px rgba(36, 86, 216, 0.25))' }"
        />
        <div class="brand-text" :style="{ fontWeight: 700, fontSize: '13px', letterSpacing: 0 }">
          Qwen
          <span :style="{ color: A2.textMuted, fontWeight: 500, fontSize: '10px', letterSpacing: '1.2px', marginLeft: '2px' }">TERMINAL</span>
        </div>
      </div>

      <n-menu
        class="topbar-menu"
        mode="horizontal"
        :value="route.name"
        :options="menuOptions"
        responsive
        :style="{ minWidth: '440px', '--n-item-height': '46px' }"
        @update:value="navTo"
      />

      <div style="flex: 1" />

      <n-space size="small" align="center" :wrap="false">
        <DataFreshness />
        <n-button quaternary size="small" title="搜索 ⌘K" @click="paletteOpen = true">
          <template #icon><Icon name="search" :size="15" /></template>
          <span class="kbd">⌘K</span>
        </n-button>
        <n-badge :value="notif.unreadCount" :max="99" :show="notif.unreadCount > 0">
          <n-button quaternary circle size="small" title="通知" data-bell @click="bellOpen = !bellOpen">
            <template #icon><Icon name="bell" :size="15" /></template>
          </n-button>
        </n-badge>
        <n-dropdown trigger="click" :options="userMenuOptions" @select="handleUserMenu">
          <n-avatar
            round
            size="small"
            :style="{ background: isLoggedIn ? A2.qwen : '#B8B4A8', cursor: 'pointer', fontWeight: 700 }"
            :title="isLoggedIn ? auth.user?.username : '点击登录'"
          >
            {{ userInitial }}
          </n-avatar>
        </n-dropdown>
      </n-space>
    </n-layout-header>

    <NotificationsPanel :open="bellOpen" @close="bellOpen = false" />
    <CommandPalette :open="paletteOpen" @close="paletteOpen = false" />
  </div>
</template>

<style scoped>
.topbar-header {
  height: 46px;
  display: flex;
  align-items: center;
  padding: 0 16px;
  background: #fff;
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 18px;
  flex-shrink: 0;
}
.brand-logo {
  width: 36px;
  height: 36px;
  object-fit: contain;
  filter: drop-shadow(0 1px 2px rgba(36, 86, 216, 0.25));
}
.brand-text {
  font-weight: 700;
  font-size: 13px;
  letter-spacing: 0;
}
.brand-text span {
  color: #7A776F;
  font-weight: 500;
  font-size: 10px;
  letter-spacing: 1.2px;
  margin-left: 2px;
}
.topbar-menu {
  min-width: 440px;
  --n-item-height: 46px;
}
.topbar-menu :deep(.n-menu-item-content) {
  padding: 0 14px;
}
.kbd {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9.5px;
  padding: 1px 4px;
  background: rgba(14,14,12,0.06);
  border-radius: 3px;
  color: #7A776F;
}
</style>
