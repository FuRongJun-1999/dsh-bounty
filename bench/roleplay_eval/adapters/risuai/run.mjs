#!/usr/bin/env node
/**
 * RisuAI 适配器（CONTRACT §3.3）
 *
 *   node bench/roleplay_eval/adapters/risuai/run.mjs --data data --profile P0 --out out/risuai_P0.json
 *
 * 做法：把规范世界书 / 对话历史 / 档位翻译成 RisuAI 的 loreBook 与 loreSettings，
 * 写进 upstream/src/ts/poc/rp67_fixture.json；把 inject/rp67_adapter.test.ts 复制到
 * upstream/src/ts/poc/ 后跑 vitest，从 stdout 取回 RisuAI 真实算法产出的读数，
 * 再按 §7.2 的 READOUT/DIFF/KPI 行语法打印，并按 §3.2 写 --out。
 *
 * 被测算法全部是上游代码（见 inject/rp67_adapter.test.ts 头部）；本文件只做字段翻译与格式化。
 * 运行期：不联网、不用凭据、不调 LLM。默认 engine=vitest；engine=permissioned 用
 * node --permission（不给 --allow-net）跑同一批用例，作为零网络证据。
 */

import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const BENCH = resolve(HERE, '..', '..')            // bench/roleplay_eval
const UPSTREAM = join(HERE, 'upstream')
const TEST_SRC = join(HERE, 'inject', 'rp67_adapter.test.ts')
const TEST_DST = join(UPSTREAM, 'src', 'ts', 'poc', 'rp67_adapter.test.ts')
const FIXTURE_DST = join(UPSTREAM, 'src', 'ts', 'poc', 'rp67_fixture.json')

let docPosRaw = []
const ADAPTER = 'risuai'
const UPSTREAM_REPO = 'https://github.com/kwaroran/Risuai'
const UPSTREAM_COMMIT = '454e5e207747399f43a4788f5f08ecd5aa291550'
const ENTRY = 'bench/roleplay_eval/adapters/risuai/run.mjs'
const ENGINE_VERSION = 'Risuai@454e5e2'

const CAPABILITIES = {
  recursive: true,
  group: false,
  probability: false,
  regex_key: true,
  at_depth: true,
  whole_words_cjk: 'no_match_cjk',
}

const UNSUPPORTED = [
  { field: 'probability', reason: 'upstream-decorator-uses-Math.random-lorebook.svelte.ts:494' },
  { field: 'case_sensitive', reason: 'upstream-folds-case-unconditionally-lorebook.svelte.ts:182' },
  { field: 'group', reason: 'no-group-field-in-loreBook-database.svelte.ts:1338' },
  { field: 'group_weight', reason: 'no-group-field-in-loreBook-database.svelte.ts:1338' },
  { field: 'recursion.prevent', reason: 'no-upstream-field' },
  { field: 'recursion.delay', reason: 'no-upstream-field' },
  { field: 'capability_probe', reason: 'fixture-side-marker-no-upstream-field' },
  { field: 'budget_chars', reason: 'upstream-budget-counts-tokens-not-chars' },
  { field: 'recursive_max_depth', reason: 'upstream-loops-to-fixpoint-without-depth-cap' },
  { field: 'seed', reason: 'no-effect-because-probability-unsupported' },
]

// ---- 小工具 ----

function sha256Text(s) {
  return createHash('sha256').update(s, 'utf8').digest('hex')
}
function charsOf(s) {
  return Array.from(s).length
}
function bytesOf(s) {
  return Buffer.byteLength(s, 'utf8')
}
function fmtUids(uids) {
  const xs = [...new Set(uids)].map(Number).sort((a, b) => a - b)
  return xs.length ? xs.join(',') : '-'
}
function joinUids(seq) {
  return seq.length ? seq.map(Number).join(',') : '-'
}
function pydump(v, indent = 0) {
  const pad = ' '.repeat(indent)
  const pad2 = ' '.repeat(indent + 1)
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'number') return String(v)
  if (typeof v === 'string') return JSON.stringify(v)
  if (Array.isArray(v)) {
    if (!v.length) return '[]'
    return '[\n' + v.map((x) => pad2 + pydump(x, indent + 1)).join(',\n') + '\n' + pad + ']'
  }
  const keys = Object.keys(v).sort()
  if (!keys.length) return '{}'
  return '{\n' + keys.map((k) => pad2 + JSON.stringify(k) + ': ' + pydump(v[k], indent + 1)).join(',\n') + '\n' + pad + '}'
}

function argValue(argv, name, fallback) {
  const i = argv.indexOf('--' + name)
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : fallback
}

function resolveDir(p) {
  if (isAbsolute(p)) return p
  for (const base of [process.cwd(), BENCH]) {
    const c = resolve(base, p)
    if (existsSync(c)) return c
  }
  return resolve(BENCH, p)
}

// ---- 规范字段 → RisuAI 字段 ----

/**
 * 装饰器拼装只用上游自己实现的 @@ 指令（lorebook.svelte.ts:305 起的 CCardLib.decorator.parse 分派）：
 *   position=at_depth → @@depth；position=after_char → @@position after_desc；before_char → 不上装饰器（上游默认 pos=""）
 *   depth（窗口覆盖）→ @@scan_depth（上游 :375）；secondkey 的 and_all → 多行 @@additional_keys（:444，逐行一条必须命中的查询）
 *   secondkey 的 not_any → @@exclude_keys（:451，负向查询）；match_whole_words → @@match_full_word（:466）
 *   recursion.exclude → @@no_recursive_search（:512）；enabled=false → @@dont_activate（:482）
 */
function toRisuEntry(e) {
  const dec = []
  if (e.position === 'at_depth' && e.depth !== null) dec.push('@@depth ' + e.depth)
  if (e.position === 'after_char') dec.push('@@position after_desc')
  if (e.depth !== null) dec.push('@@scan_depth ' + e.depth)
  if (e.selective && e.selective_logic === 'and_all') {
    for (const k of e.secondary_keys) dec.push('@@additional_keys ' + k)
  }
  if (e.selective && e.selective_logic === 'not_any' && e.secondary_keys.length) {
    dec.push('@@exclude_keys ' + e.secondary_keys.join(' '))
  }
  if (e.match_whole_words) dec.push('@@match_full_word')
  if (e.recursion && e.recursion.exclude) dec.push('@@no_recursive_search')
  if (!e.enabled) dec.push('@@dont_activate')

  const andAny = e.selective && e.selective_logic === 'and_any'
  const out = {
    key: e.keys.join(','),
    secondkey: andAny ? e.secondary_keys.join(',') : '',
    insertorder: e.order,
    comment: e.comment,
    content: dec.length ? dec.join('\n') + '\n' + e.content : e.content,
    mode: 'normal',
    alwaysActive: !!e.constant,
    selective: andAny,
    id: 'rp67-' + e.uid,
  }
  if (e.keys.length === 1 && /^\/([\s\S]*)\/([dgimsuvy]*)$/.test(e.keys[0])) out.useRegex = true
  return out
}

function roleToRisu(role) {
  // 触发只看正文；role 只影响上游 matchLog 的标签文字，不影响命中判定。
  return role === 'user' ? 'user' : 'char'
}

// ---- 主流程 ----

function main() {
  const argv = process.argv.slice(2)
  const profileName = argValue(argv, 'profile', 'P0')
  const outArg = argValue(argv, 'out', null)
  const engine = argValue(argv, 'engine', 'vitest')
  const dataDir = resolveDir(argValue(argv, 'data', 'data'))

  if (!existsSync(TEST_SRC)) return fatal('adapter-files-missing', 'missing ' + TEST_SRC)
  if (!existsSync(join(UPSTREAM, 'package.json'))) {
    return fatal('upstream-missing', 'run adapters/risuai/fetch_upstream.sh && setup.sh first')
  }

  const worldbook = JSON.parse(readFileSync(join(dataDir, 'worldbook.json'), 'utf8'))
  const chat = readFileSync(join(dataDir, 'chat.jsonl'), 'utf8')
    .split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l))
  const profiles = JSON.parse(readFileSync(join(dataDir, 'profiles.json'), 'utf8'))
  const profile = (profiles.profiles || []).find((p) => p.name === profileName)
  if (!profile) return fatal('unknown-profile', 'profile=' + profileName)

  const entries = worldbook.entries
  const byComment = new Map()
  for (const e of entries) {
    if (byComment.has(e.comment)) return fatal('duplicate-comment', 'comment=' + e.comment)
    byComment.set(e.comment, e.uid)
  }

  const fixture = {
    characterName: 'RP67',
    username: 'Traveler',
    uid: entries.map((e) => e.uid),
    entries: entries.map(toRisuEntry),
    messages: chat.map((m) => ({ role: roleToRisu(m.role), data: m.text })),
    turns: [1, 2, 3, 4, 5, 6],
    settings: {
      scanDepth: profile.scan_depth,
      tokenBudget: profile.budget_chars,
      tokenBudgetUnbounded: 1000000000,
      fullWordMatching: !!profile.whole_words,
      recursiveScanning: !!profile.recursive,
    },
    probes: {
      promptTypeSamples: {
        stchat: JSON.stringify({
          chat_completion_source: 'claude',
          prompts: [{ identifier: 'main', content: 'M', role: 'system' }],
          prompt_order: [{ order: [{ identifier: 'main', enabled: true }] }],
        }),
        parameters: JSON.stringify({ temp: 1, rep_pen: 1, min_length: 0 }),
        stcontext: JSON.stringify({ story_string: 'S', chat_start: 'C' }),
        stinst: JSON.stringify({ input_sequence: 'I', output_sequence: 'O' }),
        unsupported: JSON.stringify({ hello: 1 }),
        broken: '{not json',
      },
      stChatPreset: {
        prompts: [
          { identifier: 'main', content: 'MAIN', role: 'system' },
          { identifier: 'jailbreak', content: 'JAIL', role: 'system' },
          { identifier: 'chatHistory', content: '', role: 'system' },
          { identifier: 'worldInfoBefore', content: '', role: 'system' },
          { identifier: 'charDescription', content: '', role: 'system' },
          { identifier: 'personaDescription', content: '', role: 'system' },
          { identifier: 'unknownThing', content: 'RAW', role: 'assistant' },
        ],
        prompt_order: [{
          order: [
            { identifier: 'main', enabled: true },
            { identifier: 'jailbreak', enabled: false },
            { identifier: 'chatHistory', enabled: true },
            { identifier: 'worldInfoBefore', enabled: true },
            { identifier: 'charDescription', enabled: true },
            { identifier: 'personaDescription', enabled: true },
            { identifier: 'unknownThing', enabled: true },
          ],
        }],
      },
      macroSamples: {
        plain: 'The sky is clear.',
        upper: '{{upper::capital}}',
        'if-true': '{{#if 1}}ALPHA{{/}}',
        'if-false': '{{#if 0}}ALPHA{{/}}',
        user: '{{user}}',
      },
      randomMacroSamples: { 'uid25-content': entries.find((e) => e.uid === 25).content },
      chatml: '<|im_start|>system\nYou are RP67.<|im_end|>\n<|im_start|>user\nHi<|im_end|>\n',
      tokenSamples: [1, 2, 8, 20, 24].map((u) => ({
        label: 'uid' + u,
        text: entries.find((e) => e.uid === u).content,
      })),
    },
  }

  mkdirSync(dirname(TEST_DST), { recursive: true })
  writeFileSync(FIXTURE_DST, JSON.stringify(fixture, null, 1) + '\n', 'utf8')
  copyFileSync(TEST_SRC, TEST_DST)

  const runRes = runVitest(engine)
  if (runRes.error) return fatal('engine-spawn-' + runRes.error, 'engine=' + engine)
  if (runRes.rc !== 0) {
    process.stderr.write(String(runRes.stderr || '').slice(-4000))
    return fatal('vitest-exit-' + runRes.rc, 'engine=' + engine)
  }

  const blocks = parseReadings(runRes.stdout)
  if (!blocks.turn) return fatal('no-readout-blocks', 'engine=vitest')

  const doc = buildDoc(blocks, entries, byComment, profileName)
  const text = pydump(doc) + '\n'
  if (outArg) {
    const p = isAbsolute(outArg) ? outArg : resolve(process.cwd(), outArg)
    mkdirSync(dirname(p), { recursive: true })
    writeFileSync(p, text, 'utf8')
  }

  // §7.2 读数行：CAPS / READOUT / UNSUPPORTED / ERROR。EXTRA 行是本适配器自加的附注，非契约读数。
  process.stdout.write('CAPS ' + ADAPTER + ' ' + JSON.stringify(CAPABILITIES) + '\n')
  for (const t of doc.turns) {
    process.stdout.write(
      'READOUT ' + ADAPTER + ' ' + profileName + ' turn=' + t.turn +
      ' active=' + t.active_uids.length +
      ' order=' + joinUids(t.inject_order) +
      ' chars=' + t.totals.chars +
      ' bytes=' + t.totals.bytes +
      ' dropped=' + fmtUids(t.totals.dropped_uids) + '\n')
  }
  for (const u of doc.unsupported) {
    process.stdout.write('UNSUPPORTED ' + ADAPTER + ' field=' + u.field + ' reason=' + u.reason + '\n')
  }
  for (const e of doc.errors) {
    process.stdout.write('ERROR ' + ADAPTER + ' profile=' + profileName + ' kind=' + e.kind + '\n')
  }
  process.stdout.write('EXTRA ' + ADAPTER + ' ' + profileName + ' ' + extraLine(doc, blocks) + '\n')
  process.stdout.write('JSON ' + ADAPTER + ' ' + profileName + ' ' + JSON.stringify(doc) + '\n')
  return doc.errors.length ? 1 : 0
}

function extraLine(doc, blocks) {
  void doc
  const ml = [1, 2, 3, 4, 5, 6].map((k) => (blocks.turn[k] || {}).matchLog).join(',')
  const diff = doc.turns.flatMap((t) => t.engine_notes.filter((n) => n.startsWith('prompt_diff=')))
  const cbs = blocks['cbs-random-macro-changed'] || {}
  const parts = [
    'matchlog=' + (ml || '-'),
    'pos_raw=' + (docPosRaw.length ? docPosRaw.join(',') : '-'),
    'prompt_diff=' + (diff.length ? diff.join(',') : '-'),
    'uid25_roll_cbs_expanded=' + Object.values(cbs).join(','),
    'regex_key_probe_hits=' + JSON.stringify([
      (blocks['regex-key-probe'] || {}).three_char_window_hits,
      (blocks['regex-key-probe'] || {}).two_char_window_hits,
    ]),
    'prompt_json_type=' + JSON.stringify(blocks['prompt-json-type'] || {}),
    'cbs_upper=' + JSON.stringify((blocks['cbs-expansion'] || {}).upper),
    'chatml_roles=' + (blocks['chatml-parse'] || []).map((m) => m.role).join(','),
    'tokens=' + JSON.stringify(blocks.tokenize || {}),
  ]
  return parts.join(' ')
}

function runVitest(engine) {
  const file = 'src/ts/poc/rp67_adapter.test.ts'
  let cmd
  let args
  if (engine === 'permissioned') {
    cmd = process.execPath
    args = [
      '--permission',
      '--allow-fs-read=*',
      '--allow-fs-write=*',
      '--allow-worker',
      '--allow-addons',
      '--allow-child-process',
      join('node_modules', 'vitest', 'vitest.mjs'),
      'run',
      file,
    ]
  } else {
    cmd = 'npx'
    args = ['--no-install', 'vitest', 'run', file]
  }
  const r = spawnSync(cmd, args, {
    cwd: UPSTREAM,
    encoding: 'utf8',
    maxBuffer: 128 * 1024 * 1024,
    shell: process.platform === 'win32' && engine !== 'permissioned',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', CI: '1', NO_COLOR: '1' },
  })
  return { rc: r.status, stdout: r.stdout || '', stderr: r.stderr || '', error: r.error ? String(r.error.message) : null }
}

function parseReadings(stdout) {
  const out = {}
  for (const line of stdout.split(/\r?\n/)) {
    const at = line.indexOf('RPREADING|')
    if (at < 0) continue
    const rest = line.slice(at + 'RPREADING|'.length)
    const sep = rest.indexOf('|')
    if (sep < 0) continue
    const tag = rest.slice(0, sep)
    try {
      out[tag] = JSON.parse(rest.slice(sep + 1))
    } catch (err) {
      throw new Error('RPREADING parse failed for ' + tag + ': ' + String(err))
    }
  }
  const turns = {}
  for (const k of Object.keys(out)) {
    if (/^turn\d+$/.test(k)) turns[Number(k.slice(4))] = out[k]
  }
  out.turn = turns
  return out
}

function contractPosition(rawPos, depth) {
  if (rawPos === 'depth' || rawPos === 'reverse_depth') return { position: 'at_depth', depth: depth >= 1 ? depth : 1 }
  if (rawPos === 'after_desc') return { position: 'after_char', depth: null }
  return { position: 'before_char', depth: null }
}

function buildDoc(blocks, entries, byComment, profileName) {
  const errors = []
  const contentByUid = new Map(entries.map((e) => [e.uid, e.content]))
  const turns = []
  const posRaw = []
  for (const turn of [1, 2, 3, 4, 5, 6]) {
    const raw = blocks.turn[turn]
    if (!raw) {
      errors.push({ kind: 'missing-turn-' + turn })
      continue
    }
    const notes = []
    const toUid = (source) => {
      const uid = byComment.get(source)
      if (uid === undefined) notes.push('unknown-source=' + source)
      return uid
    }
    const capped = raw.capped.map((a) => ({ ...a, uid: toUid(a.source) })).filter((a) => a.uid !== undefined)
    const open = raw.open.map((a) => ({ ...a, uid: toUid(a.source) })).filter((a) => a.uid !== undefined)
    const cappedUids = new Set(capped.map((a) => a.uid))

    const blocksOut = []
    let totC = 0
    let totB = 0
    for (const a of capped) {
      const body = a.prompt
      const want = contentByUid.get(a.uid)
      if (want !== body) notes.push('prompt_diff=uid' + a.uid)
      const pos = contractPosition(a.pos, a.depth)
      if (a.pos && a.pos !== 'depth' && a.pos !== 'reverse_depth' && a.pos !== 'after_desc' && a.pos !== '') {
        notes.push('pos_unmapped=uid' + a.uid + ':' + a.pos)
      }
      const c = charsOf(body)
      const b = bytesOf(body)
      totC += c
      totB += b
      blocksOut.push({
        uid: a.uid,
        position: pos.position,
        depth: pos.depth,
        chars: c,
        bytes: b,
        sha256: sha256Text(body),
      })
      if (a.pos) posRaw.push('uid' + a.uid + ':' + a.pos)
    }
    const dropped = open.map((a) => a.uid).filter((u) => !cappedUids.has(u)).sort((x, y) => x - y)

    turns.push({
      turn,
      profile: profileName,
      history_len: 2 * turn,
      active_uids: blocksOut.map((b) => b.uid).slice().sort((x, y) => x - y),
      inject_order: blocksOut.map((b) => b.uid),
      blocks: blocksOut.map((b) => ({
        uid: b.uid, position: b.position, depth: b.depth, chars: b.chars, bytes: b.bytes, sha256: b.sha256,
      })),
      totals: { active: blocksOut.length, chars: totC, bytes: totB, dropped_uids: dropped },
      engine_notes: [...new Set(notes)].sort(),
    })
  }
  docPosRaw = posRaw

  return {
    adapter: ADAPTER,
    upstream_repo: UPSTREAM_REPO,
    upstream_commit: UPSTREAM_COMMIT,
    adapter_version: ENGINE_VERSION,
    engine_env: {
      node: process.version,
      entry: ENTRY,
      engine_cmd: 'npx --no-install vitest run src/ts/poc/rp67_adapter.test.ts',
      network: 'none',
      llm: 'none',
    },
    capabilities: CAPABILITIES,
    turns,
    unsupported: UNSUPPORTED,
    errors,
  }
}

function fatal(kind, detail) {
  process.stdout.write('ERROR ' + ADAPTER + ' profile=- kind=' + kind + '\n')
  process.stderr.write('FATAL ' + kind + ' ' + detail + '\n')
  return 1
}

process.exitCode = main()
