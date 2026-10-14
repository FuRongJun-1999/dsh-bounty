#!/usr/bin/env node
// 原生（不控种）确定性核验：同输入连跑 N 次，每次一个独立 node 进程，且每次带 --no-seed。
//
// 与 verify_determinism.mjs 的分工：
//   verify_determinism.mjs         —— 控种路径（CONTRACT §2 规则 8 的档位种子），产物 raw/sillytavern_determinism.txt
//   本件 verify_determinism_native.mjs —— 关掉控种，量「上游原生随机源」造成的重复差异，产物 raw/sillytavern_determinism_native.txt
//
// 每次运行的 out JSON 写到临时目录，不覆盖 out/sillytavern_P*.json（那份是控种读数）。
// 用法：
//   node bench/roleplay_eval/adapters/sillytavern/verify_determinism_native.mjs --repeats 5

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const EVAL = path.resolve(HERE, '..', '..');            // bench/roleplay_eval
const NAME = 'sillytavern';

function args(argv) {
    const out = {
        repeats: 5,
        profiles: 'P0,P1,P2,P3,P4',
        out: path.join(EVAL, 'raw', NAME + '_determinism_native.txt'),
    };
    for (let i = 0; i < argv.length; i++) {
        if (argv[i] === '--repeats') out.repeats = Number(argv[++i]);
        else if (argv[i] === '--profiles') out.profiles = argv[++i];
        else if (argv[i] === '--out') out.out = argv[++i];
    }
    return out;
}

const sha = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
const shaFile = (p) => sha(fs.readFileSync(p));

// 从一次运行的 out JSON 里抽出「turn → uid → sha256」与「turn → active_uids」。
function shape(file) {
    const doc = JSON.parse(fs.readFileSync(file, 'utf8'));
    const blocks = new Map();
    const active = new Map();
    for (const t of doc.turns || []) {
        const per = new Map();
        for (const b of t.blocks || []) per.set(String(b.uid), String(b.sha256));
        blocks.set(String(t.turn), per);
        active.set(String(t.turn), (t.active_uids || []).join(','));
    }
    return { blocks, active };
}

function varyingUids(shapes) {
    const seen = new Map();
    for (const s of shapes) {
        for (const [turn, per] of s.blocks) {
            for (const [uid, digest] of per) {
                const key = turn + ':' + uid;
                if (!seen.has(key)) seen.set(key, new Set());
                seen.get(key).add(digest);
            }
        }
    }
    return [...seen.entries()].filter(([, v]) => v.size > 1)
        .map(([k, v]) => k + '=' + [...v].map((x) => x.slice(0, 16)).sort().join('|'))
        .sort();
}

function varyingActive(shapes) {
    const seen = new Map();
    for (const s of shapes) {
        for (const [turn, joined] of s.active) {
            if (!seen.has(turn)) seen.set(turn, new Set());
            seen.get(turn).add(joined);
        }
    }
    return [...seen.entries()].filter(([, v]) => v.size > 1).map(([k]) => k).sort();
}

function main() {
    const opt = args(process.argv.slice(2));
    const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'st-native-'));
    const lines = ['# adapter=' + NAME + ' repeats=' + opt.repeats
        + ' scopes=stdout+out processes=independent seeding=off'];
    let failures = 0;
    for (const profile of opt.profiles.split(',').map((s) => s.trim()).filter(Boolean)) {
        const digests = [];
        const outDigests = [];
        const shapes = [];
        for (let i = 0; i < opt.repeats; i++) {
            const outPath = path.join(scratch, NAME + '_' + profile + '_' + i + '.json');
            const proc = spawnSync(process.execPath, [
                path.join(HERE, 'run.mjs'),
                '--data', path.join(EVAL, 'data'),
                '--profile', profile,
                '--out', outPath,
                '--no-seed',
            ], { cwd: EVAL, env: process.env, maxBuffer: 64 * 1024 * 1024 });
            if (proc.status !== 0) {
                failures++;
                lines.push('ERROR ' + NAME + ' profile=' + profile + ' kind=exit-' + proc.status);
            }
            digests.push(sha(proc.stdout));
            outDigests.push(fs.existsSync(outPath) ? shaFile(outPath) : 'missing');
            if (fs.existsSync(outPath)) shapes.push(shape(outPath));
        }
        const identical = new Set(digests).size === 1 && new Set(outDigests).size === 1;
        lines.push('# profile=' + profile + ' stdout_sha256_each_run=' + digests.join(','));
        lines.push('# profile=' + profile + ' out_sha256_each_run=' + outDigests.join(','));
        lines.push('# profile=' + profile + ' varying_blocks=' + (varyingUids(shapes).join(',') || '-'));
        lines.push('# profile=' + profile + ' varying_active_turns=' + (varyingActive(shapes).join(',') || '-'));
        lines.push('DETERMINISM ' + NAME + ' repeats=' + opt.repeats
            + ' identical=' + (identical ? 'true' : 'false') + ' sha=' + digests[digests.length - 1]);
    }
    fs.rmSync(scratch, { recursive: true, force: true });
    lines.push('SUMMARY adapter=' + NAME + ' repeats=' + opt.repeats + ' seeding=off failures=' + failures);
    fs.mkdirSync(path.dirname(path.resolve(opt.out)), { recursive: true });
    fs.writeFileSync(opt.out, lines.join('\n') + '\n', 'utf8');
    for (const line of lines) process.stdout.write(line + '\n');
    return failures ? 1 : 0;
}

process.exit(main());
