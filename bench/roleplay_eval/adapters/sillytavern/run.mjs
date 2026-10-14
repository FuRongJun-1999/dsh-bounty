#!/usr/bin/env node
// SillyTavern 适配器（角色扮演横评 · 世界书触发 ＋ 上下文预算）。
//
// CLI（CONTRACT §3.3）：
//   node adapters/sillytavern/run.mjs --data <data 目录> --profile P0 --out <out 文件>
//
// 读数来源：起本地 ST 服务，在 chromium 页面里 import 被测方自己的
// public/scripts/world-info.js，用 setWorldInfoSettings ＋ checkWorldInfo(chat, maxContext, true)
// 取激活集、注入顺序、注入块与 dropped。适配器不实现任何触发逻辑。
//
// 只读 --data，只写 --out 与 upstream 的用户数据目录（data/default-user/worlds/）。
// 运行期零网络零凭据：本地 server ＋ 本机 chromium，不请求任何模型 API。

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const UPSTREAM = process.env.ST_UPSTREAM ? path.resolve(process.env.ST_UPSTREAM) : path.join(HERE, 'upstream');
const PORT = Number(process.env.ST_PORT || 8123);
const BASE_URL = 'http://127.0.0.1:' + PORT;
const ADAPTER = 'sillytavern';
const UPSTREAM_REPO = 'https://github.com/SillyTavern/SillyTavern';
const UPSTREAM_COMMIT = '06bde939fb1e9c4c8d8641d810f0a916b5bce127';
const ADAPTER_SCRIPT_VERSION = 'st-roleplay-eval-adapter/0.1';
const ENTRY = 'bench/roleplay_eval/adapters/sillytavern/run.mjs';
const WORLD_NAME = 'roleplay_eval';
const ANCHOR_WORLD_NAME = 'roleplay_eval_p0';
const BUDGET_PERCENT = 25;                 // ST 默认 world_info_budget
const UNBOUNDED_MAX_CONTEXT = 1000000;     // 预算＝25% × 该值＝250000 token，任何注入集都不足以触顶
const DEFAULT_INSERTION_DEPTH = 4;         // ST DEFAULT_DEPTH，仅 at_depth 条目的插入深度用它
const POWERS_OF_TWO = [256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144];

const POSITION_TO_ST = { before_char: 0, after_char: 1, at_depth: 4 };
const ST_TO_POSITION = { 0: 'before_char', 1: 'after_char', 4: 'at_depth' };
// public/scripts/world-info.js:33-38  world_info_logic = { AND_ANY: 0, NOT_ALL: 1, NOT_ANY: 2, AND_ALL: 3 }
const LOGIC_TO_ST = { and_any: 0, not_all: 1, not_any: 2, and_all: 3 };

const UNSUPPORTED = [
    { field: 'group_weight', reason: 'st-group-winner-is-weighted-random-not-max-weight' },
    { field: 'recursion.delay', reason: 'contract-defines-no-delay-rule-and-st-semantics-differs' },
    { field: 'capability_probe', reason: 'fixture-marker-not-an-engine-field' },
    { field: 'budget_chars', reason: 'st-budget-is-token-share-of-max-context-not-chars' },
    { field: 'whole_words_cjk', reason: 'st-whole-word-boundary-treats-cjk-as-non-word-char' },
];

const CAPABILITIES = {
    recursive: true,
    group: true,
    probability: true,
    regex_key: true,
    at_depth: true,
    whole_words_cjk: 'cjk-treated-as-boundary',
};

// ---------- 统一量尺（与 harness/metrics.py 同口径）----------

const sha256 = (s) => crypto.createHash('sha256').update(s, 'utf8').digest('hex');
const chars = (s) => Array.from(s).length;
const bytesOf = (s) => Buffer.byteLength(s, 'utf8');
const fmtUids = (uids) => (uids.length ? uids.slice().sort((a, b) => a - b).join(',') : '-');
const joinUids = (uids) => (uids.length ? uids.join(',') : '-');

const readoutLine = (profile, turn, activeUids, order, charsN, bytesN, dropped) =>
    'READOUT ' + ADAPTER + ' ' + profile + ' turn=' + turn + ' active=' + activeUids.length +
    ' order=' + joinUids(order) + ' chars=' + charsN + ' bytes=' + bytesN + ' dropped=' + fmtUids(dropped);

const capsLine = () => {
    const keys = Object.keys(CAPABILITIES).sort();
    const body = keys.map((k) => JSON.stringify(k) + ':' + JSON.stringify(CAPABILITIES[k])).join(',');
    return 'CAPS ' + ADAPTER + ' {' + body + '}';
};

const unsupportedLine = (u) => 'UNSUPPORTED ' + ADAPTER + ' field=' + u.field + ' reason=' + u.reason;
const errorLine = (profile, kind) => 'ERROR ' + ADAPTER + ' profile=' + profile + ' kind=' + kind;
const timingLine = (profile, ms) =>
    'TIMING ' + ADAPTER + ' profile=' + profile + ' min_ms=' + ms.toFixed(1) +
    ' p50_ms=' + ms.toFixed(1) + ' p95_ms=' + ms.toFixed(1);
const engineNote = (text) => 'ENGINE_NOTE ' + ADAPTER + ' ' + text;

const sortKeysDeep = (value) => {
    if (Array.isArray(value)) return value.map(sortKeysDeep);
    if (value && typeof value === 'object') {
        const out = {};
        for (const k of Object.keys(value).sort()) out[k] = sortKeysDeep(value[k]);
        return out;
    }
    return value;
};

// ---------- CLI ----------

function parseArgs(argv) {
    const out = { data: null, profile: 'P0', out: null, emitTiming: false, stopServer: false };
    for (let i = 0; i < argv.length; i++) {
        const a = argv[i];
        if (a === '--data') out.data = argv[++i];
        else if (a === '--profile') out.profile = argv[++i];
        else if (a === '--out') out.out = argv[++i];
        else if (a === '--emit-timing') out.emitTiming = true;
        else if (a === '--stop-server') out.stopServer = true;
        else throw new Error('未知参数：' + a);
    }
    if (!out.data) throw new Error('缺少 --data');
    if (!out.out) throw new Error('缺少 --out');
    return out;
}

// ---------- 规范世界书 → ST 世界书 ----------

function toStWorldBook(worldbook, prof) {
    const entries = {};
    for (let index = 0; index < worldbook.entries.length; index++) {
        const e = worldbook.entries[index];
        const caseSensitive = Boolean(prof.case_sensitive) || Boolean(e.case_sensitive);
        const matchWholeWords = Boolean(prof.whole_words) || Boolean(e.match_whole_words);
        entries[String(e.uid)] = {
            uid: e.uid,
            key: e.keys.slice(),
            keysecondary: e.secondary_keys.slice(),
            comment: e.comment,
            content: e.content,
            constant: e.constant,
            selective: e.selective,
            selectiveLogic: LOGIC_TO_ST[e.selective_logic],
            addMemo: true,
            order: e.order,
            position: POSITION_TO_ST[e.position],
            disable: !e.enabled,
            excludeRecursion: e.recursion.exclude,
            preventRecursion: e.recursion.prevent,
            delayUntilRecursion: e.recursion.delay,
            displayIndex: index,
            probability: e.probability,
            useProbability: true,
            outletName: '',
            group: e.group === null ? '' : e.group,
            groupOverride: false,
            groupWeight: e.group_weight,
            scanDepth: e.depth,                                  // 契约语义：条目级扫描窗口
            depth: e.depth === null ? DEFAULT_INSERTION_DEPTH : e.depth,  // ST 语义：插入深度
            caseSensitive,
            matchWholeWords,
            useGroupScoring: null,
            automationId: '',
            role: 0,
            vectorized: false,
            sticky: null,
            cooldown: null,
            delay: null,
            triggers: [],
            ignoreBudget: false,
        };
    }
    return { entries };
}

// ---------- 服务 ----------

function ping() {
    return new Promise((resolve) => {
        const req = http.get(BASE_URL + '/', (res) => { res.resume(); resolve(true); });
        req.on('error', () => resolve(false));
        req.setTimeout(3000, () => { req.destroy(); resolve(false); });
    });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function ensureServer() {
    if (await ping()) return { started: false, wait_ms: 0 };
    const logPath = path.join(HERE, 'server.log');
    const out = fs.openSync(logPath, 'a');
    const child = spawn(process.execPath, ['server.js', '--port', String(PORT)], {
        cwd: UPSTREAM, stdio: ['ignore', out, out], detached: true,
    });
    child.unref();
    const t0 = Date.now();
    while (Date.now() - t0 < 300000) {
        if (await ping()) return { started: true, wait_ms: Date.now() - t0 };
        await sleep(1000);
    }
    throw new Error('server-not-up:' + BASE_URL);
}

function stopServer() {
    return new Promise((resolve) => {
        const req = http.request(BASE_URL + '/api/users/logout', { method: 'POST' }, (res) => { res.resume(); resolve(true); });
        req.on('error', () => resolve(false));
        req.end();
    });
}

// ---------- 页面侧读数 ----------

async function readInPage(page, payload) {
    return page.evaluate(async (p) => {
        const wi = await import('./scripts/world-info.js');
        const tokenizers = await import('./scripts/tokenizers.js');

        const settings = {
            world_info: [p.worldName],
            world_info_depth: p.scanDepth,
            world_info_recursive: p.recursive,
            world_info_max_recursion_steps: p.recursiveMaxSteps,
            world_info_budget: p.budgetPercent,
            world_info_budget_cap: 0,
            world_info_include_names: false,
            world_info_case_sensitive: p.caseSensitive,
            world_info_match_whole_words: p.wholeWords,
            world_info_min_activations: 0,
            world_info_min_activations_depth_max: 0,
            world_info_use_group_scoring: false,
            world_info_overflow_alert: false,
        };

        // 与 CONTRACT §1.3 的 seed 对齐：ST 的概率判定与成组择一走 Math.random()（world-info.js:5041／:5453），
        // 无档位种子时不可复现。每次 checkWorldInfo 前装同一序列的可复现发生源，调用后还原。
        const makeRng = (seed) => {
            let s = seed >>> 0;
            return () => {
                s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
                return s / 4294967296;
            };
        };

        const toUidList = (res) => {
            const injected = new Map();
            for (const entry of res.allActivatedEntries.values()) injected.set(entry.uid, entry.content);

            const fixup = new Map();
            const before = [];
            for (const [uid, content] of injected) {
                if (!content) continue;
                const at = res.worldInfoBefore.indexOf(content);
                if (at >= 0) before.push([at, uid, content]);
            }
            before.sort((a, b) => a[0] - b[0]);
            const after = [];
            for (const [uid, content] of injected) {
                if (!content) continue;
                const at = res.worldInfoAfter.indexOf(content);
                if (at >= 0) after.push([at, uid, content]);
            }
            after.sort((a, b) => a[0] - b[0]);
            const depth = [];
            for (const group of (res.WIDepthEntries || [])) {
                for (const content of (group.entries || [])) {
                    for (const [uid, c] of injected) {
                        if (c && c === content) { depth.push([uid, content, group.depth]); break; }
                    }
                }
            }
            const blocks = [];
            const push = (uid, content, position, dep) => {
                if (fixup.has(uid)) return;
                fixup.set(uid, true);
                blocks.push({ uid, content, position, depth: dep });
            };
            for (const [at, uid, content] of before) push(uid, content, 'before_char', null);
            for (const [uid, content, dep] of depth) push(uid, content, 'at_depth', dep === undefined || dep === null ? null : dep);
            for (const [at, uid, content] of after) push(uid, content, 'after_char', null);
            return blocks;
        };

        const runOnce = async (turn, maxContext) => {
            const chatForWI = p.chatTexts.slice(0, 2 * turn).reverse();
            console.debug('[ADAPTER] turn ' + turn + ' maxContext ' + maxContext);
            const original = Math.random;
            Math.random = makeRng((p.seed + turn * 1000003) >>> 0);
            let res;
            try {
                res = await wi.checkWorldInfo(chatForWI, maxContext, true);
            } finally {
                Math.random = original;
            }
            const blocks = toUidList(res);
            const joined = blocks.map((b) => b.content).join('\n');
            const tokens = joined ? await tokenizers.getTokenCountAsync(joined + '\n') : 0;
            return {
                uids: blocks.map((b) => b.uid),
                blocks: blocks,
                tokens: tokens,
                worldInfoBeforeLen: res.worldInfoBefore.length,
                worldInfoAfterLen: res.worldInfoAfter.length,
                depthGroups: (res.WIDepthEntries || []).length,
            };
        };

        const apply = (settings, worldName) => {
            wi.setWorldInfoSettings(Object.assign({ world_info: [worldName] }, settings), []);
        };
        const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

        // ---- 锚点：P0 设置下「预算不构成约束」的最小 2 的幂 ----
        apply(p.anchorSettings, p.anchorWorldName);
        const anchorUnbounded = {};
        for (let turn = 1; turn <= 6; turn++) {
            anchorUnbounded[turn] = await runOnce(turn, p.unboundedMaxContext);
        }
        const anchorProbe = [];
        let anchorMaxContext = null;
        for (const M of p.powers) {
            let same = true;
            for (let turn = 1; turn <= 6; turn++) {
                const r = await runOnce(turn, M);
                if (!sameSet(r.uids, anchorUnbounded[turn].uids)) { same = false; break; }
            }
            anchorProbe.push({ max_context: M, budget_tokens: Math.round(p.budgetPercent * M / 100), non_binding: same });
            if (same) { anchorMaxContext = M; break; }
        }

        // 该档的 maxContext：P3 按 CONTRACT §1.3 的预算比例（600/4000）缩放锚点；
        // P0/P1/P2/P4 的 budget_chars 都等于 4000，直接用锚点。
        const maxContext = (p.profile === 'P3' && anchorMaxContext !== null)
            ? Math.round(anchorMaxContext * p.budgetChars / p.p0BudgetChars)
            : (anchorMaxContext === null ? p.powers[p.powers.length - 1] : anchorMaxContext);

        // ---- 该档读数：无约束注入集（算 dropped）＋ 本档注入集 ----
        apply(p.readSettings, p.worldName);
        if (p.debug) {
            const data = await wi.loadWorldInfo(p.worldName);
            const e24 = data && data.entries ? data.entries['24'] : null;
            console.debug('[DBG] entry24=' + JSON.stringify(e24 ? { key: e24.key, scanDepth: e24.scanDepth, position: e24.position } : null));
            console.debug('[DBG] regex24=' + String(wi.parseRegexFromString('/地.图/')) + ' test=' + (wi.parseRegexFromString('/地.图/') ? wi.parseRegexFromString('/地.图/').test('我把地图折好塞进背包。') : 'n/a'));
        }
        const turns = {};
        for (let turn = 1; turn <= 6; turn++) {
            turns[turn] = {
                unbounded: await runOnce(turn, p.unboundedMaxContext),
                bounded: await runOnce(turn, maxContext),
            };
        }

        return {
            anchorProbe: anchorProbe,
            anchorMaxContext: anchorMaxContext,
            anchorUnbounded: anchorUnbounded,
            maxContext: maxContext,
            turns: turns,
        };
    }, payload);
}

// ---------- 主流程 ----------

async function main() {
    const t0 = Date.now();
    let args;
    try {
        args = parseArgs(process.argv.slice(2));
    } catch (err) {
        process.stdout.write(errorLine('P0', 'bad-cli') + '\n');
        process.stderr.write(String(err.message) + '\n');
        return 2;
    }
    const profile = args.profile;
    const errors = [];

    const dataDir = path.resolve(args.data);
    const worldbook = JSON.parse(fs.readFileSync(path.join(dataDir, 'worldbook.json'), 'utf8'));
    const chat = fs.readFileSync(path.join(dataDir, 'chat.jsonl'), 'utf8').split('\n')
        .filter((line) => line.trim()).map((line) => JSON.parse(line));
    const profiles = JSON.parse(fs.readFileSync(path.join(dataDir, 'profiles.json'), 'utf8'));
    const prof = profiles.profiles.find((x) => x.name === profile);
    if (!prof) {
        process.stdout.write(errorLine(profile, 'unknown-profile') + '\n');
        return 1;
    }
    const p0prof = profiles.profiles.find((x) => x.name === 'P0');

    // 服务先起，再写世界书文件（首次启动会生成 default-user 目录）。
    const serverInfo = await ensureServer();

    const worldsDir = path.join(UPSTREAM, 'data', 'default-user', 'worlds');
    fs.mkdirSync(worldsDir, { recursive: true });
    const worldFile = path.join(worldsDir, WORLD_NAME + '.json');
    const anchorWorldFile = path.join(worldsDir, ANCHOR_WORLD_NAME + '.json');
    const worldText = JSON.stringify(toStWorldBook(worldbook, prof), null, 1) + '\n';
    const anchorWorldText = JSON.stringify(toStWorldBook(worldbook, p0prof), null, 1) + '\n';
    fs.writeFileSync(worldFile, worldText, 'utf8');
    fs.writeFileSync(anchorWorldFile, anchorWorldText, 'utf8');

    const requireSt = createRequire(path.join(UPSTREAM, 'tests', 'package.json'));
    const { chromium } = requireSt('@playwright/test');
    const launchOptions = process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {};
    const tBrowser = Date.now();
    const browser = await chromium.launch(launchOptions);
    const page = await browser.newPage();
    if (process.env.ST_DUMP_CONSOLE === '1') {
        page.on('console', (msg) => {
            const text = msg.text();
            if (text.startsWith('[WI]') || text.startsWith('[ADAPTER]') || text.startsWith('[DBG]')) process.stderr.write(text + '\n');
        });
    }
    const tLoad = Date.now();
    await page.goto(BASE_URL + '/');
    if (await page.locator('body.login').count() > 0) {
        const selects = page.locator('#userList .userSelect');
        for (let i = (await selects.count()) - 1; i >= 0; i--) {
            await selects.nth(i).click();
            const ok = await page.waitForURL((u) => u.toString().startsWith(BASE_URL) && u.pathname !== '/login', { timeout: 5000 }).then(() => true, () => false);
            if (ok) break;
        }
    }
    await page.waitForFunction('document.getElementById("preloader") === null', { timeout: 180000 });
    const tReady = Date.now();

    // 档位设置 → ST 的 world_info_* 全局设置（setWorldInfoSettings 的入参形状）。
    const settingsOf = (pf) => ({
        world_info_depth: Number(pf.scan_depth),
        world_info_recursive: Boolean(pf.recursive),
        world_info_max_recursion_steps: Boolean(pf.recursive) ? 1 + Number(pf.recursive_max_depth || 3) : 0,
        world_info_budget: BUDGET_PERCENT,
        world_info_budget_cap: 0,
        world_info_include_names: false,
        world_info_case_sensitive: Boolean(pf.case_sensitive),
        world_info_match_whole_words: Boolean(pf.whole_words),
        world_info_min_activations: 0,
        world_info_min_activations_depth_max: 0,
        world_info_use_group_scoring: false,
        world_info_overflow_alert: false,
    });

    const payload = {
        worldName: WORLD_NAME,
        anchorWorldName: ANCHOR_WORLD_NAME,
        profile: profile,
        budgetPercent: BUDGET_PERCENT,
        unboundedMaxContext: UNBOUNDED_MAX_CONTEXT,
        seed: Number(profiles.seed || 20261014),
        powers: POWERS_OF_TWO,
        chatTexts: chat.map((m) => m.text),
        budgetChars: Number(prof.budget_chars),
        p0BudgetChars: Number(p0prof.budget_chars),
        anchorSettings: settingsOf(p0prof),
        readSettings: settingsOf(prof),
        debug: process.env.ST_DUMP_CONSOLE === '1',
    };
    const measured = await readInPage(page, payload);
    const tDone = Date.now();
    await browser.close();

    const anchorMaxContext = measured.anchorMaxContext;
    const maxContext = measured.maxContext;
    if (anchorMaxContext === null) errors.push({ kind: 'anchor-not-found' });
    const budgetTokens = Math.round(BUDGET_PERCENT * maxContext / 100);

    const turns = [];
    const contentDump = [];
    for (let turn = 1; turn <= 6; turn++) {
        const bounded = measured.turns[turn].bounded;
        const unbounded = measured.turns[turn].unbounded;
        const order = bounded.blocks.map((b) => b.uid);
        const active = order.slice().sort((a, b) => a - b);
        const dropped = unbounded.uids.filter((u) => !active.includes(u)).sort((a, b) => a - b);
        const blocks = bounded.blocks.map((b) => ({
            uid: b.uid,
            position: b.position,
            depth: b.position === 'at_depth' ? (b.depth === null ? DEFAULT_INSERTION_DEPTH : b.depth) : null,
            chars: chars(b.content),
            bytes: bytesOf(b.content),
            sha256: sha256(b.content),
            content: b.content,   // 仅用于 ST_DUMP_CONTENT；写进 out 前会被剔除
        }));
        let totalChars = 0;
        let totalBytes = 0;
        for (const b of blocks) {
            totalChars += b.chars;
            totalBytes += b.bytes;
            contentDump.push({ turn: turn, uid: b.uid, position: b.position, depth: b.depth,
                chars: b.chars, bytes: b.bytes, sha256: b.sha256, content: b.content });
        }
        turns.push({
            turn: turn,
            profile: profile,
            history_len: 2 * turn,
            active_uids: active,
            inject_order: order,
            blocks: blocks.map(({ content, ...rest }) => rest),
            totals: { active: active.length, chars: totalChars, bytes: totalBytes, dropped_uids: dropped },
            engine_notes: [
                'max_context=' + maxContext,
                'budget_tokens=' + budgetTokens,
                'unbounded_max_context=' + UNBOUNDED_MAX_CONTEXT,
                'unbounded_active=' + unbounded.uids.length,
                'unbounded_tokens=' + unbounded.tokens,
                'dropped_by_budget_only=' + (dropped.length ? dropped.join(',') : '-'),
            ].sort(),
        });
    }

    const doc = {
        adapter: ADAPTER,
        upstream_repo: UPSTREAM_REPO,
        upstream_commit: UPSTREAM_COMMIT,
        adapter_version: ADAPTER_SCRIPT_VERSION,
        engine_env: {
            node: process.version,
            entry: ENTRY,
            engine_version: JSON.parse(fs.readFileSync(path.join(UPSTREAM, 'package.json'), 'utf8')).version,
            world_info_engine: 'public/scripts/world-info.js',
            browser: process.env.CHROME_PATH ? 'CHROME_PATH' : 'playwright-default',
            server: 'node server.js --port ' + PORT,
            world_file: 'upstream/data/default-user/worlds/' + WORLD_NAME + '.json',
            anchor_world_file: 'upstream/data/default-user/worlds/' + ANCHOR_WORLD_NAME + '.json',
            network: 'local-server-and-local-chromium-only',
        },
        capabilities: CAPABILITIES,
        turns: turns,
        unsupported: UNSUPPORTED,
        errors: errors,
    };

    // 注入正文只进 stderr（ST_DUMP_CONTENT=1）：正文不是读数行，缺省不打印。
    if (process.env.ST_DUMP_CONTENT === '1') {
        for (const b of contentDump) {
            process.stderr.write('[RAW] adapter=' + ADAPTER + ' profile=' + profile + ' turn=' + b.turn +
                ' uid=' + b.uid + ' position=' + b.position + ' depth=' + b.depth +
                ' chars=' + b.chars + ' bytes=' + b.bytes + ' sha256=' + b.sha256 +
                ' content=' + JSON.stringify(b.content) + '\n');
        }
    }

    process.stdout.write(capsLine() + '\n');
    for (const t of turns) {
        process.stdout.write(readoutLine(profile, t.turn, t.active_uids, t.inject_order,
            t.totals.chars, t.totals.bytes, t.totals.dropped_uids) + '\n');
    }
    for (const u of UNSUPPORTED) process.stdout.write(unsupportedLine(u) + '\n');
    process.stdout.write(engineNote('profile=' + profile + ' max_context=' + maxContext +
        ' budget_tokens=' + budgetTokens +
        ' anchor_max_context=' + anchorMaxContext +
        ' budget_delta_vs_p0=' + (budgetTokens - Math.round(BUDGET_PERCENT * anchorMaxContext / 100))) + '\n');
    process.stdout.write(engineNote('anchor_probe=' + measured.anchorProbe.map((x) => x.max_context + ':' + (x.non_binding ? 'non-binding' : 'binding')).join(',')) + '\n');
    for (const e of errors) process.stdout.write(errorLine(profile, e.kind) + '\n');
    // 计时行只在 --emit-timing 下打印：墙钟值不是读数，缺省打印会破坏 stdout 的逐次一致性。
    if (args.emitTiming) {
        process.stdout.write(engineNote('server_started=' + serverInfo.started + ' server_wait_ms=' + serverInfo.wait_ms +
            ' browser_ms=' + (tLoad - tBrowser) + ' page_ready_ms=' + (tReady - tLoad) +
            ' evaluate_ms=' + (tDone - tReady)) + '\n');
        process.stdout.write(timingLine(profile, tDone - t0) + '\n');
    }

    fs.mkdirSync(path.dirname(path.resolve(args.out)), { recursive: true });
    fs.writeFileSync(path.resolve(args.out), JSON.stringify(sortKeysDeep(doc), null, 1) + '\n', 'utf8');

    if (args.stopServer) await stopServer();
    return errors.length ? 1 : 0;
}

main().then((code) => process.exit(code)).catch((err) => {
    process.stdout.write(errorLine('P0', 'adapter-crash') + '\n');
    process.stderr.write((err && err.stack ? err.stack : String(err)) + '\n');
    process.exit(1);
});
