#!/usr/bin/env python3
"""Chạy lại census executable (A2.2) trên EC2, môi trường dùng cho lượt đo chính (Le chốt 2026-10-20, review §3.2 v1 mục 5).

Dùng lại nguyên hàm `build_c` và `one` của census.py (không sửa file đó), chỉ đổi môi trường:
  - RUNNER: cando_binrunner build ở $CORPUS/cando2 (cách ci/setup-corpus.sh dựng), thay cho $CORPUS/tractor/target;
  - toolchain: $RUSTUP_TOOLCHAIN (1.97.0, như mọi job EC2) thay cho 'stable';
  - WORKERS mặc định 1 (tuần tự). Census cũ chạy 2 worker trên Cowork cloud; 54/55 cặp timeout ở đó pass 3/3 khi chạy
    tuần tự trên EC2 (job recheck-timeout-exe), nên tuần tự là lựa chọn an toàn hơn.
  - đầu ra ở $OUT, không ghi đè census-exe.jsonl gốc (giữ để đối chiếu hai môi trường).
Sau census: cặp công bố đỗ mà tái lập ra trượt chỉ vì Timeout được chạy lại theo luật đăng ký trước
`docs/proposal/prereg-2026-10-20-retry-rule.md` (3 lần, tuần tự, 120 giây; 3/3 pass mới vào P_rep)."""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ['OUT']
os.environ.setdefault('EXP', os.path.abspath(os.path.join(HERE, '..')))

src = open(os.path.join(HERE, 'census.py')).read().replace('\nmain()\n', '\n')
g = {'__name__': 'census_mod', '__file__': os.path.join(HERE, 'census.py')}
exec(src, g)
g['RUNNER'] = os.environ.get('RUNNER', f"{g['CORPUS']}/cando2/target/release/cando_binrunner")
g['ENV'] = dict(os.environ)          # RUSTUP_TOOLCHAIN do job đặt
g['BUILD'] = os.environ['B']
g['EXP'] = OUT                      # one() ghi report vào {EXP}/results/census-reports/...

sys.path.insert(0, HERE)
os.environ.setdefault('B', g['BUILD'])
import recheck_timeouts as RT        # noqa: E402
RT.RUNNER = g['RUNNER']; RT.CORPUS = g['CORPUS']; RT.B = f"{g['BUILD']}/recheck"; RT.OUT = f'{OUT}/recheck'


def main():
    import csv
    os.makedirs(f'{OUT}/results', exist_ok=True)
    rows = [r for r in csv.DictReader(open(os.path.join(HERE, '..', 'data', 'case-name-map.tsv')), delimiter='\t') if r['kind'] == 'exe']
    cres = {(r['bundle'], r['tractor_case']): g['build_c'](r['bundle'], r['tractor_case']) for r in rows}
    json.dump({f'{k[0]}/{k[1]}': {'tally': v[0], 'err': v[1]} for k, v in cres.items()},
              open(f'{OUT}/census-c-side.json', 'w'), indent=1)
    out = f'{OUT}/census-exe-ec2.jsonl'
    done = set()
    if os.path.exists(out):
        for l in open(out):
            d = json.loads(l); done.add((d['bundle'], d['tractor_case'], d['system']))
    jobs = [(r, s) for r in rows for s in g['SYSTEMS'] if (r['bundle'], r['tractor_case'], s) not in done]
    print(f'{len(jobs)} pairs to run', flush=True)
    with ThreadPoolExecutor(int(os.environ.get('WORKERS', '1'))) as ex, open(out, 'a') as f:
        for fut in as_completed([ex.submit(g['one'], *a) for a in jobs]):
            rec = fut.result(); rec['env'] = 'ec2'
            f.write(json.dumps(rec) + '\n'); f.flush()
            print(rec['system'], rec['tractor_case'], rec.get('build_ok'), rec.get('ours_passed'), flush=True)
    # luật timeout đăng ký trước
    recs = [json.loads(l) for l in open(out)]
    tg = [r for r in recs if r.get('pub_passed') and not r.get('pilot') and r.get('results')
          and set(r['results']) - {'Pass', 'Skip'} == {'Timeout'}]
    print(len(tg), 'cặp chỉ trượt vì Timeout, chạy lại theo luật 3/3', flush=True)
    os.makedirs(RT.OUT, exist_ok=True); os.makedirs(RT.B, exist_ok=True)
    with open(f'{OUT}/recheck-timeout-ec2.jsonl', 'w') as f:
        for r in tg:
            rec = RT.recheck(r)
            f.write(json.dumps(rec, ensure_ascii=False) + '\n'); f.flush()
            print(r['system'], r['tractor_case'], rec.get('ours_passed'), rec.get('stable'), flush=True)


if __name__ == '__main__':
    main()
