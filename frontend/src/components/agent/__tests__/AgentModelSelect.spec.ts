import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AgentModelSelect from '../AgentModelSelect.vue'
import {
  BRAND_STYLE_RULES,
  parseModelOption,
  resolveBrandStyle,
} from '../modelBrandRules'
import type { AgentModelOption } from '@/composables/useAgentModels'

describe('AgentModelSelect 品牌规则表与模型解析', () => {
  // 真实 opencode 返回的主流模型样例清单
  const opencodeModelSamples: AgentModelOption[] = [
    // Anthropic
    { value: 'opencode/claude-sonnet-5-5', label: 'Claude Sonnet 5.5 · opencode' },
    { value: 'opencode/claude-opus-5-5', label: 'Claude Opus 5.5 · opencode' },
    { value: 'opencode/claude-fable-5-1', label: 'Claude Fable 5.1 · opencode' },
    { value: 'opencode/claude-sonnet-5', label: 'Claude Sonnet 5 · opencode' },
    { value: 'opencode/claude-haiku-4-5', label: 'Claude Haiku 4.5 · opencode' },
    // OpenAI
    { value: 'opencode/gpt-6-luna', label: 'GPT-6 Luna · opencode' },
    { value: 'opencode/gpt-6-sol', label: 'GPT-6 Sol · opencode' },
    { value: 'opencode/gpt-6-astra', label: 'GPT-6 Astra · opencode' },
    { value: 'opencode/gpt-5.6-terra', label: 'GPT-5.6 Terra · opencode' },
    { value: 'opencode/gpt-5.5-pro', label: 'GPT-5.5 Pro · opencode' },
    { value: 'opencode/gpt-5.5', label: 'GPT-5.5 · opencode' },
    { value: 'opencode/gpt-5.4-nano', label: 'GPT-5.4 Nano · opencode' },
    { value: 'opencode/gpt-5.4-mini', label: 'GPT-5.4 Mini · opencode' },
    { value: 'opencode/gpt-5.3-codex', label: 'GPT-5.3 Codex · opencode' },
    { value: 'opencode/gpt-5.3-codex-spark', label: 'GPT-5.3 Codex Spark · opencode' },
    // Google Gemini
    { value: 'opencode/gemini-3.8-flash', label: 'Gemini 3.8 Flash · opencode' },
    { value: 'opencode/gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash Lite · opencode' },
    { value: 'opencode/gemini-3.1-pro', label: 'Gemini 3.1 Pro Preview · opencode' },
    // DeepSeek
    { value: 'opencode/deepseek-v4.1-flash', label: 'DeepSeek V4.1 Flash · opencode' },
    { value: 'opencode/deepseek-v4-pro', label: 'DeepSeek V4 Pro · opencode' },
    { value: 'volcengine-plan/deepseek-v4-flash', label: 'deepseek-v4-flash · volcengine-plan' },
    // 智谱 GLM
    { value: 'opencode/glm-5.3-flash', label: 'GLM-5.3-Flash · opencode' },
    { value: 'opencode/glm-5.3', label: 'GLM-5.3 · opencode' },
    { value: 'volcengine-plan/glm-latest', label: 'glm-latest · volcengine-plan' },
    // 月之暗面 Kimi
    { value: 'opencode/kimi-k3', label: 'Kimi K3 · opencode' },
    { value: 'opencode/kimi-k2.7-code', label: 'Kimi K2.7 Code · opencode' },
    { value: 'volcengine-plan/kimi-k2.8-preview', label: 'kimi-k2.8-preview · volcengine-plan' },
    // 阿里 通义千问 Qwen
    { value: 'opencode/qwen3.8-flash', label: 'Qwen3.8 Flash · opencode' },
    { value: 'opencode/qwen3.8-max', label: 'Qwen3.8 Max · opencode' },
    { value: 'opencode/qwen3.6-plus', label: 'Qwen3.6 Plus · opencode' },
    // MiniMax
    { value: 'opencode/minimax-m3', label: 'MiniMax-M3 · opencode' },
    { value: 'volcengine-plan/minimax-m3', label: 'minimax-m3 · volcengine-plan' },
    // 字节跳动 豆包 / 火山方舟原生
    { value: 'volcengine-plan/doubao-seed-2.1-turbo', label: 'doubao-seed-2.1-turbo · volcengine-plan' },
    { value: 'volcengine-plan/doubao-seed-evolving', label: 'doubao-seed-evolving · volcengine-plan' },
    { value: 'volcengine-plan/doubao-seed-2.0-lite', label: 'doubao-seed-2.0-lite · volcengine-plan' },
    { value: 'volcengine-plan/ark-code-latest', label: 'ark-code-latest · volcengine-plan' },
    // xAI Grok
    { value: 'opencode/grok-4.7', label: 'Grok 4.7 · opencode' },
    { value: 'opencode/grok-build-0.1', label: 'Grok Build 0.1 · opencode' },
    // 小米 MiMo
    { value: 'opencode/mimo-v2.6-flash-free', label: 'MiMo-V2.6-Flash Free · opencode' },
    // 英伟达 Nemotron
    { value: 'opencode/nemotron-3.5-lightning-free', label: 'Nemotron 3.5 Lightning Free · opencode' },
    { value: 'opencode/nemotron-3-ultra-free', label: 'Nemotron 3 Ultra Free · opencode' },
    // 昆仑万维 Muse Spark
    { value: 'opencode/muse-spark-1.3', label: 'Muse Spark 1.3 · opencode' },
    { value: 'opencode/muse-spark-1.3-contributor-free', label: 'Muse Spark 1.3 Free · opencode' },
    // 零一万物 Ling
    { value: 'opencode/ling-3.0-flash-fin-free', label: 'Ling 3.0 Flash Fin Free · opencode' },
    // 美团 LongCat
    { value: 'opencode/longcat-2.5-preview-free', label: 'LongCat 2.5 Preview Free · opencode' },
    // 实验/特殊社区模型 (兜底)
    { value: 'opencode/space-bunny-free', label: 'Space Bunny Free · opencode' },
    { value: 'opencode/big-pickle', label: 'Big Pickle · opencode' },
  ]

  it('正确解析各主流厂商模型品牌、配色与头像 Text', () => {
    // Anthropic
    const claude = parseModelOption({ value: 'opencode/claude-sonnet-5-5', label: 'Claude Sonnet 5.5 · opencode' })
    expect(claude.avatarText).toBe('C')
    expect(claude.avatarBg).toBe('#D97706')

    const claudeFable = parseModelOption({ value: 'opencode/claude-fable-5-1', label: 'Claude Fable 5.1 · opencode' })
    expect(claudeFable.avatarText).toBe('C')

    // OpenAI
    const gpt = parseModelOption({ value: 'opencode/gpt-6-luna', label: 'GPT-6 Luna · opencode' })
    expect(gpt.avatarText).toBe('GPT')
    expect(gpt.avatarBg).toBe('#FFFFFF')
    expect(gpt.dotColor).toBe('#10A37F')

    // Google Gemini
    const gemini = parseModelOption({ value: 'opencode/gemini-3.8-flash', label: 'Gemini 3.8 Flash · opencode' })
    expect(gemini.avatarText).toBe('GEM')
    expect(gemini.avatarBg).toBe('#1A73E8')

    // DeepSeek
    const ds = parseModelOption({ value: 'opencode/deepseek-v4.1-flash', label: 'DeepSeek V4.1 Flash · opencode' })
    expect(ds.avatarText).toBe('DS')
    expect(ds.avatarBg).toBe('#0EA5E9')

    // GLM
    const glm = parseModelOption({ value: 'opencode/glm-5.3-flash', label: 'GLM-5.3-Flash · opencode' })
    expect(glm.avatarText).toBe('GLM')
    expect(glm.avatarBg).toBe('#0F172A')

    // Qwen (紧跟数字无连字符，如 qwen3.8)
    const qwen = parseModelOption({ value: 'opencode/qwen3.8-flash', label: 'Qwen3.8 Flash · opencode' })
    expect(qwen.avatarText).toBe('QW')
    expect(qwen.avatarBg).toBe('#6366F1')

    // Kimi (动态提取代际代号)
    const kimiK3 = parseModelOption({ value: 'opencode/kimi-k3', label: 'Kimi K3 · opencode' })
    expect(kimiK3.avatarText).toBe('K3')
    const kimiK27 = parseModelOption({ value: 'opencode/kimi-k2.7-code', label: 'Kimi K2.7 Code · opencode' })
    expect(kimiK27.avatarText).toBe('K2.7')

    // MiniMax (动态提取 M3)
    const mm = parseModelOption({ value: 'opencode/minimax-m3', label: 'MiniMax-M3 · opencode' })
    expect(mm.avatarText).toBe('M3')
    expect(mm.avatarBg).toBe('#E11D48')

    // 豆包 / 火山平台原生模型
    const doubao = parseModelOption({ value: 'volcengine-plan/doubao-seed-2.1-turbo', label: 'doubao-seed-2.1-turbo · volcengine-plan' })
    expect(doubao.avatarText).toBe('DB')
    expect(doubao.avatarBg).toBe('#38BDF8')

    const ark = parseModelOption({ value: 'volcengine-plan/ark-code-latest', label: 'ark-code-latest · volcengine-plan' })
    expect(ark.avatarText).toBe('DB')

    // Grok
    const grok = parseModelOption({ value: 'opencode/grok-4.7', label: 'Grok 4.7 · opencode' })
    expect(grok.avatarText).toBe('GROK')
    expect(grok.avatarBg).toBe('#000000')

    // MiMo
    const mimo = parseModelOption({ value: 'opencode/mimo-v2.6-flash-free', label: 'MiMo-V2.6-Flash Free · opencode' })
    expect(mimo.avatarText).toBe('MI')
    expect(mimo.avatarBg).toBe('#FF6900')

    // Nemotron
    const nemo = parseModelOption({ value: 'opencode/nemotron-3.5-lightning-free', label: 'Nemotron 3.5 Lightning Free · opencode' })
    expect(nemo.avatarText).toBe('NV')
    expect(nemo.avatarBg).toBe('#76B900')

    // Meta (包含 Muse Spark 系列)
    const muse = parseModelOption({ value: 'opencode/muse-spark-1.3', label: 'Muse Spark 1.3 · opencode' })
    expect(muse.avatarText).toBe('MUSE')
    expect(muse.avatarBg).toBe('#0668E1') // Meta 蓝

    // LongCat
    const longcat = parseModelOption({ value: 'opencode/longcat-2.5-preview-free', label: 'LongCat 2.5 Preview Free · opencode' })
    expect(longcat.avatarText).toBe('LC')
    expect(longcat.avatarBg).toBe('#F59E0B')
  })

  it('适配 OpenRouter 的腾讯混元 moduleid (tencent/hy3 与 tencent/hy4-preview)', () => {
    // OpenRouter 代理直出格式
    const hy3FromOpenRouter = parseModelOption({
      value: 'openrouter/tencent/hy3',
      label: 'Tencent: hy3 · openrouter',
    })
    expect(hy3FromOpenRouter.avatarText).toBe('HY3')
    expect(hy3FromOpenRouter.avatarBg).toBe('#0052D9')

    const hy4PreviewFromOpenRouter = parseModelOption({
      value: 'openrouter/tencent/hy4-preview',
      label: 'Tencent: hy4-preview · openrouter',
    })
    expect(hy4PreviewFromOpenRouter.avatarText).toBe('HY4')
    expect(hy4PreviewFromOpenRouter.avatarBg).toBe('#0052D9')

    // 原生/直连格式
    const hy3 = parseModelOption({
      value: 'tencent/hy3',
      label: 'hy3 · tencent',
    })
    expect(hy3.avatarText).toBe('HY3')
    expect(hy3.avatarBg).toBe('#0052D9')

    const hy4Preview = parseModelOption({
      value: 'tencent/hy4-preview',
      label: 'hy4-preview · tencent',
    })
    expect(hy4Preview.avatarText).toBe('HY4')
    expect(hy4Preview.avatarBg).toBe('#0052D9')

    // 升级与子代号格式 (如 hy-5, hunyuan-lite)
    const hy5 = parseModelOption({
      value: 'tencent/hy-5-pro',
      label: 'Hunyuan HY-5 Pro · tencent',
    })
    expect(hy5.avatarText).toBe('HY5')
    expect(hy5.avatarBg).toBe('#0052D9')

    const hunyuanLite = parseModelOption({
      value: 'tencent/hunyuan-lite',
      label: 'Hunyuan Lite · tencent',
    })
    expect(hunyuanLite.avatarText).toBe('HY')
    expect(hunyuanLite.avatarBg).toBe('#0052D9')
  })

  it('杜绝渠道分发前缀干扰：托管在 volcengine-plan 上的第三方模型仍保持自身品牌', () => {
    // 在火山引擎上托管的 Kimi
    const hostedKimi = parseModelOption({ value: 'volcengine-plan/kimi-k3', label: 'kimi-k3 · volcengine-plan' })
    expect(hostedKimi.provider).toBe('volcengine-plan')
    expect(hostedKimi.avatarText).toBe('K3')
    expect(hostedKimi.avatarBg).toBe('#0F172A') // Kimi 曜黑，绝非豆包天蓝

    // 在火山引擎上托管的 DeepSeek
    const hostedDS = parseModelOption({ value: 'volcengine-plan/deepseek-v4-pro', label: 'deepseek-v4-pro · volcengine-plan' })
    expect(hostedDS.avatarText).toBe('DS')
    expect(hostedDS.avatarBg).toBe('#0EA5E9')

    // 在火山引擎上托管的 MiniMax
    const hostedMM = parseModelOption({ value: 'volcengine-plan/minimax-m3', label: 'minimax-m3 · volcengine-plan' })
    expect(hostedMM.avatarText).toBe('M3')
    expect(hostedMM.avatarBg).toBe('#E11D48')
  })

  it('严格词边界防误伤：muse-spark 不会被误匹配为 ark- 并归属豆包', () => {
    const muse = parseModelOption({ value: 'opencode/muse-spark-1.3', label: 'Muse Spark 1.3 · opencode' })
    expect(muse.avatarText).toBe('MUSE')
    expect(muse.avatarBg).toBe('#0668E1') // 归属 Meta 科技蓝，绝非豆包浅蓝
  })

  it('前瞻性支持厂商后续升级型号', () => {
    // OpenAI o系列推理模型升级
    const o3 = parseModelOption({ value: 'opencode/o3-mini', label: 'o3-mini · opencode' })
    expect(o3.avatarText).toBe('O3')
    expect(o3.avatarBg).toBe('#FFFFFF')

    const o4 = parseModelOption({ value: 'opencode/o4', label: 'o4 · opencode' })
    expect(o4.avatarText).toBe('O4')

    // Meta 旗下 Llama 与 Muse
    const llama3 = parseModelOption({ value: 'meta/llama-3.3-70b', label: 'Llama 3.3 70B · meta' })
    expect(llama3.avatarText).toBe('LLM')
    expect(llama3.avatarBg).toBe('#0668E1')

    // 阿里后续升级（如 qwen4-max）
    const qwen4 = parseModelOption({ value: 'aliyun/qwen4-max', label: 'Qwen4 Max · aliyun' })
    expect(qwen4.avatarText).toBe('QW')
    expect(qwen4.avatarBg).toBe('#6366F1')
  })

  it('社区与实验性模型优雅兜底（双词提取首字母）', () => {
    const sb = parseModelOption({ value: 'opencode/space-bunny-free', label: 'Space Bunny Free · opencode' })
    expect(sb.avatarText).toBe('SB')
    expect(sb.avatarBg).toBe('#475569')

    const bp = parseModelOption({ value: 'opencode/big-pickle', label: 'Big Pickle · opencode' })
    expect(bp.avatarText).toBe('BP')
    expect(bp.avatarBg).toBe('#475569')
  })

  it('全部 53 款真实 opencode 模型无任何未预期报错并能正常解析', () => {
    for (const opt of opencodeModelSamples) {
      const parsed = parseModelOption(opt)
      expect(parsed.value).toBe(opt.value)
      expect(parsed.avatarText).toBeTruthy()
      expect(parsed.avatarBg).toMatch(/^#[0-9A-Fa-f]{6}$/)
      expect(parsed.dotColor).toMatch(/^#[0-9A-Fa-f]{6}$/)
    }
  })

  it('组件挂载并正确渲染选中模型与其品牌圆点', async () => {
    const wrapper = mount(AgentModelSelect, {
      props: {
        modelValue: 'opencode/claude-sonnet-5-5',
        options: opencodeModelSamples,
      },
    })

    const trigger = wrapper.find('.model-trigger')
    expect(trigger.exists()).toBe(true)
    expect(trigger.text()).toContain('Claude Sonnet 5.5')

    const dot = wrapper.find('.status-dot')
    expect(dot.attributes('style')).toContain('background-color: rgb(245, 158, 11)') // #F59E0B
  })
})
