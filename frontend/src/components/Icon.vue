<script setup>
const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 16 },
  stroke: { type: [Number, String], default: 1.5 },
  color: { type: String, default: 'currentColor' },
})
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" :stroke="color" :stroke-width="stroke" stroke-linecap="round" stroke-linejoin="round">
    <template v-if="name === 'search'"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.35-4.35" /></template>
    <template v-else-if="name === 'send'"><path d="M3 12h18M13 6l8 6-8 6" /></template>
    <template v-else-if="name === 'sparkle'"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.5 5.5l2.8 2.8M15.7 15.7l2.8 2.8M5.5 18.5l2.8-2.8M15.7 8.3l2.8-2.8" /></template>
    <template v-else-if="name === 'chart'"><path d="M3 3v18h18" /><path d="m7 14 4-4 4 4 5-6" /></template>
    <template v-else-if="name === 'home'"><path d="m3 10 9-7 9 7v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V10z" /><path d="M9 21V12h6v9" /></template>
    <template v-else-if="name === 'star'"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></template>
    <template v-else-if="name === 'starF'"><path :fill="color" d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></template>
    <template v-else-if="name === 'filter'"><path d="M22 3H2l8 9.46V19l4 2v-8.54L22 3z" /></template>
    <template v-else-if="name === 'briefcase'"><rect x="2" y="7" width="20" height="14" rx="2" /><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" /></template>
    <template v-else-if="name === 'flask'"><path d="M9 3h6M10 3v6L4 20a2 2 0 0 0 1.7 3h12.6A2 2 0 0 0 20 20l-6-11V3" /></template>
    <template v-else-if="name === 'user'"><circle cx="12" cy="7" r="4" /><path d="M5 21v-2a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v2" /></template>
    <template v-else-if="name === 'bot'"><path d="M12 8V4H8" /><rect x="4" y="8" width="16" height="12" rx="2" /><path d="M2 14h2M20 14h2M9 13v2M15 13v2" /></template>
    <template v-else-if="name === 'bell'"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M13.7 21a2 2 0 0 1-3.4 0" /></template>
    <template v-else-if="name === 'plus'"><path d="M12 5v14M5 12h14" /></template>
    <template v-else-if="name === 'arrowUp'"><path d="M12 19V5M5 12l7-7 7 7" /></template>
    <template v-else-if="name === 'arrowDown'"><path d="M12 5v14M19 12l-7 7-7-7" /></template>
    <template v-else-if="name === 'arrowRight'"><path d="M5 12h14M12 5l7 7-7 7" /></template>
    <template v-else-if="name === 'check'"><path d="M20 6 9 17l-5-5" /></template>
    <template v-else-if="name === 'x'"><path d="M18 6 6 18M6 6l12 12" /></template>
    <template v-else-if="name === 'menu'"><path d="M3 12h18M3 6h18M3 18h18" /></template>
    <template v-else-if="name === 'mic'"><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3" /></template>
    <template v-else-if="name === 'attach'"><path d="M21 11l-9 9a5 5 0 0 1-7-7l9-9a3 3 0 0 1 5 5l-9 9a1 1 0 0 1-2-2l8-8" /></template>
    <template v-else-if="name === 'refresh'"><path d="M21 12a9 9 0 0 0-15-7l-3 3M3 12a9 9 0 0 0 15 7l3-3M21 5v5h-5M3 19v-5h5" /></template>
    <template v-else-if="name === 'download'"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" /></template>
    <template v-else-if="name === 'share'"><circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" /><path d="m8.59 13.51 6.83 3.98M15.41 6.51l-6.82 3.98" /></template>
    <template v-else-if="name === 'lightbulb'"><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.7.5 1 1.3 1 2.1V18h6v-1.2c0-.8.3-1.6 1-2.1A7 7 0 0 0 12 2z" /></template>
    <template v-else-if="name === 'brain'"><path d="M12 5a3 3 0 0 0-3-3 3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 1 5 3 3 0 0 0 4 3 3 3 0 0 0 6 0 3 3 0 0 0 4-3 3 3 0 0 0 1-5 3 3 0 0 0-2-5 3 3 0 0 0-3-3 3 3 0 0 0-3 3z" /></template>
    <template v-else-if="name === 'trend'"><path d="M22 7l-8.5 8.5-5-5L2 17M16 7h6v6" /></template>
    <template v-else-if="name === 'fire'"><path d="M14 4s4 6 4 10a6 6 0 0 1-12 0c0-2 2-3 2-5 2 0 2 2 2 2s2-2 2-5c1 0 2-2 2-2z" /></template>
    <template v-else-if="name === 'shield'"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></template>
    <template v-else-if="name === 'eye'"><path d="M2 12s4-8 10-8 10 8 10 8-4 8-10 8-10-8-10-8z" /><circle cx="12" cy="12" r="3" /></template>
    <template v-else-if="name === 'doc'"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M9 13h6M9 17h4" /></template>
    <template v-else-if="name === 'tools'"><path d="M14.7 6.3a3 3 0 1 0 4.2 4.2L21 8.5V13L13 21l-3-3 8-8-2.7-2.7zM7 14l-5 5a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l5-5" /></template>
    <template v-else-if="name === 'chevronDown'"><path d="m6 9 6 6 6-6" /></template>
    <template v-else-if="name === 'chevronRight'"><path d="m9 6 6 6-6 6" /></template>
    <template v-else-if="name === 'play'"><path :fill="color" d="M5 3l14 9-14 9V3z" /></template>
    <template v-else-if="name === 'bookmark'"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z" /></template>
    <template v-else-if="name === 'alert'"><path d="M12 9v4M12 17h.01M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0z" /></template>
    <template v-else-if="name === 'loader'"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></template>
    <template v-else><circle cx="12" cy="12" r="9" /></template>
  </svg>
</template>
