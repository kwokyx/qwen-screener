<script setup>
defineProps({
  width: { type: [String, Number], default: '100%' },
  height: { type: [String, Number], default: 14 },
  rounded: { type: [String, Number], default: 4 },
  inline: { type: Boolean, default: false },
})
</script>

<template>
  <span class="sk" :style="{
    width: typeof width === 'number' ? width + 'px' : width,
    height: typeof height === 'number' ? height + 'px' : height,
    borderRadius: typeof rounded === 'number' ? rounded + 'px' : rounded,
    display: inline ? 'inline-block' : 'block',
  }" />
</template>

<style scoped>
.sk {
  background: linear-gradient(90deg, rgba(14,14,12,0.05) 25%, rgba(14,14,12,0.10) 37%, rgba(14,14,12,0.05) 63%);
  background-size: 400% 100%;
  animation: sk-shimmer 1.4s ease-in-out infinite;
  vertical-align: middle;
}
@keyframes sk-shimmer {
  0% { background-position: 100% 50%; }
  100% { background-position: 0 50%; }
}
</style>
