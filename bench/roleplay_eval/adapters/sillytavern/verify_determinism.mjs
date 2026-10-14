#!/usr/bin/env node
// 确定性核验：同输入连跑 N 次（每次一个独立 node 进程），比对 stdout 与 out JSON 的 sha256。
//
// 用法：
//   node bench/roleplay_eval/adapters/sillytavern/verify_determinism.mjs --repeats 5
//
// 产物：raw/sillytavern_determinism.txt（SHA 行 ＋ DETERMINISM 行，行语法见 CONTRACT §7.2）。

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const EVAL = path.resolve(HERE, '..', '..');            // bench/roleplay_eval
const NAME = 'sillytavern';

function args(argv) {
    const out = { repeats: 5, profiles: 'P0,P1,P2,P3,P4', out: path.join(EVAL, 'raw', NAME + '_determinism.txt') };
    for (let i = 0; i < argv.length; i++) {
        if (argv[i] === '--repeats') out.repeats = Number(argv[++i]);
        else if (argv[i] === '--profiles') out.profiles = argv[++i];
        else if (argv[i] === '--out') out.out = argv[++i];
    }
    return out;
}

const sha = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
const shaFile = (p) => sha(fs.readFileSync(p));

function main() {
    const opt = args(process.argv.slice(2));
    const lines = ['# adapter=' + NAME + ' repeats=' + opt.repeats + ' scopes=stdout+out processes=independent'];
    let failures = 0;
    for (const profile of opt.profiles.split(',').map((s) => s.trim()).filter(Boolean)) {
        const outPath = path.join(EVAL, 'out', NAME + '_' + profile + '.json');
        const digests = [];
        const outDigests = [];
        for (let i = 0; i < opt.repeats; i++) {
            const proc = spawnSync(process.execPath, [
                path.join(HERE, 'run.mjs'),
                '--data', path.join(EVAL, 'data'),
                '--profile', profile,
                '--out', outPath,
            ], { cwd: EVAL, env: process.env, maxBuffer: 64 * 1024 * 1024 });
            if (proc.status !== 0) {
                failures++;
                lines.push('ERROR ' + NAME + ' profile=' + profile + ' kind=exit-' + proc.status);
            }
            digests.push(sha(proc.stdout));
            outDigests.push(fs.existsSync(outPath) ? shaFile(outPath) : 'missing');
            lines.push('SHA ' + outDigests[outDigests.length - 1] + ' file=out/' + NAME + '_' + profile + '.json');
        }
        const identical = new Set(digests).size === 1 && new Set(outDigests).size === 1;
        if (!identical) failures++;
        lines.push('# profile=' + profile + ' stdout_sha256_each_run=' + digests.join(','));
        lines.push('DETERMINISM ' + NAME + ' repeats=' + opt.repeats + ' identical=' + (identical ? 'true' : 'false') + ' sha=' + digests[digests.length - 1]);
    }
    fs.writeFileSync(opt.out, lines.join('\n') + '\n', 'utf8');
    for (const line of lines) process.stdout.write(line + '\n');
    process.stdout.write('SUMMARY adapter=' + NAME + ' repeats=' + opt.repeats + ' failures=' + failures + '\n');
    return failures ? 1 : 0;
}

process.exit(main());
