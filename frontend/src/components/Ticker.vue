<script setup>
import { A2 } from '../shared/theme.js'
import { INDICES } from '../shared/data.js'
</script>

<template>
  <div :style="{ background: '#EFEDE6', color: A2.textSub, height: '24px', display: 'flex', alignItems: 'center', fontSize: '10.5px', fontFamily: 'IBM Plex Mono, monospace', padding: '0 16px', gap: '22px', overflow: 'hidden', boxShadow: '0 1px 0 ' + A2.borderHair, flexShrink: 0 }">
    <div v-for="idx in INDICES" :key="idx.code" :style="{ display: 'flex', alignItems: 'center', gap: '5px' }">
      <span :style="{ color: A2.textMuted, fontSize: '10px' }">{{ idx.name }}</span>
      <span :style="{ color: A2.text, fontWeight: 600 }">{{ idx.value.toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</span>
      <span :style="{ color: idx.change >= 0 ? A2.up : A2.down, fontWeight: 600 }">
        {{ idx.change >= 0 ? '▲' : '▼' }} {{ (idx.change >= 0 ? '+' : '') + idx.changePct.toFixed(2) }}%
      </span>
    </div>
    <div :style="{ marginLeft: 'auto', display: 'flex', gap: '14px', color: A2.textMuted }">
      <span>北向 <span :style="{ color: A2.up, fontWeight: 600 }">+28.42亿</span></span>
      <span>融资 <span :style="{ color: A2.up, fontWeight: 600 }">+12.18亿</span></span>
      <span>成交 <span :style="{ color: A2.text, fontWeight: 600 }">8,247亿</span></span>
      <span :style="{ display: 'flex', alignItems: 'center', gap: '4px' }">
        <span :style="{ width: '5px', height: '5px', background: A2.down, borderRadius: '50%' }" />
        2026-05-01 14:32
      </span>
    </div>
  </div>
</template>
