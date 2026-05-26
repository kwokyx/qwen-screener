// 把后端 / axios / fetch 抛出的内部错误翻译成产品化中文提示。
// 调用方拿到的 message 不应该再包含 errno、stack、API_KEY 等内部信息。

const TRANSIENT_PATTERNS = [
  /connection reset/i, /connection aborted/i, /remote ?disconnect/i,
  /timed? ?out/i, /timeout/i, /broken pipe/i, /errno 5\d/i,
  /max retries exceeded/i, /network ?error/i, /ECONN/i, /ERR_NETWORK/i,
  /apiconnection/i,
]

function isTransient(s) {
  return TRANSIENT_PATTERNS.some((p) => p.test(s))
}

/**
 * @param {unknown} err  axios error / fetch error / 后端 detail 字符串 / 任意 thrown
 * @param {object} [opts]
 * @param {string} [opts.fallback='请求失败，请稍后再试']
 * @param {string} [opts.context='ai'|'data']  影响默认文案
 * @returns {string}
 */
export function friendlyError(err, opts = {}) {
  const { fallback, context = 'data' } = opts

  // 抽出可读文本
  let msg = ''
  if (err == null) msg = ''
  else if (typeof err === 'string') msg = err
  else if (err.response?.data?.detail) msg = String(err.response.data.detail)
  else if (err.message) msg = String(err.message)
  else msg = String(err)

  if (!msg) return fallback || (context === 'ai' ? 'AI 服务暂时不可用，请稍后再试' : '请求失败，请稍后再试')

  // 已经是中文产品化文案的（后端 _user_friendly_error 出来的），直接透传
  if (/^AI 服务|^请稍后|^行情服务/.test(msg) || /未知错误|^请求失败/.test(msg)) {
    return msg
  }

  const lower = msg.toLowerCase()

  // 鉴权类
  if (/api_?key/i.test(msg) || lower.includes('unauthorized') || lower.includes('401')) {
    return 'AI 服务凭证无效，请联系管理员检查配置'
  }
  if (lower.includes('429') || (lower.includes('rate') && lower.includes('limit'))) {
    return 'AI 服务请求过于频繁，请稍后再试'
  }
  if (lower.includes('503')) {
    return context === 'ai' ? 'AI 服务暂时不可用，请稍后再试' : '后端服务暂时不可用，请稍后再试'
  }
  if (lower.includes('404')) {
    return '未找到对应数据'
  }
  if (lower.includes('400')) {
    return '请求参数有误'
  }

  // 瞬时网络
  if (isTransient(msg)) {
    return context === 'ai' ? 'AI 服务暂时不可达，请稍后再试' : '网络不太稳定，请稍后再试'
  }

  // 兜底——如果原文是干净中文且不含技术名词，直接显示
  if (msg.length < 80 && !/errno|trace|exception|stack/i.test(msg)) {
    return msg
  }

  return fallback || (context === 'ai' ? 'AI 服务调用失败，请稍后再试' : '请求失败，请稍后再试')
}
