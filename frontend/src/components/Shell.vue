<script setup>
import TopBar from './TopBar.vue'
import Ticker from './Ticker.vue'
import { A2 } from '../shared/theme.js'
</script>

<template>
  <div class="artboard-root" :style="{ background: A2.bg, height: '100vh', display: 'flex', flexDirection: 'column', color: A2.text, fontFamily: 'IBM Plex Sans, Noto Sans SC, sans-serif' }">
    <TopBar />
    <Ticker />
    <div :style="{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' }">
      <slot />
    </div>
  </div>
</template>
