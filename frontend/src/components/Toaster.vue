<script setup>
import { useToastStore } from '../stores/toast'
import { A2 } from '../shared/theme.js'
import Icon from './Icon.vue'

const ts = useToastStore()

const ICON = { success: 'check', info: 'sparkle', warning: 'alert', error: 'shield' }
const TONE = {
  success: { bg: A2.surface, bar: A2.down, ic: A2.down },
  info:    { bg: A2.surface, bar: A2.qwen, ic: A2.qwen },
  warning: { bg: A2.surface, bar: A2.amber, ic: A2.amber },
  error:   { bg: A2.surface, bar: A2.up, ic: A2.up },
}
</script>

<template>
  <div class="toaster" role="status" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="t in ts.items" :key="t.id" class="toast"
           :style="{ background: TONE[t.type].bg, border: `1px solid ${A2.borderHair}`, boxShadow: A2.shadowMd }">
        <div :style="{ width: '3px', alignSelf: 'stretch', background: TONE[t.type].bar, borderRadius: '2px' }" />
        <div :style="{ color: TONE[t.type].ic, display: 'grid', placeItems: 'center', flexShrink: 0 }">
          <Icon :name="ICON[t.type]" :size="14" />
        </div>
        <div :style="{ flex: 1, fontSize: '12.5px', color: A2.text, lineHeight: 1.5 }">{{ t.message }}</div>
        <button @click="ts.dismiss(t.id)"
                :style="{ background: 'transparent', border: 'none', cursor: 'pointer', color: A2.textMuted, padding: '2px 4px' }">
          <Icon name="x" :size="11" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toaster {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 200;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}
.toast {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px 10px 8px;
  min-width: 240px;
  max-width: 360px;
  border-radius: 8px;
  pointer-events: auto;
}
.toast-enter-active, .toast-leave-active { transition: all 0.22s cubic-bezier(0.4, 0, 0.2, 1); }
.toast-enter-from { opacity: 0; transform: translateX(20px); }
.toast-leave-to   { opacity: 0; transform: translateX(20px); }
.toast-leave-active { position: absolute; right: 0; }
</style>
