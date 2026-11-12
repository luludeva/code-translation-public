#!/usr/bin/env python3
"""Thay mục nonrep_groups của analysis-<kind>.json (exp 30) bằng mục tính lại với --nonrep-evidence, đúng các lời gọi của
harness.analysis.analyse (nonrep_population, load_evidence, nonrep_groups, by_gs). Mục này chỉ đọc census và file bằng chứng, không đọc bản
ghi RQ1, nên không cần chạy lại cả analyse trên máy lớn. Kiểm: với evidence=None phải tái tạo đúng mục đang có trong exp 30.
Dùng (gốc repo, đặt HARNESS_P_REP_LIB_* như lượt chính): python3 experiments/33-nonrep-evidence/scripts/patch_analysis.py"""
import json, os, sys
sys.path.insert(0, os.getcwd())
from harness import analysis as A

E30, E33 = 'experiments/30-main-s0/results', 'experiments/33-nonrep-evidence/results'
ev_path = f'{E33}/evidence.jsonl'


def section(kind, ev):
    pop = A.nonrep_population(kind)
    f, unmatched = A.nonrep_groups(pop, ev, 'missing')
    return A.by_gs(pop, f, lambda p: p['bundle'], lambda p: p['system']), unmatched


for kind in ('exe', 'lib'):
    doc = json.load(open(f'{E30}/analysis-{kind}.json'))
    base, _ = section(kind, None)
    same = json.dumps(base, sort_keys=True) == json.dumps(doc['sections']['nonrep_groups'], sort_keys=True)
    if not same: raise SystemExit(f'{kind}: không tái tạo được mục nonrep_groups của exp 30, dừng')
    sec, unmatched = section(kind, A.load_evidence(ev_path, kind))
    doc['sections']['nonrep_groups'] = sec
    doc['meta'].update(nonrep_evidence=os.path.abspath(ev_path), nonrep_unclassified='missing', nonrep_unmatched=unmatched,
                       nonrep_patched_by='experiments/33-nonrep-evidence/scripts/patch_analysis.py')
    json.dump(doc, open(f'{E33}/analysis-{kind}.json', 'w'), indent=1, ensure_ascii=False, sort_keys=True)
    print(kind, 'tái tạo exp 30: đạt; unmatched', unmatched, json.dumps(sec['all']['_all'], ensure_ascii=False)[:400])
