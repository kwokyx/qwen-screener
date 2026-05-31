<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton,
  NInput,
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NMenu,
  NSpace,
  NTag,
} from 'naive-ui'
import Icon from './Icon.vue'

const route = useRoute()
const router = useRouter()

const menuOptions = [
  { label: '行情', key: 'dashboard' },
  { label: '智能筛选', key: 'chat' },
  { label: '结果', key: 'results' },
  { label: '自选', key: 'portfolio' },
  { label: '策略', key: 'strategy' },
]

const activeKey = computed(() => {
  return route.name || 'dashboard'
})

function handleMenuSelect(key) {
  router.push({ name: key })
}

const searchQuery = ref('')

function handleSearch() {
  const q = searchQuery.value.trim()
  if (q) {
    router.push({ name: 'detail', params: { code: q } })
    searchQuery.value = ''
  }
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
            <n-tag size="small" :bordered="false" class="data-tag">
              日线数据
            </n-tag>
            <n-input
              class="nav-search"
              v-model:value="searchQuery"
              placeholder="搜索代码 / 名称"
              size="small"
              clearable
              @keyup.enter="handleSearch"
            />
            <n-button size="small" @click="handleSearch">
              <template #icon><Icon name="search" :size="12" /></template>
            </n-button>
          </n-space>
        </div>
      </div>
    </n-layout-header>

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

.data-tag {
  color: #111111;
  background: #F5F5F5;
  font-weight: 600;
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

.app-content {
  background: #FFFFFF;
  min-height: calc(100vh - 60px);
}

.content-container {
  max-width: 1540px;
  margin: 0 auto;
  padding: 20px 30px 34px;
}

@media (max-width: 768px) {
  .nav-menu-wrap {
    display: none;
  }

  .top-nav-inner {
    padding: 0 12px;
    gap: 8px;
  }

  .brand-sub,
  .data-tag {
    display: none;
  }

  .nav-search {
    width: 150px;
  }

  .content-container {
    padding: 12px;
  }
}
</style>
