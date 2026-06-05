import client from './client'

function normalizeCaptcha(payload = {}) {
  return {
    captcha_id: payload.captcha_id || payload.captchaId || '',
    captcha_code: payload.captcha_code || payload.captchaCode || '',
  }
}

export async function captcha() {
  const { data } = await client.get('/auth/captcha')
  return data
}

export async function login(username, password, captchaPayload = {}) {
  // FastAPI OAuth2PasswordRequestForm 要求 form-encoded
  const form = new URLSearchParams({ username, password, ...normalizeCaptcha(captchaPayload) })
  const { data } = await client.post('/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  return data
}

export async function register(username, password, email, captchaPayload = {}) {
  const { data } = await client.post('/auth/register', {
    username,
    password,
    email,
    ...normalizeCaptcha(captchaPayload),
  })
  return data
}

export async function me() {
  const { data } = await client.get('/auth/me')
  return data
}
