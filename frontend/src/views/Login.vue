<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { A2 } from '../shared/theme.js'
import Icon from '../components/Icon.vue'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const mode = ref('login') // 'login' | 'register'
const username = ref('')
const password = ref('')
const email = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    if (mode.value === 'register') {
      await auth.register(username.value, password.value, email.value)
    }
    await auth.login(username.value, password.value)
    const next = route.query.next || '/dashboard'
    router.replace(next)
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || '请求失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div :style="{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: A2.bg, fontFamily: 'IBM Plex Sans, Noto Sans SC, sans-serif' }">
    <div :style="{ width: '380px', background: A2.surface, borderRadius: '14px', boxShadow: A2.shadowLg, padding: '32px 28px', border: `1px solid ${A2.borderHair}` }">
      <div :style="{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '24px' }">
        <div :style="{ width: '32px', height: '32px', background: A2.qwenGrad, color: '#fff', display: 'grid', placeItems: 'center', fontWeight: 800, fontSize: '14px', borderRadius: '8px', boxShadow: '0 2px 6px rgba(36,86,216,0.30)' }">千</div>
        <div>
          <div :style="{ fontWeight: 700, fontSize: '15px', letterSpacing: '-0.2px' }">
            Qwen <span :style="{ color: A2.textMuted, fontSize: '11px', letterSpacing: '1.2px', fontWeight: 500 }">TERMINAL</span>
          </div>
          <div :style="{ fontSize: '11px', color: A2.textMuted, marginTop: '1px' }">基于千问的股票筛选系统</div>
        </div>
      </div>

      <div :style="{ display: 'flex', gap: '4px', padding: '3px', background: A2.bgDeep, borderRadius: '8px', marginBottom: '20px' }">
        <button v-for="m in ['login', 'register']" :key="m" @click="mode = m"
                :style="{ flex: 1, padding: '7px', fontSize: '12px', fontWeight: mode === m ? 600 : 500, background: mode === m ? A2.surface : 'transparent', border: 'none', cursor: 'pointer', color: mode === m ? A2.text : A2.textMuted, borderRadius: '6px', boxShadow: mode === m ? A2.shadow : 'none' }">
          {{ m === 'login' ? '登录' : '注册' }}
        </button>
      </div>

      <form @submit.prevent="submit">
        <div :style="{ marginBottom: '14px' }">
          <label :style="{ fontSize: '11px', color: A2.textMuted, fontWeight: 600, display: 'block', marginBottom: '6px', letterSpacing: '0.4px' }">用户名</label>
          <input v-model="username" required minlength="3" maxlength="64" autocomplete="username"
                 :style="{ width: '100%', padding: '10px 12px', fontSize: '13px', border: `1px solid ${A2.borderStrong}`, borderRadius: '8px', background: A2.surface, outline: 'none', fontFamily: 'IBM Plex Mono, monospace' }" />
        </div>

        <div :style="{ marginBottom: '14px' }">
          <label :style="{ fontSize: '11px', color: A2.textMuted, fontWeight: 600, display: 'block', marginBottom: '6px', letterSpacing: '0.4px' }">密码</label>
          <input v-model="password" type="password" required minlength="6" maxlength="64" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
                 :style="{ width: '100%', padding: '10px 12px', fontSize: '13px', border: `1px solid ${A2.borderStrong}`, borderRadius: '8px', background: A2.surface, outline: 'none', fontFamily: 'IBM Plex Mono, monospace' }" />
        </div>

        <div v-if="mode === 'register'" :style="{ marginBottom: '14px' }">
          <label :style="{ fontSize: '11px', color: A2.textMuted, fontWeight: 600, display: 'block', marginBottom: '6px', letterSpacing: '0.4px' }">邮箱（选填）</label>
          <input v-model="email" type="email" autocomplete="email"
                 :style="{ width: '100%', padding: '10px 12px', fontSize: '13px', border: `1px solid ${A2.borderStrong}`, borderRadius: '8px', background: A2.surface, outline: 'none' }" />
        </div>

        <div v-if="error" :style="{ background: A2.upSoft, color: A2.up, padding: '8px 12px', fontSize: '11.5px', borderRadius: '6px', marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }">
          <Icon name="shield" :size="11" /> {{ error }}
        </div>

        <button type="submit" :disabled="loading"
                :style="{ width: '100%', padding: '11px', background: A2.qwenGrad, color: '#fff', border: 'none', fontSize: '13px', fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer', borderRadius: '8px', boxShadow: '0 2px 8px rgba(36,86,216,0.20)', opacity: loading ? 0.7 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }">
          <Icon name="sparkle" :size="13" /> {{ loading ? '处理中...' : (mode === 'login' ? '登 录' : '注册并登录') }}
        </button>
      </form>

      <div :style="{ marginTop: '18px', padding: '10px 12px', background: A2.qwenGradSoft, borderRadius: '8px', fontSize: '11px', color: A2.qwenDeep, lineHeight: 1.55, border: `1px solid ${A2.borderHair}` }">
        提示：首次使用请先注册，所有数据仅用于学习研究。
      </div>
    </div>
  </div>
</template>
