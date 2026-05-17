<script setup>
import { useRoute } from 'vue-router'
import ErrorBoundary from './components/ErrorBoundary.vue'
import Toaster from './components/Toaster.vue'
import WatchlistDock from './components/WatchlistDock.vue'

const route = useRoute()
</script>

<template>
  <ErrorBoundary>
    <RouterView v-slot="{ Component }">
      <Transition name="page-fade" mode="out-in">
        <component :is="Component" />
      </Transition>
    </RouterView>
  </ErrorBoundary>
  <Toaster />
  <!-- 登录页不显示 dock -->
  <WatchlistDock v-if="route.name !== 'login'" />
</template>
