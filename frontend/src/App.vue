<script setup>
import { useRoute } from 'vue-router'
import { NConfigProvider, NDialogProvider, NMessageProvider, NNotificationProvider } from 'naive-ui'
import ErrorBoundary from './components/ErrorBoundary.vue'
import Toaster from './components/Toaster.vue'
import WatchlistDock from './components/WatchlistDock.vue'
import { useAuthStore } from './stores/auth'

const route = useRoute()
const auth = useAuthStore()

const naiveThemeOverrides = {
  common: {
    primaryColor: '#111111',
    primaryColorHover: '#000000',
    primaryColorPressed: '#27272A',
    primaryColorSuppl: '#111111',
    borderRadius: '6px',
    fontFamily: "'IBM Plex Sans', 'Noto Sans SC', -apple-system, BlinkMacSystemFont, sans-serif",
    fontFamilyMono: "'IBM Plex Mono', SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    textColor1: '#111111',
    textColor2: '#3F3F46',
    textColor3: '#71717A',
    borderColor: '#EDEDED',
    bodyColor: '#FFFFFF',
    cardColor: '#FFFFFF',
    tableColor: '#FFFFFF',
  },
  Button: {
    borderRadiusTiny: '4px',
    borderRadiusSmall: '5px',
    borderRadiusMedium: '6px',
  },
  Card: {
    borderRadius: '8px',
    color: '#FFFFFF',
    borderColor: '#EDEDED',
  },
  Tag: {
    borderRadius: '4px',
  },
  Input: {
    borderRadius: '6px',
  },
  Select: {
    peers: {
      InternalSelection: {
        borderRadius: '6px',
      },
    },
  },
  DataTable: {
    thColor: '#FFFFFF',
    thTextColor: '#71717A',
    tdColorHover: '#FAFAFA',
  },
  Layout: {
    siderColor: '#FFFFFF',
    headerColor: '#FFFFFF',
    contentColor: '#FFFFFF',
  },
}
</script>

<template>
  <n-config-provider :theme-overrides="naiveThemeOverrides">
    <n-message-provider>
      <n-dialog-provider>
        <n-notification-provider>
          <ErrorBoundary>
            <RouterView v-slot="{ Component, route: viewRoute }">
              <component :is="Component" :key="viewRoute.fullPath" />
            </RouterView>
          </ErrorBoundary>
          <Toaster />
          <WatchlistDock v-if="route.name !== 'login' && auth.token" />
        </n-notification-provider>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>
