<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useWatchlistStore } from '../stores/watchlist'
import { toast } from '../stores/toast'
import Icon from './Icon.vue'

const props = defineProps({
  stock: { type: Object, required: true },   // {code, name, sector, refPrice}
  size: { type: Number, default: 14 },
  variant: { type: String, default: 'icon' }, // icon | button
})

const wl = useWatchlistStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const active = computed(() => wl.has(props.stock.code))

function onClick(e) {
  e.stopPropagation()
  e.preventDefault()
  if (!auth.token) {
    toast.info('登录后可以保存自选股')
    router.push({ name: 'login', query: { redirect: route.fullPath } })
    return
  }
  const wasActive = active.value
  wl.toggle(props.stock)
  const name = props.stock.name || props.stock.code
  if (wasActive) toast.info(`已从自选移除 ${name}`)
  else toast.success(`已加入自选 · ${name}`)
}
</script>

<template>
  <button v-if="variant === 'button'" class="btn-outline" :class="{ active }" @click="onClick">
    <Icon :name="active ? 'starF' : 'star'" :size="size" :color="active ? '#F59E0B' : 'currentColor'" />
    {{ active ? '已自选' : '加自选' }}
  </button>
  <button v-else class="star-btn" :class="{ active }" :title="active ? '从自选移除' : '加入自选'" @click="onClick">
    <Icon :name="active ? 'starF' : 'star'" :size="size" :color="active ? '#F59E0B' : '#B8B4A8'" />
  </button>
</template>

<style scoped>
.star-btn {
  background: transparent;
  border: none;
  padding: 4px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  cursor: pointer;
}
.star-btn:hover { background: rgba(14, 14, 12, 0.06); }
.btn-outline.active { color: #C77E18; border-color: rgba(199, 126, 24, 0.4); background: #FAF1E0; }
</style>
