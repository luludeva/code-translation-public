"""Danh sách cặp từ census (harness-design.md mục 4.4, module pairs; decision-log mục "Phễu §3.2", 2026-10-21).

P_rep executable: cặp không pilot, công bố đỗ, build được, và tái lập đỗ (mọi vector Pass hoặc Skip; gồm nhóm đỗ với 0 vector,
  decision-log 2026-10-21), hoặc chỉ trượt vì Timeout rồi đỗ 3/3 khi chạy lại (luật đăng ký trước 2026-10-20).
P_rep library: như trên với census library và file kiểm lại hao hụt (recheck: alias .so, 3 lần).
R_run (cho RQ2, chưa dùng ở V5/V6): công bố trượt ở giai đoạn test, build được, tái lập trượt."""
import json, os

from .config import REPO


def load(p):
    return [json.loads(l) for l in open(p)] if p and os.path.exists(p) else []


def _passes(r):
    res = r.get('results')
    if res is None: return False
    bad = set(res) - {'Pass', 'Skip'}
    return not bad and (bool(res) or (r.get('run_ok') and r.get('vectors') == 0))


def _timeout_only(r):
    res = r.get('results') or {}
    return set(res) - {'Pass', 'Skip'} == {'Timeout'}


def p_rep(census, recheck):
    rk = {(r['bundle'], r['tractor_case'], r['system']): r for r in recheck}
    out = []
    for r in census:
        if r['pilot'] or r.get('stage') == 'P0_missing_artifact' or r.get('pub_passed') is not True:
            continue
        k = (r['bundle'], r['tractor_case'], r['system'])
        if r.get('build_ok') and _passes(r):
            out.append(dict(r, via='census'))
        elif k in rk and rk[k].get('ours_passed') and rk[k].get('stable', True):   # gồm cặp census không build vì lệch tên .so
            out.append(dict(r, via='recheck', so_alias=rk[k].get('so_alias')))
    for r in out: r['no_input'] = bool(r.get('no_input'))   # 3 library không có trường input: vào P_rep, ngoài P_test theo thiết kế
    return out


# Nguồn P_rep. Q9 (a) (Le chọn 25/10): census library lần ba thay nguồn library; để đổi nguồn mà không sửa harness/ sau commit đo (luật
# kế thừa tag, decision-log 2026-10-26), job đặt HARNESS_P_REP_LIB_CENSUS, HARNESS_P_REP_LIB_RECHECK; manifest RQ1 ghi nguồn và sha256.
DEFAULT = dict(
    exe=dict(census=f'{REPO}/experiments/02-harvest-repro/results/census-exe-ec2.jsonl',
             recheck=f'{REPO}/experiments/02-harvest-repro/results/recheck-timeout-ec2.jsonl'),
    lib=dict(census=os.environ.get('HARNESS_P_REP_LIB_CENSUS') or f'{REPO}/experiments/06-library-census/results/census-lib.jsonl',
             recheck=os.environ.get('HARNESS_P_REP_LIB_RECHECK') or f'{REPO}/experiments/06-library-census/results/recheck-loss.jsonl'))


def source_info(kind):
    """Đường dẫn và sha256 của nguồn P_rep đang dùng (cho manifest)."""
    import hashlib
    return {k: dict(path=v, sha256=hashlib.sha256(open(v, 'rb').read()).hexdigest() if os.path.exists(v) else None)
            for k, v in DEFAULT[kind].items()}


def prep_pairs(kind, census=None, recheck=None):
    d = DEFAULT[kind]
    return p_rep(load(census or d['census']), load(recheck or d['recheck']))


def cases_of(pairs):
    seen, out = set(), []
    for r in pairs:
        k = (r['bundle'], r['tractor_case'])
        if k not in seen: seen.add(k); out.append(k)
    return sorted(out)


def shard(items, spec):
    """spec 'i/n' (1-based): phần thứ i trong n phần, chia theo vòng để cân tải."""
    if not spec: return items
    i, n = map(int, spec.split('/'))
    return [x for j, x in enumerate(items) if j % n == i - 1]
