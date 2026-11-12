#!/usr/bin/env python3
"""Sinh writing/generated/method-params.tex: tham số harness và số đếm của exp 12 dùng trong Chương 3 (§3.3, §3.6).

Nguồn:
  - hằng số đọc trực tiếp từ package harness/ (import, hoặc regex trên mã nguồn với hằng viết thẳng trong biểu thức;
    hằng lặp ở nhiều nơi thì mọi nơi phải cùng giá trị, nếu không in ??); số seed lượt chính đối chiếu thêm ci/make-shard-jobs.py;
  - experiments/12-stderr-audit/results/ (classified.jsonl.gz, rq2-stderr-vectors.jsonl).
Không có nguồn thì in ?? để build lộ ra. Không sửa tay file sinh ra.

Dùng: python3 writing/scripts/gen-method-macros.py [--harness-root <thư mục chứa harness/>]
  --harness-root mặc định là gốc repo. Khi code chưa merge vào main, trỏ tới worktree của nhánh review."""
import argparse, gzip, inspect, json, math, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
OUT = f'{ROOT}/writing/generated/method-params.tex'


def src(hroot, rel):
    try:
        return open(os.path.join(hroot, rel)).read()
    except OSError:
        return ''


def need(vals, label, k=1):
    """Số chỗ khớp phải đạt tối thiểu k; thiếu thì trả [None] để same() ra ??."""
    if len(vals) >= k: return vals
    print(f'{label}: cần ít nhất {k} chỗ khớp, thấy {len(vals)}', file=sys.stderr)
    return [None]


def same(key, vals):
    """Mọi chỗ đọc được phải cùng một giá trị; không có hoặc lệch nhau thì ??."""
    if vals and None not in vals and len(set(vals)) == 1: return vals[0]
    print(f'{key}: giá trị không nhất quán hoặc thiếu: {vals}', file=sys.stderr)
    return '??'


def main_seeds(hroot):
    """Số seed lượt chính: danh sách seed phải trùng nhau ở metrics.py, merge_shards.py (CLI và chữ ký merge) và lệnh rq1 của
    ci/make-shard-jobs.py (nơi lượt chính thực sự chạy). harness/rq1.py có --seeds mặc định '0' (pilot), không thuộc lượt chính."""
    seq = lambda s: tuple(int(x) for x in re.split(r'[,\s]+', s.strip()) if x)
    ms = src(hroot, 'harness/merge_shards.py')
    lists = need([seq(x) for x in re.findall(r"'--seeds', default='([\d,]+)'", src(hroot, 'harness/metrics.py'))], 'metrics.py --seeds')
    lists += need([seq(x) for x in re.findall(r"'--seeds', default='([\d,]+)'", ms)], 'merge_shards.py --seeds')
    lists += need([seq(x) for x in re.findall(r'def merge\([^)]*seeds=\(([\d, ]+)\)', ms)], 'merge_shards.py merge(seeds=...)')
    lists += need([seq(x) for x in re.findall(r'harness\.rq1 .*--seeds ([\d,]+)', src(hroot, 'ci/make-shard-jobs.py'))],
                  'ci/make-shard-jobs.py rq1 --seeds')
    v = same('pSeeds', lists)
    return '??' if v == '??' else len(v)


def harness_params(hroot):
    sys.path.insert(0, hroot)
    m = {}
    try:
        import harness.config as C, harness.observe as O, harness.rq1 as R, harness.rq2 as Q
        from harness.gen import v2_exe, stategen_v2
    except Exception as e:                       # nhánh chưa có mã: để ?? thay vì đoán
        print(f'Không import được harness từ {hroot}: {e}', file=sys.stderr)
        return m, None
    m['pOutputCapMiB'] = O.OUTPUT_CAP >> 20
    m['pCapSensFactor'] = R.OUTPUT_CAP_SENS
    m['pCapSensMiB'] = (O.OUTPUT_CAP * R.OUTPUT_CAP_SENS) >> 20
    m['pMemLimitGiB'] = O.MEM_LIMIT >> 30
    m['pSanRssMiB'] = R.SAN_RSS_MB
    m['pFsizeLimitGiB'] = O.FSIZE_LIMIT >> 30
    m['pRerunFactor'] = C.TIMEOUT_RERUN_FACTOR
    m['pSanTimeoutFactor'] = R.SAN_TIMEOUT_FACTOR
    m['pCTimeFactor'] = R.C_TIME_FACTOR             # timeout theo case: bội của thời gian C lớn nhất trên vector (F3)
    m['pStabReps'] = R.STAB_REPS
    m['pInfraAttempts'] = R.SAN_ATTEMPTS if R.SAN_ATTEMPTS == R.LIB_INFRA_ATTEMPTS else '??'
    m['pRqTwoReps'] = Q.REPS
    rel = inspect.signature(O.float_tol_equal).parameters['rel'].default
    m['pFloatRelTolExp'] = round(math.log10(rel))
    m['pExeConstSyntaxPct'] = round(v2_exe.P_V2 * 100)
    m['pLibDictPct'] = round(stategen_v2.P_DICT * 100)
    m['pLibSweepPct'] = round(stategen_v2.P_SWEEP * 100)
    m['pLibRandomPct'] = 100 - m['pLibDictPct'] - m['pLibSweepPct']
    m['pLibSweepMaxValues'] = stategen_v2.SMALL_MAX
    src_obs = open(inspect.getsourcefile(O)).read()
    d = re.search(r'deadline = t0 \+ timeout \* (\d+) \+ (\d+)', src_obs)
    m['pLibDeadlineFactor'], m['pLibDeadlineSlackSec'] = (d.group(1), d.group(2)) if d else ('??', '??')
    src_rq1 = open(inspect.getsourcefile(R)).read()
    t = re.search(r"'--timeout', type=int, default=(\d+)", src_rq1)
    m['pTimeoutSec'] = t.group(1) if t else '??'          # mặc định CLI; giá trị lượt chính chốt ở memo W6, R5
    a = re.search(r"'-t', '(\d+)'", src_rq1)
    m['pAflExecTimeoutMs'] = a.group(1) if a else '??'
    # Hằng viết thẳng trong biểu thức ở nhiều nơi: đọc mọi chỗ, chỗ nào thiếu hoặc lệch nhau thì ??.
    lib_src = inspect.getsource(O._run_lib)
    m['pDumpCapFactor'] = same('pDumpCapFactor', re.findall(r'getsize\(dump_path\) > (\d+) \* cap\b', lib_src))
    m['pSeeds'] = main_seeds(hroot)
    m['pGenAttemptFactorExe'] = same('pGenAttemptFactorExe', [
        *need(re.findall(r'guard < budget \* (\d+)', src(hroot, 'harness/gen/v1.py')), 'v1.py budget * N'),
        *need(re.findall(r'guard < n_v2 \* (\d+)', src(hroot, 'harness/gen/v2_exe.py')), 'v2_exe.py n_v2 * N')])
    ms = src(hroot, 'harness/gen/mutate_state.py')
    # mutate_state: mọi chỗ gán max_attempts_factor= (mặc định ở def và mọi lời gọi truyền tường minh), và vòng phải dùng tham số đó
    lib = need(re.findall(r'tries < n_(?:dict|sweep) \* (\d+)', src(hroot, 'harness/gen/stategen_v2.py')), 'stategen_v2.py tries < n_x * N', 2)
    lib += need(re.findall(r'max_attempts_factor\s*=\s*(\d+)', ms), 'mutate_state.py max_attempts_factor=N')
    if not re.search(r'range\(n \* max_attempts_factor\)', ms):
        print('pGenAttemptFactorLib: mutate_state.py không còn vòng range(n * max_attempts_factor)', file=sys.stderr); lib = []
    m['pGenAttemptFactorLib'] = same('pGenAttemptFactorLib', lib)
    import subprocess
    try:
        rev = subprocess.run(['git', '-C', hroot, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
    except OSError:
        rev = '?'
    return m, rev


def stderr_audit():
    r = f'{ROOT}/experiments/12-stderr-audit/results'
    m = {}
    try:
        cases = set()
        with gzip.open(f'{r}/classified.jsonl.gz', 'rt') as f:
            for l in f:
                x = json.loads(l)
                if x.get('kind') == 'exe' and x.get('group') in ('B', 'C'):   # khác biệt còn lại sau khi bỏ đường dẫn binary
                    cases.add((x['bundle'], x['case']))
        m['nStderrPilotExeCases'] = len(cases)
    except OSError:
        m['nStderrPilotExeCases'] = '??'
    try:
        m['nStderrRQTwoVectors'] = sum(1 for l in open(f'{r}/rq2-stderr-vectors.jsonl') if l.strip())
    except OSError:
        m['nStderrRQTwoVectors'] = '??'
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--harness-root', default=ROOT)
    a = ap.parse_args()
    keys = ['pOutputCapMiB', 'pCapSensFactor', 'pCapSensMiB', 'pMemLimitGiB', 'pSanRssMiB', 'pFsizeLimitGiB', 'pTimeoutSec',
            'pRerunFactor', 'pSanTimeoutFactor', 'pCTimeFactor', 'pStabReps', 'pInfraAttempts', 'pRqTwoReps', 'pFloatRelTolExp',
            'pExeConstSyntaxPct', 'pLibRandomPct', 'pLibDictPct', 'pLibSweepPct', 'pLibSweepMaxValues', 'pLibDeadlineFactor',
            'pLibDeadlineSlackSec', 'pAflExecTimeoutMs', 'pDumpCapFactor', 'pSeeds', 'pGenAttemptFactorExe', 'pGenAttemptFactorLib']
    hp, rev = harness_params(os.path.abspath(a.harness_root))
    sa = stderr_audit()
    lines = ['% SINH TU DONG boi writing/scripts/gen-method-macros.py. KHONG SUA TAY.',
             f'% Tham so: package harness/ tai commit {rev or "?"}',
             '% So dem stderr: experiments/12-stderr-audit/results/ (Le duyet mau 17/17 ngay 2026-10-23)', '']
    lines += [f'\\newcommand{{\\{k}}}{{{hp.get(k, "??")}}}' for k in keys]
    lines += [f'\\newcommand{{\\{k}}}{{{v}}}' for k, v in sa.items()]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
