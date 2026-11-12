#!/usr/bin/env python3
"""Dựng phễu P0 → P_acc → P_rep từ census-exe.jsonl (P_test cần harness, chưa có ở bước này)."""
import json, collections
recs = [json.loads(l) for l in open('results/census-exe.jsonl')]
# dedupe: giữ bản ghi cuối cho mỗi cặp
d = {}
for r in recs: d[(r['bundle'], r['tractor_case'], r['system'])] = r
recs = list(d.values())
def ours_pass(r): return r.get('run_ok') and all(k in ('Pass', 'Skip') for k in (r.get('results') or {}))
rows = ['system\tscope\tP0\tP_acc\tP_rep\tacc_missing_artifact\tacc_build_fail\tacc_no_bin_target\tacc_run_fail\tacc_repfail_timeout_only\tacc_repfail_comparison\tpub_fail_ours_pass\trustc_bootstrap_used']
systems = sorted({r['system'] for r in recs})
for scope in ['main', 'pilot']:
    for s in systems + ['ALL']:
        R = [r for r in recs if (s == 'ALL' or r['system'] == s) and r['pilot'] == (scope == 'pilot')]
        acc = [r for r in R if r.get('pub_passed')]
        c = collections.Counter()
        for r in acc:
            res = r.get('results') or {}
            if r.get('stage') == 'P0_missing_artifact': c['miss'] += 1
            elif not r.get('build_ok'): c['nobin' if 'no unique binary' in r.get('build_log_tail', '') else 'build'] += 1
            elif not r.get('run_ok'): c['run'] += 1
            elif not ours_pass(r): c['rf_cmp' if 'VectorComparisonFailed' in res else 'rf_to'] += 1
            else: c['rep'] += 1
        pfop = sum(1 for r in R if r.get('pub_passed') is False and ours_pass(r))
        rows.append(f"{s}\t{scope}\t{len(R)}\t{len(acc)}\t{c['rep']}\t{c['miss']}\t{c['build']}\t{c['nobin']}\t{c['run']}\t{c['rf_to']}\t{c['rf_cmp']}\t{pfop}\t{sum(1 for r in R if r.get('rustc_bootstrap'))}")
open('results/funnel-exe.tsv', 'w').write('\n'.join(rows) + '\n')
print('\n'.join(rows))
