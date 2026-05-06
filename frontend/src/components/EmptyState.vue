<script setup>
import { A2 } from '../shared/theme.js'

defineProps({
  icon: { type: String, default: '📋' },     // emoji 字符串
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  compact: { type: Boolean, default: false },  // 表格行嵌入用
})
</script>

<template>
  <div :style="{ padding: compact ? '24px 16px' : '40px 20px', textAlign: 'center', color: A2.textMuted }">
    <div :style="{ fontSize: compact ? '20px' : '28px', marginBottom: compact ? '4px' : '10px', lineHeight: 1 }">{{ icon }}</div>
    <div :style="{ fontSize: compact ? '12px' : '13px', color: A2.text, fontWeight: 600, marginBottom: '4px' }">{{ title }}</div>
    <div v-if="subtitle" :style="{ fontSize: compact ? '11px' : '11.5px', color: A2.textDim, lineHeight: 1.5 }">{{ subtitle }}</div>
    <div v-if="$slots.action" :style="{ marginTop: '12px' }"><slot name="action" /></div>
  </div>
</template>
