<script setup>
import { useRoute } from 'vue-router'
import Toaster from './components/Toaster.vue'
import WatchlistDock from './components/WatchlistDock.vue'

const route = useRoute()
</script>

<template>
  <RouterView v-slot="{ Component }">
    <Transition name="page-fade" mode="out-in">
      <component :is="Component" />
    </Transition>
  </RouterView>
  <Toaster />
  <!-- 登录页不显示 dock -->
  <WatchlistDock v-if="route.name !== 'login'" />
</template>
