// Direction A v2 — refined pro terminal theme
// (kept for backward compat — other views may still reference A2)

export const A2 = {
  bg: '#FFFFFF',
  bgDeep: '#F5F5F5',
  surface: '#F7F7F7',
  surfaceElev: '#FFFFFF',
  border: 'transparent',
  borderHair: '#EDEDED',
  borderStrong: '#D8D8D8',
  text: '#111111',
  textSub: '#3F3F46',
  textMuted: '#71717A',
  textDim: '#A1A1AA',
  qwen: '#111111',
  qwenDeep: '#000000',
  qwenSoft: '#F1F5F9',
  qwenGrad: '#111111',
  qwenGradSoft: '#F5F5F5',
  up: '#E04F76',
  upSoft: '#FFF1F1',
  down: '#16A35C',
  downSoft: '#ECFDF5',
  amber: '#B8FF2C',
  amberSoft: '#FFFBEB',
  shadow: 'none',
  shadowMd: 'none',
  shadowLg: 'none',
}

// Professional light financial terminal tokens.
// Brand colors stay neutral/blue; red/green are reserved for price direction.
export const Preview = {
  bg: '#FFFFFF',
  card: '#F7F7F7',
  border: '#EDEDED',
  mutedBg: '#F5F5F5',
  ink: '#111111',
  brand: '#111111',
  brandHover: '#000000',
  brandSoft: '#F1F5F9',
  accent: '#B8FF2C',
  chartGrid: '#E7E7E7',
  chartGridLight: '#F1F1F1',
  textMain: '#111111',
  textMuted: '#71717A',
  textFaint: '#A1A1AA',
  positive: '#E04F76',
  negative: '#16A35C',
  upSoft: '#FFF1F1',
  downSoft: '#ECFDF5',
  shadow: 'none',
}

export const card = { background: A2.surface, borderRadius: '8px', boxShadow: A2.shadow }
export const cardElev = { background: A2.surface, borderRadius: '8px', boxShadow: A2.shadowMd }
