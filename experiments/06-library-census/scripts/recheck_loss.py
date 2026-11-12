#!/usr/bin/env python3
"""Kiểm lại 22 ca hao hụt P_acc → P_rep của census library (DoD mốc 1, decision-log 2026-10-14 "Checkpoint 18/10").

Khác census_lib.py ở ba điểm, để tách lỗi của mình khỏi lỗi bản dịch:
  - chạy tuần tự (census chạy 2 worker song song, timeout có thể do tranh tài nguyên);
  - timeout 120 giây (mặc định TRACTOR) ngay từ đầu, lặp REPS lần;
  - .so lệch tên (build ra lib<khác>.so thay vì lib<library>.so): đặt symlink tên đúng, ghi `so_alias`, rồi chạy.
    Lệch tên là lệch giữa fork HARVEST và bản công khai (như matrix_sum), không phải lỗi bản dịch.
Danh sách cặp lấy từ results/census-lib.jsonl: công bố đỗ, không pilot, có input, ours_passed khác True."""
import glob, json, os, shutil, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import census_lib as CL   # noqa: E402

REPS, TO = int(os.environ.get('REPS', '3')), int(os.environ.get('TO', '120'))
OUT = CL.OUT; B = CL.B; T = CL.T; H = CL.H


def targets():
    rows = [json.loads(l) for l in open(os.path.join(HERE, '..', 'results', 'census-lib.jsonl'))]
    return [r for r in rows if not r['pilot'] and not r['no_input'] and r.get('pub_passed') is True and not r.get('ours_passed')]


def recheck(info, r):
    b, tc, hc, s = r['bundle'], r['tractor_case'], r['harvest_case'], r['system']
    base = f'{H}/{s}/{b}/{hc}'
    src = f'{base}/verified' if os.path.isdir(f'{base}/verified') else f'{base}/translated'
    rec = dict(bundle=b, tractor_case=tc, system=s, census_results=r.get('results'), census_build=r.get('build_log_tail'))
    wd = f'{B}/recheck-src/{s}/{b}/{hc}'; shutil.rmtree(wd, ignore_errors=True); os.makedirs(os.path.dirname(wd), exist_ok=True)
    shutil.copytree(src, wd, ignore=shutil.ignore_patterns('target', 'logs'))
    feat = any('#![feature' in open(f, errors='ignore').read() for f in glob.glob(f'{wd}/**/*.rs', recursive=True))
    env = dict(os.environ, RUSTC_BOOTSTRAP='1') if feat else dict(os.environ)
    td = f'{B}/recheck-rust/{s}/{b}/{hc}'; shutil.rmtree(td, ignore_errors=True)
    rc, log = CL.sh(['cargo', 'build', '--release', '--target-dir', f'{td}/target'], cwd=wd, env=env)
    rel = f'{td}/target/release'; want = f'{rel}/lib{info["library"]}.so'
    if rc != 0:
        rec.update(build_ok=False, build_log_tail=log[-1500:]); return rec
    if not os.path.exists(want):
        found = [x for x in glob.glob(f'{rel}/*.so')]
        if len(found) != 1:
            rec.update(build_ok=False, build_log_tail='so: ' + ','.join(map(os.path.basename, found))); return rec
        os.symlink(os.path.basename(found[0]), want); rec['so_alias'] = f'{os.path.basename(found[0])} -> lib{info["library"]}.so'
    rec['build_ok'] = True
    root = f'{B}/recheck-roots/{s}/{b}/{tc}'; shutil.rmtree(root, ignore_errors=True); os.makedirs(root)
    troot = f'{T}/{b}/{tc}'
    os.symlink(f'{troot}/test_case', f'{root}/test_case'); os.symlink(f'{troot}/test_vectors', f'{root}/test_vectors')
    os.symlink(f'{B}/c/{b}/{tc}', f'{root}/build-ninja'); os.symlink(td, f'{root}/translated_rust')
    rec['reps'] = []
    for k in range(REPS):
        rep = f'{OUT}/reports/{s}/{b}/{tc}.rep{k}.json'; os.makedirs(os.path.dirname(rep), exist_ok=True)
        t0 = time.time()
        rc, log = CL.sh([info['runner_bin'], '-l', 'quiet', '-t', root, '--rust', '--timeout', str(TO), '-o', rep, 'lib'], timeout=4 * 3600)
        one = dict(secs=round(time.time() - t0, 1), runner_rc=rc, runner_log_tail=(log or '')[-800:])
        if os.path.exists(rep):
            d = json.load(open(rep))
            one['results'] = {v: d[v]['result'] for v in sorted(d)}
            one['diffs'] = {v: d[v].get('diff', '')[:600] for v in sorted(d) if d[v]['result'] not in ('Pass', 'Skip')}
        rec['reps'].append(one)
    outs = [json.dumps(x.get('results'), sort_keys=True) for x in rec['reps']]
    rec['stable'] = len(set(outs)) == 1
    rec['ours_passed'] = all(x.get('results') and all(v in ('Pass', 'Skip') for v in x['results'].values()) for x in rec['reps'])
    shutil.rmtree(td, ignore_errors=True); shutil.rmtree(wd, ignore_errors=True)
    return rec


def main():
    os.makedirs(OUT, exist_ok=True); os.makedirs(B, exist_ok=True)
    CL.S.B = B; CL.S.setup_cando2()
    tg = targets(); print(len(tg), 'cặp', flush=True)
    cases = sorted({(r['bundle'], r['tractor_case']) for r in tg})
    cinfo = {c: CL.prepare_case(*c) for c in cases}
    with open(f'{OUT}/recheck-loss.jsonl', 'w') as f:
        for r in tg:
            info = cinfo[(r['bundle'], r['tractor_case'])]
            rec = recheck(info, r) if info['runner_ok'] and info['c_so'] else dict(r, error='C hoặc runner không build được', c_results=info.get('c_results'))
            rec['c_results'] = info.get('c_results')
            f.write(json.dumps(rec, ensure_ascii=False) + '\n'); f.flush()
            print(r['system'], r['tractor_case'], rec.get('so_alias', ''), rec.get('ours_passed'), rec.get('stable'),
                  [x.get('results') for x in rec.get('reps', [])][:1], flush=True)


if __name__ == '__main__':
    main()
