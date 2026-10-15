# -*- coding: utf-8 -*-
# 守卫：check_intake_template.py 的 --mutate 定点变异自证。
import io, json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, 'scripts', 'check_intake_template.py')
def _run_fixture(rows):
    fd, path = tempfile.mkstemp(suffix='.json'); os.close(fd)
    io.open(path, 'w', encoding='utf-8').write(json.dumps(rows))
    env = dict(os.environ); env['PYTHONUTF8'] = '1'
    r = subprocess.run([sys.executable, '-X', 'utf8', SCRIPT, '--offline-fixture', path],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=60)
    os.unlink(path)
    return r
GOOD = [{'issue': 1, 'body': 'x <!-- intake:v1 {"project":"memory","difficulty":"medium","impact":"B","target":"FuRongJun-1999/dsh-memory"} -->'}]
def test_clean_fixture_passes():
    r = _run_fixture(GOOD)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
def test_repo_drift_warns():
    rows = [{'issue': 2, 'body': 'x <!-- intake:v1 {"repo":"FuRongJun-1999/lingshu","severity":"P1"} -->'}]
    r = _run_fixture(rows)
    assert 'field drift' in r.stdout
def test_project_mismatch_fails():
    rows = [{'issue': 3, 'body': 'x <!-- intake:v1 {"project":"memory","target":"FuRongJun-1999/lingshu"} -->'}]
    r = _run_fixture(rows)
    assert r.returncode == 1 and 'project=memory' in r.stdout
def test_bad_difficulty_fails():
    rows = [{'issue': 4, 'body': 'x <!-- intake:v1 {"project":"memory","difficulty":"small","target":"FuRongJun-1999/dsh-memory"} -->'}]
    r = _run_fixture(rows)
    assert r.returncode == 1 and 'difficulty' in r.stdout
def test_p_severity_maps():
    rows = [{'issue': 5, 'body': 'x <!-- intake:v1 {"target":"FuRongJun-1999/lingshu","severity_hint":"P1"} -->'}]
    r = _run_fixture(rows)
    assert 'impact' not in [l.split(':')[0] for l in r.stdout.split(chr(10)) if 'not in vocab' in l]
def test_no_marker_reports():
    rows = [{'issue': 6, 'body': 'no marker here'}]
    r = _run_fixture(rows)
    assert 'no intake:v1 marker' in r.stdout
MUTATE = os.environ.get('MUTATE_TARGET', '')
if MUTATE == 'R1':
    # 变异：把 project 一致性检查注释掉 ⇒ test_project_mismatch_fails 必红
    _orig = io.open(SCRIPT, encoding='utf-8').read()
    _mut = _orig.replace("errs.append('project=%s but target=%s implies %s'", "pass  # ")
    io.open(SCRIPT, 'w', encoding='utf-8').write(_mut)
elif MUTATE == 'R2':
    _orig = io.open(SCRIPT, encoding='utf-8').read()
    _mut = _orig.replace("errs.append('difficulty=%r not in vocab", "pass  # ")
    io.open(SCRIPT, 'w', encoding='utf-8').write(_mut)