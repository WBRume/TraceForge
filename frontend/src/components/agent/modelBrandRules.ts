import type { AgentModelOption } from '@/composables/useAgentModels'

// 模型信息结构定义
export interface ParsedModel {
  value: string
  label: string
  modelName: string
  modelId: string
  provider: string
  groupName: string
  avatarText: string
  avatarBg: string
  avatarColor: string
  dotColor: string
}

export interface BrandPatternRule {
  brand: string
  patterns: readonly (string | RegExp)[]
  avatarText: string | ((name: string, modelId: string) => string)
  avatarBg: string
  avatarColor?: string
  dotColor: string
}

// 声明式品牌规则表（基于主流厂商命名升级风格与真实模型列表表驱动设计）
export const BRAND_STYLE_RULES: readonly BrandPatternRule[] = [
  // 1. Anthropic Claude 系列 (Sonnet, Opus, Haiku, Fable 等子代号持续演进)
  {
    brand: 'Claude',
    patterns: [/\b(claude|sonnet|opus|haiku|fable)\b/i, /\banthropic\b/i],
    avatarText: 'C',
    avatarBg: '#D97706', // 琥珀暖橙
    avatarColor: '#FFFFFF',
    dotColor: '#F59E0B',
  },
  // 2. 深度求索 DeepSeek 系列 (V2, V3, V4, V4.1, Pro, Flash, Coder, Chat)
  {
    brand: 'DeepSeek',
    patterns: [/\bdeep-?seek/i],
    avatarText: 'DS',
    avatarBg: '#0EA5E9', // 天蓝色
    avatarColor: '#FFFFFF',
    dotColor: '#0EA5E9',
  },
  // 3. OpenAI 系列 (GPT-4/5/6, o1/o3/o4 系列, Codex, ChatGPT)
  {
    brand: 'OpenAI',
    patterns: [
      /\bgpt(-|\b|\d)/i,
      /\b(chatgpt|openai|codex)\b/i,
      /\bo[1-9](-|\b)/i,
    ],
    avatarText: (name: string, id: string) => {
      const oMatch = `${name} ${id}`.match(/\bo[1-9]\b/i)
      return oMatch ? oMatch[0].toUpperCase() : 'GPT'
    },
    avatarBg: '#FFFFFF',
    avatarColor: '#000000',
    dotColor: '#10A37F',
  },
  // 4. Google Gemini 系列 (Flash, Pro, Ultra, Flash Lite, 3.x, 4.x)
  {
    brand: 'Gemini',
    patterns: [/\bgemini/i, /\bgoogle\b/i],
    avatarText: 'GEM',
    avatarBg: '#1A73E8', // 谷歌科技蓝
    avatarColor: '#FFFFFF',
    dotColor: '#4285F4',
  },
  // 5. 智谱 GLM 系列 (GLM-4, GLM-5, 5.3, Flash, Air, Pro, Latest, CodeGeeX)
  {
    brand: 'GLM',
    patterns: [/\b(chat)?glm/i, /\b(zhipu|codegeex|cogview)\b/i],
    avatarText: 'GLM',
    avatarBg: '#0F172A', // 科技墨黑
    avatarColor: '#FFFFFF',
    dotColor: '#3B82F6',
  },
  // 6. 月之暗面 Kimi 系列 (K2, K2.7, K2.8, K3, K4 等代际演进)
  {
    brand: 'Kimi',
    patterns: [/\bkimi/i, /\bmoonshot\b/i],
    avatarText: (name: string, id: string) => {
      const kMatch = `${name} ${id}`.match(/\bk[0-9](\.[0-9]+)?\b/i)
      return kMatch ? kMatch[0].toUpperCase() : 'KM'
    },
    avatarBg: '#0F172A', // 质感曜黑
    avatarColor: '#FFFFFF',
    dotColor: '#475569',
  },
  // 7. 阿里 通义千问 Qwen 系列 (Qwen2.5, Qwen3, 3.6, 3.8, Max, Plus, Flash)
  {
    brand: 'Qwen',
    patterns: [/\bqwen/i, /\b(tongyi|wanx|alibaba)\b/i],
    avatarText: 'QW',
    avatarBg: '#6366F1', // 千问紫
    avatarColor: '#FFFFFF',
    dotColor: '#818CF8',
  },
  // 8. MiniMax / 稀宇科技 (MiniMax-M2, M2.5, M3, M4, abab)
  {
    brand: 'MiniMax',
    patterns: [/\bminimax/i, /\babab/i],
    avatarText: (name: string, id: string) => {
      const mMatch = `${name} ${id}`.match(/\bm[0-9]+/i)
      return mMatch ? `M${mMatch[0].slice(1)}` : 'MM'
    },
    avatarBg: '#E11D48', // MiniMax 玫瑰红
    avatarColor: '#FFFFFF',
    dotColor: '#F43F5E',
  },
  // 9. 字节跳动 豆包 / 火山引擎平台原生模型 (Doubao, Seed 架构系列, Ark 方舟原生)
  {
    brand: 'Doubao',
    patterns: [
      /\bdoubao/i,
      /\bseed-/i,
      /\bark-[a-z0-9]/i,
      /\bbytedance\b/i,
    ],
    avatarText: 'DB',
    avatarBg: '#38BDF8', // 豆包浅蓝
    avatarColor: '#FFFFFF',
    dotColor: '#38BDF8',
  },
  // 10. Meta 系列 (包含 Llama 与 Muse Spark 系列)
  {
    brand: 'Meta',
    patterns: [
      /\bllama/i,
      /\bmeta\b/i,
      /\bmuse(-|\b)/i,
    ],
    avatarText: (name: string, id: string) => {
      return /\bmuse\b/i.test(`${name} ${id}`) ? 'MUSE' : 'LLM'
    },
    avatarBg: '#0668E1', // Meta 科技蓝
    avatarColor: '#FFFFFF',
    dotColor: '#0668E1',
  },
  // 11. xAI Grok 系列 (Grok-2, Grok-3, 4.7, Grok Build 等)
  {
    brand: 'Grok',
    patterns: [/\bgrok/i, /\bxai\b/i],
    avatarText: 'GROK',
    avatarBg: '#000000', // 极致纯黑
    avatarColor: '#FFFFFF',
    dotColor: '#71717A',
  },
  // 12. 小米 MiMo 系列 (MiMo V2, V2.6, V3, Flash, Pro 等)
  {
    brand: 'MiMo',
    patterns: [/\bmimo/i, /\bxiaomi\b/i],
    avatarText: 'MI',
    avatarBg: '#FF6900', // 小米亮橙色
    avatarColor: '#FFFFFF',
    dotColor: '#FF6900',
  },
  // 13. NVIDIA Nemotron 系列 (Nemotron-3, 3.5, Ultra, Lightning 等)
  {
    brand: 'Nemotron',
    patterns: [/\bnemotron/i, /\bnvidia\b/i],
    avatarText: 'NV',
    avatarBg: '#76B900', // 英伟达电光绿
    avatarColor: '#FFFFFF',
    dotColor: '#76B900',
  },
  // 14. 美团 LongCat 系列 (LongCat 2.5 Preview 等)
  {
    brand: 'LongCat',
    patterns: [/\blongcat/i, /\bmeituan\b/i],
    avatarText: 'LC',
    avatarBg: '#F59E0B', // 美团亮黄
    avatarColor: '#1E293B',
    dotColor: '#D97706',
  },
  // 15. 腾讯混元 (适配 openrouter: tencent/hy3, tencent/hy4-preview 及后续升级)
  {
    brand: 'Hunyuan',
    patterns: [
      /\bhunyuan/i,
      /\bhy-?\d+/i,
      /\bhy-(preview|turbo|pro|lite|standard|vision)\b/i,
    ],
    avatarText: (name: string, id: string) => {
      const target = `${name} ${id}`
      const hyMatch = target.match(/\bhy-?[0-9]+/i)
      return hyMatch ? hyMatch[0].replace('-', '').toUpperCase() : 'HY'
    },
    avatarBg: '#0052D9', // 腾讯混元蓝
    avatarColor: '#FFFFFF',
    dotColor: '#266FE8',
  },
] as const

// 表驱动品牌样式解析器（解耦渠道前缀，针对模型标识精准匹配）
export const resolveBrandStyle = (modelName: string, modelId: string, rawValue: string = '') => {
  const searchTarget = `${modelName} ${modelId} ${rawValue}`
  const matched = BRAND_STYLE_RULES.find(rule =>
    rule.patterns.some(pattern => {
      if (typeof pattern === 'string') {
        return searchTarget.toLowerCase().includes(pattern.toLowerCase())
      }
      return pattern.test(searchTarget)
    })
  )

  if (matched) {
    const avatarText = typeof matched.avatarText === 'function'
      ? matched.avatarText(modelName, modelId)
      : matched.avatarText
    return {
      avatarText,
      avatarBg: matched.avatarBg,
      avatarColor: matched.avatarColor || '#FFFFFF',
      dotColor: matched.dotColor,
    }
  }

  // 默认兜底：提取词首字母（如 Space Bunny -> SB）或前 3 个字符
  const words = modelName.match(/[a-zA-Z0-9]+/g) || []
  let fallbackText = 'AI'
  if (words.length >= 2) {
    fallbackText = (words[0][0] + words[1][0]).toUpperCase()
  } else if (words.length === 1) {
    fallbackText = words[0].slice(0, 3).toUpperCase()
  }
  return {
    avatarText: fallbackText,
    avatarBg: '#475569',
    avatarColor: '#FFFFFF',
    dotColor: '#94A3B8',
  }
}

// 智能模型品牌与特征提取器
export const parseModelOption = (opt: AgentModelOption): ParsedModel => {
  const rawValue = opt.value || ''
  const rawLabel = opt.label || rawValue || ''
  let modelName = rawLabel
  let modelId = rawValue
  let provider = ''

  // 1. 提取 provider 与纯净模型名及纯净模型 ID：
  // 规则 A：若 value 包含斜杠（格式为 "provider/model_id"）
  if (rawValue.includes('/')) {
    const slashIdx = rawValue.indexOf('/')
    provider = rawValue.slice(0, slashIdx).trim()
    modelId = rawValue.slice(slashIdx + 1).trim()

    const splitMatch = rawLabel.split(/\s+[·|\-]\s+/)
    if (splitMatch.length >= 2) {
      modelName = splitMatch[0].trim()
      if (!provider) provider = splitMatch[1].trim()
    } else if (rawLabel === rawValue) {
      modelName = modelId
    }
  } else {
    // 规则 B：若 value 无斜杠，尝试从 label "model_name · provider" 中解析
    const splitMatch = rawLabel.split(/\s+[·|\-]\s+/)
    if (splitMatch.length >= 2) {
      modelName = splitMatch[0].trim()
      provider = splitMatch.slice(1).join(' ').trim()
    }
  }

  // 分组直接显示原生 provider，没有则为空（没有则不显示分组标题）
  const groupName = provider

  // 2. 表驱动获取品牌配色与头像徽标（基于 modelName 与纯净 modelId，避免渠道干扰）
  const { avatarText, avatarBg, avatarColor, dotColor } = resolveBrandStyle(modelName, modelId, rawValue)

  return {
    value: opt.value,
    label: opt.label,
    modelName,
    modelId,
    provider,
    groupName,
    avatarText,
    avatarBg,
    avatarColor,
    dotColor,
  }
}
