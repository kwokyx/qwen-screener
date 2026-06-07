<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NAvatar,
  NBadge,
  NButton,
  NDropdown,
  NInput,
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NMenu,
  NSpace,
} from 'naive-ui'
import Icon from './Icon.vue'
import DataFreshness from './DataFreshness.vue'
import NotificationsPanel from './NotificationsPanel.vue'
import { useAuthStore } from '../stores/auth'
import { useNotificationsStore } from '../stores/notifications'
import * as stockApi from '../api/stock'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const notif = useNotificationsStore()

const menuOptions = [
  { label: '行情', key: 'dashboard' },
  { label: 'AI选股', key: 'chat' },
  { label: '结果', key: 'results' },
  { label: '自选', key: 'portfolio' },
  { label: '策略', key: 'strategy' },
]

const activeKey = computed(() => {
  return route.name || 'dashboard'
})
const isLoggedIn = computed(() => Boolean(auth.token))
const username = computed(() => auth.user?.username || '已登录')
const userInitial = computed(() => username.value.charAt(0).toUpperCase())
const userMenuOptions = computed(() => [
  { key: 'user', label: username.value, disabled: true },
  { key: 'logout', label: '退出登录' },
])

function handleMenuSelect(key) {
  router.push({ name: key })
}

const searchQuery = ref('')
const bellOpen = ref(false)
const searchItems = ref([])
const searchOpen = ref(false)
const searchLoading = ref(false)
const searchCursor = ref(0)
let searchDebounce = null
let searchSeq = 0

const directCode = computed(() => normalizeStockCode(searchQuery.value))
const showSearchPanel = computed(() => searchOpen.value && Boolean(searchQuery.value.trim()))

function normalizeStockCode(value) {
  const q = String(value || '').trim().toUpperCase()
  const full = q.match(/^([0-9]{6})\\.(SH|SZ|BJ)$/)
  if (full) return `${full[1]}.${full[2]}`
  if (!/^[0-9]{6}$/.test(q)) return ''
  if (q.startsWith('6') || q.startsWith('9')) return `${q}.SH`
  if (q.startsWith('0') || q.startsWith('2') || q.startsWith('3')) return `${q}.SZ`
  if (q.startsWith('4') || q.startsWith('8')) return `${q}.BJ`
  return ''
}

async function runSearch(q) {
  const text = q.trim()
  if (!text) {
    searchItems.value = []
    return []
  }
  const seq = ++searchSeq
  searchLoading.value = true
  try {
    const data = await stockApi.search(text, 8)
    if (seq !== searchSeq) return searchItems.value
    const rows = Array.isArray(data) ? data : (data.items || [])
    searchItems.value = rows
    searchCursor.value = 0
    return rows
  } catch {
    if (seq === searchSeq) searchItems.value = []
    return []
  } finally {
    if (seq === searchSeq) searchLoading.value = false
  }
}

watch(searchQuery, (value) => {
  searchCursor.value = 0
  if (searchDebounce) clearTimeout(searchDebounce)
  const q = value.trim()
  if (!q) {
    searchItems.value = []
    searchLoading.value = false
    return
  }
  searchDebounce = setTimeout(() => runSearch(q), 180)
})

function pickStock(stock) {
  if (!stock?.code) return
  searchQuery.value = ''
  searchItems.value = []
  searchOpen.value = false
  router.push(`/detail/${stock.code}`)
}

async function handleSearch() {
  const q = searchQuery.value.trim()
  if (!q) return
  if (directCode.value) {
    openDirectCode()
    return
  }
  if (searchItems.value.length) {
    pickStock(searchItems.value[Math.max(0, searchCursor.value)] || searchItems.value[0])
    return
  }
  const rows = await runSearch(q)
  if (rows.length) {
    pickStock(rows[0])
  }
}

function onSearchKeydown(e) {
  if (e.key === 'Enter') {
    e.preventDefault()
    void handleSearch()
    return
  }
  if (!showSearchPanel.value) return
  if (!searchItems.value.length) {
    if (e.key === 'Escape') searchOpen.value = false
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    searchCursor.value = Math.min(searchItems.value.length - 1, searchCursor.value + 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    searchCursor.value = Math.max(0, searchCursor.value - 1)
  } else if (e.key === 'Escape') {
    searchOpen.value = false
  }
}

function openDirectCode() {
  if (!directCode.value) return
  const code = directCode.value
  searchQuery.value = ''
  searchOpen.value = false
  router.push(`/detail/${code}`)
}

function onDocMouseDown(e) {
  if (!e.target.closest('[data-shell-search]')) searchOpen.value = false
}

document.addEventListener('mousedown', onDocMouseDown)
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocMouseDown)
  if (searchDebounce) clearTimeout(searchDebounce)
})

function goStockSearch() {
  searchOpen.value = true
  const q = searchQuery.value.trim()
  if (q && !searchItems.value.length) {
    runSearch(q)
  }
}

function goLogin(mode = 'login') {
  const query = { redirect: route.fullPath }
  if (mode === 'register') query.mode = 'register'
  router.push({ name: 'login', query })
}

function handleUserMenu(key) {
  if (key !== 'logout') return
  auth.logout()
  router.push('/dashboard')
}
</script>

<template>
  <n-layout class="app-shell">
    <n-layout-header class="top-nav" bordered>
      <div class="top-nav-inner">
        <div class="nav-brand" @click="router.push('/dashboard')">
          <span class="brand-icon">QS</span>
          <span>
            <span class="brand-text">Qwen Stock</span>
            <span class="brand-sub">A 股筛选工作台</span>
          </span>
        </div>

        <div class="nav-menu-wrap">
          <n-menu
            mode="horizontal"
            :value="activeKey"
            :options="menuOptions"
            @update:value="handleMenuSelect"
          />
        </div>

        <div class="nav-actions">
          <n-space align="center" size="small">
            <DataFreshness />
            <div class="nav-search-wrap" data-shell-search>
              <n-input
                class="nav-search"
                v-model:value="searchQuery"
                placeholder="搜索代码 / 名称"
                size="small"
                clearable
                @focus="goStockSearch"
                @keydown="onSearchKeydown"
              />
              <div v-if="showSearchPanel" class="nav-search-panel">
                <div v-if="searchLoading" class="search-state">搜索中...</div>
                <template v-else-if="searchItems.length">
                  <button
                    v-for="(item, idx) in searchItems"
                    :key="item.code"
                    type="button"
                    class="search-item"
                    :class="{ active: idx === searchCursor }"
                    @mouseenter="searchCursor = idx"
                    @click="pickStock(item)"
                  >
                    <span>
                      <strong>{{ item.name || item.code }}</strong>
                      <small>{{ item.code }}</small>
                    </span>
                    <em>{{ item.industry || item.market || '股票' }}</em>
                  </button>
                </template>
                <button v-else-if="directCode" type="button" class="search-item active" @click="openDirectCode">
                  <span>
                    <strong>打开 {{ directCode }}</strong>
                    <small>直接进入股票详情</small>
                  </span>
                </button>
                <div v-else class="search-state">未找到匹配股票</div>
              </div>
            </div>
            <n-button size="small" @click="handleSearch">
              <template #icon><Icon name="search" :size="12" /></template>
            </n-button>
            <n-badge :value="notif.unreadCount" :max="99" :show="notif.unreadCount > 0">
              <n-button quaternary circle size="small" title="通知" data-bell @click="bellOpen = !bellOpen">
                <template #icon><Icon name="bell" :size="15" /></template>
              </n-button>
            </n-badge>
            <template v-if="isLoggedIn">
              <n-dropdown trigger="click" :options="userMenuOptions" @select="handleUserMenu">
                <button class="user-chip" type="button" :title="username">
                  <n-avatar size="small" class="user-avatar">{{ userInitial }}</n-avatar>
                  <span class="user-name">{{ username }}</span>
                </button>
              </n-dropdown>
            </template>
            <template v-else>
              <n-button size="small" quaternary class="auth-link" @click="goLogin('login')">登录</n-button>
              <n-button size="small" type="primary" class="auth-primary" @click="goLogin('register')">注册</n-button>
            </template>
          </n-space>
        </div>
      </div>
    </n-layout-header>

    <NotificationsPanel :open="bellOpen" @close="bellOpen = false" />

    <n-layout-content class="app-content">
      <div class="content-container">
        <slot />
      </div>
    </n-layout-content>
  </n-layout>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
}

.top-nav {
  height: 60px;
  background: #FFFFFF;
  display: flex;
  align-items: center;
  padding: 0;
  border-bottom: 1px solid #EDEDED;
}

.top-nav-inner {
  width: 100%;
  max-width: 1540px;
  margin: 0 auto;
  padding: 0 30px;
  display: flex;
  align-items: center;
  height: 100%;
  gap: 28px;
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  flex-shrink: 0;
  user-select: none;
}

.brand-icon {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: 4px;
  color: #ffffff;
  background: #111111;
  font-weight: 800;
  font-size: 11px;
  letter-spacing: 0.3px;
}

.brand-text {
  display: block;
  font-weight: 700;
  font-size: 16px;
  color: #111827;
  white-space: nowrap;
  line-height: 1.1;
}

.brand-sub {
  display: none;
}

.nav-menu-wrap {
  flex: 1;
  display: flex;
  justify-content: flex-start;
}

.nav-menu-wrap :deep(.n-menu) {
  --n-item-height: 60px;
  background: transparent;
  --n-item-text-color: #52525B;
  --n-item-text-color-hover: #111111;
  --n-item-text-color-active: #111111;
  --n-item-color-active: transparent;
  --n-item-color-active-hover: transparent;
  --n-item-color-hover: transparent;
}

.nav-menu-wrap :deep(.n-menu-item-content) {
  padding: 0 13px;
  font-size: 14px;
  font-weight: 600;
}

.nav-menu-wrap :deep(.n-menu-item-content-header) {
  color: #52525B;
}

.nav-menu-wrap :deep(.n-menu-item-content--selected .n-menu-item-content-header),
.nav-menu-wrap :deep(.n-menu-item-content:hover .n-menu-item-content-header) {
  color: #111111;
}

.nav-menu-wrap :deep(.n-menu-item-content--selected) {
  position: relative;
}

.nav-menu-wrap :deep(.n-menu-item-content--selected::after) {
  content: '';
  position: absolute;
  left: 13px;
  right: 13px;
  bottom: 0;
  height: 2px;
  border-radius: 2px;
  background: #111111;
}

.nav-actions {
  flex-shrink: 0;
}

.nav-search {
  width: 260px;
}

.nav-search-wrap {
  position: relative;
}

.nav-search-panel {
  position: absolute;
  top: 38px;
  right: 0;
  width: 320px;
  max-height: 320px;
  overflow: auto;
  background: #FFFFFF;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  box-shadow: 0 14px 34px rgba(15, 23, 42, 0.12);
  z-index: 80;
  padding: 6px;
}

.search-item {
  width: 100%;
  border: none;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 9px;
  border-radius: 6px;
  text-align: left;
  cursor: pointer;
}

.search-item:hover,
.search-item.active {
  background: #F4F4F5;
}

.search-item strong {
  display: block;
  color: #111111;
  font-size: 13px;
  font-weight: 700;
}

.search-item small {
  display: block;
  margin-top: 1px;
  color: #71717A;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
}

.search-item em {
  flex-shrink: 0;
  max-width: 92px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #71717A;
  font-size: 11px;
  font-style: normal;
}

.search-state {
  padding: 18px 12px;
  color: #71717A;
  font-size: 12px;
  text-align: center;
}

.nav-actions :deep(.n-input) {
  background: #F5F5F5;
  border-color: transparent;
  border-radius: 6px;
}

.nav-actions :deep(.n-input__input-el) {
  color: #111827;
}

.nav-actions :deep(.n-input__placeholder) {
  color: #94A3B8;
}

.nav-actions :deep(.n-button) {
  background: #FFFFFF;
  color: #111111;
  border-color: #D8D8D8;
  border-radius: 6px;
}

.nav-actions :deep(.auth-link.n-button) {
  border-color: transparent;
}

.nav-actions :deep(.auth-primary.n-button) {
  background: #111111;
  color: #FFFFFF;
  border-color: #111111;
}

.user-chip {
  height: 32px;
  border: 1px solid #D8D8D8;
  background: #FFFFFF;
  border-radius: 6px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 0 8px 0 5px;
  cursor: pointer;
  color: #111111;
}

.user-chip:hover {
  background: #F7F7F7;
}

.user-avatar {
  background: #111111;
  color: #FFFFFF;
  font-weight: 700;
}

.user-name {
  max-width: 96px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 600;
}

.app-content {
  background: #FFFFFF;
  min-height: calc(100vh - 60px);
}

.content-container {
  max-width: 1540px;
  margin: 0 auto;
  padding: 20px 30px 34px;
}

@media (max-width: 1200px) {
  .top-nav-inner {
    padding: 0 16px;
    gap: 12px;
  }

  .nav-menu-wrap :deep(.n-menu-item-content) {
    padding: 0 8px;
    font-size: 13px;
  }

  .nav-search {
    width: 180px;
  }

  .user-name {
    max-width: 58px;
  }
}

@media (max-width: 768px) {
  .nav-menu-wrap {
    display: none;
  }

  .top-nav-inner {
    padding: 0 12px;
    gap: 8px;
  }

  .brand-text,
  .brand-sub {
    display: none;
  }

  .nav-search {
    width: 132px;
  }

  .content-container {
    padding: 12px;
  }
}
</style>
