/**
 * rp67 适配器注入用例。由 adapters/risuai/run.mjs 复制到 src/ts/poc/rp67_adapter.test.ts 后运行。
 *
 * 被测算法全部是 RisuAI 上游代码：
 *   src/ts/process/lorebook.svelte.ts  loadLoreBookV3Prompt（世界书触发 / 递归扫描 / 预算截断 / 排序）
 *   src/ts/tokenizer.ts                tokenize（token 估算；loadLoreBookV3Prompt:581 内部调用）
 *   src/ts/parser/parser.svelte.ts     risuChatParser（CBS 解析；loadLoreBookV3Prompt:581 内部调用）
 *   src/ts/process/prompt.ts           detectPromptJSONType / stChatConvert
 *   src/ts/parser/chatML.ts            parseChatML
 * 唯一被替换的模块是全局状态容器 src/ts/stores.svelte（仓库自带测试
 * src/ts/parser/tests/cbs/strings.test.ts:23-61 是同一做法），其余模块不 mock。
 *
 * 本文件不含随机成分：不使用 @@probability（上游用 Math.random，lorebook.svelte.ts:494），
 * 不使用 @@keep_activate_after_match / @@dont_activate_after_match（写 chatvar，:588-593）。
 */
import { test, vi } from 'vitest'
import { writable } from 'svelte/store'
import { DBState, selectedCharID } from 'src/ts/stores.svelte'
import { loadLoreBookV3Prompt } from 'src/ts/process/lorebook.svelte'
import { risuChatParser } from 'src/ts/parser/parser.svelte'
import { parseChatML } from 'src/ts/parser/chatML'
import { detectPromptJSONType, stChatConvert } from 'src/ts/process/prompt'
import { tokenize } from 'src/ts/tokenizer'
import fixture from './rp67_fixture.json'

vi.mock(
  import('src/ts/stores.svelte'),
  () =>
    ({
      DBState: { db: {} },
      selIdState: { selId: 0 },
      selectedCharID: writable(0),
    }) as any,
)

const fx: any = fixture

const emit = (tag: string, value: unknown) => {
  console.log('RPREADING|' + tag + '|' + JSON.stringify(value))
}

const brief = (a: any) => ({
  source: a.source,
  order: a.order,
  priority: a.priority,
  depth: a.depth,
  pos: a.pos,
  role: a.role,
  tokens: a.tokens,
  inject: a.inject,
  prompt: a.prompt,
})

function makeDb(entries: any[], messages: any[]) {
  const char: any = {
    type: 'character',
    name: fx.characterName,
    firstMessage: '',
    desc: '',
    notes: '',
    chatPage: 0,
    scriptstate: {},
    globalLore: entries,
    chats: [{ localLore: [], fmIndex: 0, scriptstate: {}, message: messages }],
    loreSettings: {
      scanDepth: fx.settings.scanDepth,
      tokenBudget: fx.settings.tokenBudget,
      fullWordMatching: fx.settings.fullWordMatching,
      recursiveScanning: fx.settings.recursiveScanning,
    },
  }
  const db: any = {
    characters: [char],
    username: fx.username,
    loreBookDepth: fx.settings.scanDepth,
    loreBookToken: fx.settings.tokenBudget,
    aiModel: 'openrouter',
    customTokenizer: '',
    currentPluginProvider: undefined,
    useTokenizerCaching: false,
    enableCustomFlags: false,
    botPresets: [],
    globalChatVariables: {},
    templateDefaultVariables: '',
    enabledModules: [],
    modules: [],
    moduleIntergration: '',
  }
  DBState.db = db
  selectedCharID.set(0)
  return char
}

function buildDb() {
  return makeDb(fx.entries, [])
}

test('rp67-turns', async () => {
  const char = buildDb()
  for (const turn of fx.turns) {
    char.chats[0].message = fx.messages.slice(0, 2 * turn)
    char.loreSettings.tokenBudget = fx.settings.tokenBudget
    const capped = await loadLoreBookV3Prompt()
    char.loreSettings.tokenBudget = fx.settings.tokenBudgetUnbounded
    const open = await loadLoreBookV3Prompt()
    char.loreSettings.tokenBudget = fx.settings.tokenBudget
    emit('turn' + turn, {
      capped: capped.actives.map(brief),
      open: open.actives.map(brief),
      matchLog: capped.matchLog.length,
    })
  }
})

test('rp67-modules', async () => {
  buildDb()
  const types: Record<string, string> = {}
  for (const k of Object.keys(fx.probes.promptTypeSamples)) {
    types[k] = detectPromptJSONType(fx.probes.promptTypeSamples[k])
  }
  emit('prompt-json-type', types)

  const converted = stChatConvert(fx.probes.stChatPreset)
  emit('prompt-stchat-convert', converted.map((c: any) => c.type))

  const cbs: Record<string, string> = {}
  for (const k of Object.keys(fx.probes.macroSamples)) {
    cbs[k] = risuChatParser(fx.probes.macroSamples[k])
  }
  emit('cbs-expansion', cbs)

  const changed: Record<string, boolean> = {}
  for (const k of Object.keys(fx.probes.randomMacroSamples)) {
    changed[k] = risuChatParser(fx.probes.randomMacroSamples[k]) !== fx.probes.randomMacroSamples[k]
  }
  emit('cbs-random-macro-changed', changed)

  const parsed = parseChatML(fx.probes.chatml)
  emit('chatml-parse', parsed.map((m: any) => ({ role: m.role, thoughts: m.thoughts.length })))

  const tok: Record<string, number> = {}
  for (const s of fx.probes.tokenSamples) {
    tok[s.label] = await tokenize(s.text)
  }
  emit('tokenize', tok)

  // 能力探针：uid24 的正则键在真实触发路径上是否生效。
  // 同一条目分别喂两个单条窗口：三字窗口「地标图」符合 /地.图/，两字窗口「地图」不符合。
  // 夹具自带的窗口（消息 4「我把地图折好塞进背包。」）属于后者，故 uid24 在五档里都不激活。
  const i24 = fx.uid.indexOf(24)
  const probe = async (text: string) => {
    makeDb([fx.entries[i24]], [{ role: 'user', data: text }])
    const r = await loadLoreBookV3Prompt()
    return r.actives.length
  }
  emit('regex-key-probe', {
    three_char_window: '这里标着地标图。',
    three_char_window_hits: await probe('这里标着地标图。'),
    two_char_window: '我把地图折好塞进背包。',
    two_char_window_hits: await probe('我把地图折好塞进背包。'),
  })
})
