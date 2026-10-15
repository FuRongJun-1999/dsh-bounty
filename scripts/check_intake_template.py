# -*- coding: utf-8 -*-
# 生效条件：`--offline-fixture FILE` 读 JSON 数组（元素含 issue 编号与 body），或 `--live` 拉全开放 issue。
# 检查 intake:v1 标记的：①JSON 可解析 ②target 字段在位（repo 为漂移违例）③project 与 target 一致 ④difficulty 在词表内 ⑤impact 在 IMPACT_GRADES 内（severity 为别名、算漂移）。
# 输出：逐条违例；--quiet 时只打一行汇总。退出码 0=无违例 1=有违例。
import argparse, io, json, os, re, subprocess, sys

MARKER_RE = re.compile(r'<!--\s*intake:v1\s*(\{.*?\})\s*-->', re.S)
DIFFICULTY_VOCAB = {'easy', 'medium', 'hard', 'expert'}
IMPACT_VOCAB = {'S', 'A', 'B', 'C', 'D'}
PROJECT_BY_TARGET = {
    'FuRongJun-1999/lingshu': 'lingshu',
    'FuRongJun-1999/dsh-memory': 'memory',
    'FuRongJun-1999/dsh-bounty': 'bounty_site',
    'FuRongJun-1999/dsh-bench': 'bench',
    'TanPowasd/LingShu-prime': 'lingshu',
}

def _extract(body: str):
    m = MARKER_RE.search(body or '')
    if not m:
        return None, 'NO_MARKER'
    try:
        return json.loads(m.group(1)), None
    except Exception as exc:
        return None, 'JSON_FAIL:%s' % exc

def check_marker(n: int, body: str):
    errs, warns = [], []
    d, fail = _extract(body)
    if fail == 'NO_MARKER':
        return ['no intake:v1 marker'], warns
    if fail:
        return ['marker JSON unparseable: %s' % fail], warns
    tgt = d.get('target') or d.get('repo')
    if not tgt:
        errs.append('missing target (and repo)')
    elif 'repo' in d and 'target' not in d:
        warns.append('field drift: repo used instead of target')
    if 'repo' in d:
        warns.append('field drift: repo is not canonical; use target')
    exp_proj = PROJECT_BY_TARGET.get(tgt)
    if 'project' in d and exp_proj and d['project'] != exp_proj:
        errs.append('project=%s but target=%s implies %s' % (d['project'], tgt, exp_proj))
    if 'project' not in d and 'target' in d and not exp_proj:
        errs.append('target=%s not in PROJECT_BY_TARGET mapping' % tgt)
    diff = d.get('difficulty')
    if diff is not None and diff not in DIFFICULTY_VOCAB:
        errs.append('difficulty=%r not in vocab %s' % (diff, sorted(DIFFICULTY_VOCAB)))
    imp = d.get('impact') or d.get('severity') or d.get('severity_hint')
    if imp is not None:
        imp_clean = str(imp).lstrip('P').strip() if str(imp).startswith('P') else str(imp)
        _p2i = {'1':'A','2':'B','3':'C'}
        imp_clean = _p2i.get(imp_clean, imp_clean)
        if imp_clean not in IMPACT_VOCAB:
            errs.append('impact=%r not in vocab %s' % (imp, sorted(IMPACT_VOCAB)))
    if 'severity' in d or 'severity_hint' in d:
        warns.append('field drift: severity used instead of impact')
    return errs, warns

def _live_issues():
    env = dict(os.environ); env['PYTHONUTF8'] = '1'
    r = subprocess.run(['gh','issue','list','-R','FuRongJun-1999/dsh-bounty',
                        '--state','open','--limit','200','--json','number,title'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace',
                       env=env, timeout=120)
    if r.returncode != 0:
        print('LIVE FETCH FAIL: %s' % (r.stderr or '')[:200], file=sys.stderr); sys.exit(1)
    for x in json.loads(r.stdout):
        r2 = subprocess.run(['gh','issue','view',str(x['number']),
                             '-R','FuRongJun-1999/dsh-bounty','--json','body'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            env=env, timeout=60)
        try:
            body = (json.loads(r2.stdout) or {}).get('body') or ''
        except Exception:
            body = ''
        yield x['number'], body

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--offline-fixture')
    ap.add_argument('--live', action='store_true')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()
    rows = []
    if a.offline_fixture:
        for it in json.load(io.open(a.offline_fixture, encoding='utf-8')):
            rows.append((it['issue'], it.get('body') or ''))
    elif a.live:
        rows = list(_live_issues())
    else:
        print('need --offline-fixture or --live', file=sys.stderr); sys.exit(1)
    all_ok = True
    total_e = total_w = 0
    for n, body in rows:
        errs, warns = check_marker(n, body)
        total_e += len(errs); total_w += len(warns)
        if errs:
            all_ok = False
        if not a.quiet:
            for e in errs: print('  E #%d: %s' % (n, e))
            for w in warns: print('  W #%d: %s' % (n, w))
    tag = 'OK' if all_ok else 'FAIL'
    print('intake模板自审：%s · 检查 %d 条 · 违例 %d · 漂移警告 %d' % (tag, len(rows), total_e, total_w))
    sys.exit(0 if all_ok else 1)

if __name__ == '__main__':
    main()