<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { A2 } from '../shared/theme.js'
import Icon from '../components/Icon.vue'
import { useAuthStore } from '../stores/auth'
import { friendlyError } from '../shared/errors.js'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const mode = ref(route.query.mode === 'register' ? 'register' : 'login')
const username = ref('')
const password = ref('')
const email = ref('')
const error = ref('')
const loading = ref(false)

function sanitizeRedirect(value) {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
    ? value
    : '/dashboard'
}

const redirectTarget = computed(() => sanitizeRedirect(route.query.redirect || route.query.next))
const needsLogin = computed(() => redirectTarget.value !== '/dashboard')

watch(
  () => route.query.mode,
  (value) => {
    mode.value = value === 'register' ? 'register' : 'login'
  },
)

async function submit() {
  error.value = ''
  const name = username.value.trim()
  const pwd = password.value
  const mail = email.value.trim()

  if (name.length < 3) {
    error.value = '用户名至少 3 位'
    return
  }
  if (pwd.length < 6) {
    error.value = '密码至少 6 位'
    return
  }

  loading.value = true
  try {
    if (mode.value === 'register') {
      await auth.register(name, pwd, mail)
    }
    await auth.login(name, pwd)
    router.replace(redirectTarget.value)
  } catch (e) {
    error.value = friendlyError(e)
  } finally {
    loading.value = false
  }
}

function continueAsGuest() {
  router.replace('/dashboard')
}
</script>

<template>
  <div class="login-bg">
    <div class="login-grid">
      <!-- 左侧 brand 区 -->
      <div class="login-brand">
        <div :style="{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '24px' }">
          <div :style="{ width: '36px', height: '36px', background: A2.qwenGrad, color: '#fff', display: 'grid', placeItems: 'center', fontWeight: 800, fontSize: '15px', borderRadius: '8px', boxShadow: '0 3px 10px rgba(36,86,216,0.30)' }">千</div>
          <div>
            <div :style="{ fontWeight: 700, fontSize: '17px', letterSpacing: '-0.3px', color: A2.text }">
              Qwen <span :style="{ color: A2.textMuted, fontSize: '11px', letterSpacing: '1.2px', fontWeight: 500 }">TERMINAL</span>
            </div>
            <div :style="{ fontSize: '11px', color: A2.textMuted, marginTop: '2px' }">基于千问的 A 股智能投研系统</div>
          </div>
        </div>

        <div class="login-headline">
          <div :style="{ fontSize: '32px', fontWeight: 700, lineHeight: 1.25, letterSpacing: '-0.6px', color: A2.text, marginBottom: '12px' }">
            用一句话<br/>把市场<span :style="{ color: A2.qwen }">说清楚</span>
          </div>
          <div :style="{ fontSize: '13px', color: A2.textSub, lineHeight: 1.7, marginBottom: '28px' }">
            千问大模型 + 沪深 800 只成分股的实时基本面，让自然语言筛选、深度研报、策略选股在一个工作台里完成。
          </div>
        </div>

        <div class="login-features">
          <div v-for="f in features" :key="f.t" class="login-feature">
            <div :style="{ width: '28px', height: '28px', borderRadius: '7px', background: A2.qwenSoft, color: A2.qwen, display: 'grid', placeItems: 'center', flexShrink: 0 }">
              <Icon :name="f.icon" :size="14" />
            </div>
            <div>
              <div :style="{ fontSize: '12.5px', fontWeight: 600, color: A2.text }">{{ f.t }}</div>
              <div :style="{ fontSize: '11px', color: A2.textMuted, marginTop: '2px', lineHeight: 1.5 }">{{ f.s }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧表单区 -->
      <div class="login-card">
        <div :style="{ display: 'flex', gap: '4px', padding: '3px', background: A2.bgDeep, borderRadius: '8px', marginBottom: '20px' }">
          <button v-for="m in ['login', 'register']" :key="m" @click="mode = m"
                  :style="{ flex: 1, padding: '8px', fontSize: '12.5px', fontWeight: mode === m ? 600 : 500, background: mode === m ? A2.surface : 'transparent', border: 'none', cursor: 'pointer', color: mode === m ? A2.text : A2.textMuted, borderRadius: '6px', boxShadow: mode === m ? A2.shadow : 'none', transition: 'all 0.15s' }">
            {{ m === 'login' ? '登录' : '注册' }}
          </button>
        </div>

        <div v-if="needsLogin" :style="{ background: A2.qwenSoft, color: A2.qwen, padding: '8px 10px', fontSize: '11.5px', borderRadius: '6px', marginBottom: '14px', lineHeight: 1.5 }">
          登录后继续访问当前业务页面。
        </div>

        <form @submit.prevent="submit">
          <div :style="{ marginBottom: '14px' }">
            <label :style="{ fontSize: '11px', color: A2.textMuted, fontWeight: 600, display: 'block', marginBottom: '6px', letterSpacing: '0.4px' }">用户名</label>
            <input v-model="username" required minlength="3" maxlength="64" autocomplete="username"
                   placeholder="3 - 64 位字符"
                   :style="{ width: '100%', padding: '10px 12px', fontSize: '13px', border: `1px solid ${A2.borderStrong}`, borderRadius: '8px', background: A2.surface, outline: 'none', fontFamily: 'IBM Plex Mono, monospace' }" />
          </div>

          <div :style="{ marginBottom: '14px' }">
            <label :style="{ fontSize: '11px', color: A2.textMuted, fontWeight: 600, display: 'block', marginBottom: '6px', letterSpacing: '0.4px' }">密码</label>
            <input v-model="password" type="password" required minlength="6" maxlength="64" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
                   placeholder="至少 6 位"
                   :style="{ width: '100%', padding: '10px 12px', fontSize: '13px', border: `1px solid ${A2.borderStrong}`, borderRadius: '8px', background: A2.surface, outline: 'none', fontFamily: 'IBM Plex Mono, monospace' }" />
          </div>

          <div v-if="mode === 'register'" :style="{ marginBottom: '14px' }">
            <label :style="{ fontSize: '11px', color: A2.textMuted, fontWeight: 600, display: 'block', marginBottom: '6px', letterSpacing: '0.4px' }">邮箱（选填）</label>
            <input v-model="email" type="email" autocomplete="email"
                   placeholder="用于密码找回"
                   :style="{ width: '100%', padding: '10px 12px', fontSize: '13px', border: `1px solid ${A2.borderStrong}`, borderRadius: '8px', background: A2.surface, outline: 'none' }" />
          </div>

          <div v-if="error" :style="{ background: A2.upSoft, color: A2.up, padding: '8px 12px', fontSize: '11.5px', borderRadius: '6px', marginBottom: '14px', display: 'flex', alignItems: 'flex-start', gap: '6px' }">
            <Icon name="alert" :size="11" />
            <span>{{ error }}</span>
          </div>

          <button type="submit" :disabled="loading"
                  :style="{ width: '100%', padding: '11px', background: A2.qwenGrad, color: '#fff', border: 'none', fontSize: '13px', fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer', borderRadius: '8px', boxShadow: '0 2px 8px rgba(36,86,216,0.25)', opacity: loading ? 0.7 : 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }">
            {{ loading ? '处理中…' : (mode === 'login' ? '登 录' : '注册并登录') }}
          </button>

          <div :style="{ marginTop: '14px', textAlign: 'center' }">
            <button type="button" @click="continueAsGuest"
                    :style="{ background: 'transparent', border: 'none', color: A2.qwen, fontSize: '11.5px', cursor: 'pointer', padding: '4px 8px' }">
              暂不登录，直接体验 →
            </button>
          </div>
        </form>

        <div :style="{ marginTop: '20px', fontSize: '10.5px', color: A2.textDim, lineHeight: 1.6, textAlign: 'center' }">
          继续即代表同意服务条款 · 数据仅供研究参考
        </div>
      </div>
    </div>

    <div class="login-footer">
      © 2026 Qwen Terminal · 学年设计项目 · 不构成投资建议
    </div>
  </div>
</template>

<script>
const features = [
  { icon: 'sparkle', t: '自然语言筛选', s: '"低估值高股息的银行股" 一句话即出结果' },
  { icon: 'chart',   t: '千问深度解读', s: '基于基本面数据的研报，流式生成' },
  { icon: 'flask',   t: '策略选股引擎', s: '套用突破、均线、RPS、涨停承接等规则输出股票池' },
  { icon: 'bell',    t: '价格预警',     s: '涨幅 / 跌幅 / 突破 / 日内 五种规则' },
]
export default { setup: () => ({ features }) }
</script>

<style scoped>
.login-bg {
  min-height: 100vh;
  background:
    radial-gradient(circle at 18% 20%, rgba(36,86,216,0.10), transparent 40%),
    radial-gradient(circle at 82% 80%, rgba(245,158,11,0.06), transparent 38%),
    #F6F5F0;
  font-family: 'IBM Plex Sans', 'Noto Sans SC', sans-serif;
  color: #111110;
  display: grid;
  grid-template-rows: 1fr auto;
}
.login-grid {
  display: grid;
  grid-template-columns: 1.1fr 380px;
  gap: 64px;
  align-items: center;
  justify-content: center;
  padding: 40px 56px;
  max-width: 1100px;
  width: 100%;
  margin: 0 auto;
}
.login-features {
  display: grid;
  gap: 14px;
}
.login-feature {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.login-card {
  width: 380px;
  background: #FFFFFF;
  border-radius: 14px;
  box-shadow: 0 14px 40px rgba(14,14,12,0.08), 0 4px 12px rgba(14,14,12,0.04);
  padding: 28px 26px;
  border: 1px solid rgba(14,14,12,0.06);
}
.login-footer {
  text-align: center;
  padding: 16px;
  font-size: 10.5px;
  color: #B8B4A8;
  border-top: 1px solid rgba(14,14,12,0.06);
}
@media (max-width: 880px) {
  .login-grid { grid-template-columns: 1fr; gap: 32px; padding: 32px 20px; }
  .login-card { width: 100%; max-width: 380px; margin: 0 auto; }
}

input:focus { border-color: #2456D8 !important; box-shadow: 0 0 0 3px rgba(36,86,216,0.08); }
button:not(:disabled):hover { filter: brightness(1.04); }
</style>
