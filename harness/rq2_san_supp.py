"""Lượt bổ sung C-san cho 36 bản RQ2 executable của codex-gpt54 P01 (exp 37; docs/amendment-2026-11-05-rq2-san-supp.md, post hoc,
quyết định sau khi đã xem số S₀). File mới: luật kế thừa tag (decision-log 2026-10-26) chỉ cho thêm file dưới harness/, nên module này KHÔNG
sửa build.py, config.py, rq1.py, rq2.py mà gọi lại đúng các hàm đã freeze.

Thay đổi duy nhất (amendment mục 4, cách cài I-a do Le chốt): trong tiến trình build PIC và tiến trình chạy, gán
  harness.build.SAN_FLAGS_EXE = config.SAN_FLAGS_EXE + ['-DCMAKE_POSITION_INDEPENDENT_CODE=ON']
rồi gọi nguyên build_c_exe(B, bundle, case, san=True). build_c_exe đọc biến toàn cục SAN_FLAGS_EXE của module build lúc gọi, nên phép gán
có hiệu lực; config.SAN_FLAGS_EXE không đổi (phép cộng tạo list mới). Worker của ProcessPoolExecutor gán lại trong initializer, và
supp_key kiểm phép gán trước khi build, nên không phụ thuộc cách khởi tạo tiến trình (fork hay spawn). Build đối chứng cờ gốc (amendment mục 7
bước 3, S-orig, S-ninja) chạy trong tiến trình riêng không có phép gán (lệnh `orig`).

Mỗi key (amendment mục 8): lấy bản ghi S₀ (timeout theo case, vector, quan sát đã lưu `obs.runs`), đọc lại vector bằng vectors.read_vector như
rq2_pair và so sha256 với trường `input` đã lưu, gọi CHỈ kiểm sanitizer phía C bằng rq1._exe_san với đúng tham số rq2_pair dùng (timeout của
case, sink, c_status của quan sát C quyết định ở lần chạy đầu), rồi vector_outcome trên quan sát đã lưu cộng trạng thái sanitizer mới,
translation_outcome, primary_reason. Không chạy lại phía C đo hay phía Rust, không build lại Rust.

Phân loại thoát (amendment mục 7, 10): mã 0 đạt; mã 3 (EXIT_STOP) là luật dừng, job ghi STOP.txt; mã khác 0 còn lại là `fail`. Cổng thuộc
luật dừng: amendment, keys, s0, inputs, deadline, freeze. Cổng `fail`: env, tractor, vector_files (file vector không đọc được).

Lần thử (amendment mục 7 bước 5, Le chốt vòng 4): một lần chạy của job smoke hay job đầy đủ là một lần thử khi nó tới bước thực thi, tức
`run` đã ghi run/manifest.json trước khi giao key; `run` ghi ngay sau đó một dòng vào rq2-supp-runs.jsonl (lịch sử lần thử, chép tiếp qua
mỗi lần nộp, tên khớp mẫu rq[12]-*.jsonl của guard Publish). Lần chạy bị từ chối trước đó (scan, preflight, B0, cổng) được nộp kèm lý do
nhưng không bao giờ được tính. Lệnh `scan` đọc results/<job> và results-failed/<job>-<run> của ba job (git ls-remote, fetch): có STOP.txt
thì dừng; job đã hoàn tất (complete.json), smoke và full đã hoàn tất, hoặc (job gate) smoke đã hoàn tất thì không làm gì; số lần thử
n = max(SUPP_ATTEMPT khai báo, lần thử đã tính lớn nhất + 1, số lần thử đã tính + 1), quá 2 thì dừng. Job gate không giới hạn lần thử (không
thực thi binary C-san nào). Job đầy đủ: key có harness_error chạy lại một lần trong cùng job; hai lần thì giữ S₀ (supp_harness_error). Job
smoke: harness_error của key smoke làm lần thử của job smoke không hoàn tất. Mỗi manifest và mỗi bản ghi ghi sha256 của module này.

Lệnh (check, orig, build, run kiểm cổng trước: keys.txt, amendment đã commit, không còn khối OPTION, commit amendment là tổ tiên của HEAD,
tag freeze, môi trường mục 7):
  python3 -m harness.rq2_san_supp scan    --mode gate|smoke|full --out DIR [--declared-attempt N]   (mục 7 bước 5; mã 10: không làm gì)
  python3 -m harness.rq2_san_supp check   [--s0 F]
  python3 -m harness.rq2_san_supp orig    --out DIR [--orig-root D] [--configure-rest]   (S-orig, S-ninja; không gán cờ)
  python3 -m harness.rq2_san_supp build   --out DIR [--build-root B] [--workers 1]        (S-pic; tuần tự; không thực thi binary; mã 4: có build lỗi)
  python3 -m harness.rq2_san_supp run     --s0 rq2-exe.jsonl --out DIR (--smoke | --full) --gate-json G [--workers 6] [--expect-builds J]
                                          [--attempt N --history F]   (F: rq2-supp-runs.jsonl của job; dòng ghi ngay sau manifest)
  python3 -m harness.rq2_san_supp b0      (nhánh B0, mục 7 bước 2; results/rq2-san-log và mọi results-failed/rq2-san-log-<run>)
  python3 -m harness.rq2_san_supp accept-smoke --smoke-dir ci-out/rq2-san-supp-smoke --preflight preflight.json   (mục 7 bước 4, 5)
  (check, orig, build, run, b0 nhận --freeze-tag protocol-freeze-r1, --amendment-commit, --keys)"""
import argparse, calendar, collections, contextlib, hashlib, json, os, re, subprocess, sys, time, traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

from . import build as BD
from . import config as CF
from . import observe as OB
from . import rq1 as R1
from . import rq2 as R2
from .record import Store, blob, machine_info, manifest, tool

AMENDMENT = 'docs/amendment-2026-11-05-rq2-san-supp.md'
KEYS = 'experiments/37-rq2-san-supp/data/keys.txt'
KEYS_SHA256 = '17955ced1386aed6975985e763b3e8fd63d7e7a575d355e9b29eff291414f3d8'          # amendment mục 3
S0_SHA256 = 'cd094ca44ca71b5229291ef49a11329e6a25007ed7db1e6dd3bfd3663f26877f'            # b757f4d:ci-out/rq2-main/exe/rq2-exe.jsonl
S0_SOURCE = 'results/rq2-main b757f4da7c979623c2e0878c6a644f277d9a8be4:ci-out/rq2-main/exe/rq2-exe.jsonl'
N_KEYS = 36
KEY_PREFIX = 'codex-gpt54/P01_sphincs_plus/'
TARGET_REASON = 'incomplete_harness_run:san_build_failed'
PIC_FLAG = '-DCMAKE_POSITION_INDEPENDENT_CODE=ON'
FREEZE_TAG = 'protocol-freeze-r1'                       # Le chốt giữ r1 (amendment đầu file)
DEADLINE_UTC = '2026-11-10T05:00:00Z'                   # luật dừng mục 10: 2026-11-10 12:00 giờ VN
WORKERS = 6                                             # thực thi: như S₀ (params.workers của manifest exe b757f4d)
BUILD_WORKERS = 1                                       # build PIC tuần tự (amendment mục 7 bước 3; tránh OOM trong cgroup 13G)
ENV_REQ = dict(instance_type='c7i.2xlarge', ami_id='ami-0c4ae4cba162bf697', clang='Ubuntu clang version 18.1.3')
GCC_RE = re.compile(r'\b13\.3\.\d')                     # amendment mục 7: gcc 13.3
IMDS_KEYS = ('instance_id', 'instance_type', 'ami_id')
IMDS_TRIES, IMDS_WAIT = 5, 2                            # IMDS lỗi tạm thời không được thành STOP
PIC_ROOT = os.path.expanduser('~/build/rq2-san-supp')
ORIG_ROOT = os.path.expanduser('~/build/rq2-san-supp-orig')
OUT_NAME = 'rq2-san-supp-exe.jsonl'
EXIT_FAIL, EXIT_STOP, EXIT_BUILD, EXIT_NOOP = 1, 3, 4, 10
STOP_GATES = frozenset({'amendment', 'keys', 's0', 'inputs', 'deadline', 'freeze'})
# Ba job của lượt (amendment mục 7); tên nhánh kết quả results/<job>, bản bị guard của workflow đẩy sang results-failed/<job>-<run id>
JOBS = dict(gate='rq2-san-supp-gate', smoke='rq2-san-supp-smoke', full='rq2-san-supp')
COMPLETE, ATTEMPT, NOOP = 'complete.json', 'attempt.json', 'noop.txt'
RUNS = 'rq2-supp-runs.jsonl'                             # lịch sử lần thử đã tính của một job (khớp mẫu rq[12]-*.jsonl của guard Publish)
RUN_MANIFEST = 'run/manifest.json'                      # có trong lần nộp: lần chạy đã tới bước thực thi, là một lần thử (Le chốt vòng 4)
SMOKE_GATE_PY = 'experiments/37-rq2-san-supp/scripts/smoke_gate.py'
MAX_ATTEMPTS = 2                                        # một lần chạy lại cả job (Le chốt vòng 3); job gate không giới hạn (vòng 4)
KEY_TRIES_FULL = 2                                      # job đầy đủ: key harness_error chạy lại một lần trong cùng job
# Khối OPTION chưa chốt (amendment mục 10: dòng trích dẫn mở đầu bằng OPTION). Dòng trích dẫn (một hay nhiều dấu '>') mà nội dung
# bắt đầu bằng OPTION, có thể sau dấu nhấn mạnh; thêm tiêu đề Markdown bắt đầu bằng OPTION (chặt hơn luật, chỉ theo hướng dừng).
OPTION_QUOTE = re.compile(r'^\s*(?:>\s*)+[*_`#\s]*OPTION\b')
OPTION_HEAD = re.compile(r'^\s*#+\s*[*_`]*OPTION\b')
FROZEN_SAN_FLAGS_EXE = list(CF.SAN_FLAGS_EXE)           # ảnh chụp lúc nạp module, để kiểm danh sách đã freeze không bị sửa tại chỗ
B0_INSTANCE = 'i-01773fe09af1a559c'                     # máy chạy rq2-main exe, nơi có cache build của S₀ (mục 7 bước 2)
B0_DIR = 'ci-out/rq2-san-log'
B0_RUNS = 'rq2-san-log-runs.jsonl'                      # lịch sử các lần chạy B0, job B0 chép tiếp qua mỗi lần (ci/jobs/rq2-san-log.sh)
B0_JOB = 'rq2-san-log'


class Refuse(SystemExit):
    """Từ chối chạy, lớp `fail` (mã 1): lần thử này của job không hoàn tất."""


class Stop(SystemExit):
    """Luật dừng (mã EXIT_STOP): job ghi STOP.txt, lượt không chạy lại."""
    def __init__(self, msg):
        super().__init__(EXIT_STOP)
        self.msg = msg

    def __str__(self): return self.msg


class InputMismatch(RuntimeError):
    """Vector đọc được mà khác bản ghi S₀ (amendment mục 6: khác thì dừng). Không bao giờ hạ thành harness_error."""


class VectorUnreadable(RuntimeError):
    """File vector không đọc được (lỗi hạ tầng của corpus): ở preflight là `fail`, chạy lại được như mọi lỗi hạ tầng."""


# ---------------- cờ build C-san ----------------
def pic_flags():
    """Cờ C-san của lượt này: danh sách đã freeze cộng đúng một cờ (list mới, không sửa config.SAN_FLAGS_EXE)."""
    return list(CF.SAN_FLAGS_EXE) + [PIC_FLAG]


def install_pic():
    """Phép gán I-a. Gọi trong mọi tiến trình build PIC hoặc chạy kiểm sanitizer (initializer của worker)."""
    if CF.SAN_FLAGS_EXE != FROZEN_SAN_FLAGS_EXE: raise RuntimeError('config.SAN_FLAGS_EXE đã bị sửa trong tiến trình')
    BD.SAN_FLAGS_EXE = pic_flags()
    return BD.SAN_FLAGS_EXE


def pic_installed():
    return BD.SAN_FLAGS_EXE == pic_flags() and BD.SAN_FLAGS_EXE is not CF.SAN_FLAGS_EXE


def worker_flags():
    """Cho test: cờ mà một worker thật thấy sau initializer."""
    return list(BD.SAN_FLAGS_EXE), pic_installed(), os.getpid()


def orig_flags_in_effect():
    """Tiến trình đối chứng: cờ của build là đúng đối tượng đã freeze, chưa gán."""
    return BD.SAN_FLAGS_EXE is CF.SAN_FLAGS_EXE and CF.SAN_FLAGS_EXE == FROZEN_SAN_FLAGS_EXE


@contextlib.contextmanager
def configure_only():
    """Cho build_c_exe chạy bước cmake configure như cũ và bỏ bước `cmake --build` (S-ninja: configure cờ gốc, không build). Dùng lại
    nguyên build_c_exe thay vì chép lệnh configure; marker ghi ok false, log là log configure."""
    real = BD.sh

    def sh(cmd, cwd=None, env=None, timeout=3600):
        if list(cmd[:2]) == ['cmake', '--build']: return 'configure_only', '', 0
        return real(cmd, cwd=cwd, env=env, timeout=timeout)
    BD.sh = sh
    try: yield
    finally: BD.sh = real


# ---------------- tiện ích ----------------
def sha_file(p):
    try:
        with open(p, 'rb') as f: return hashlib.sha256(f.read()).hexdigest()
    except OSError: return None


def module_sha():
    """sha256 của file module này (ghi vào manifest và mọi bản ghi; Le chốt vòng 4)."""
    return sha_file(os.path.abspath(__file__))


def jload(p):
    try:
        with open(p) as f: return json.load(f)
    except (OSError, ValueError): return None


def _git(repo, *a):
    return subprocess.run(['git', '-C', repo, *a], capture_output=True, text=True)


def _read(p):
    try: return open(p).read().strip()
    except OSError: return None


def _utc(t=None):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() if t is None else t))


def records(path):
    if not path or not os.path.exists(path): return []
    out = []
    with open(path) as f:
        for l in f:
            try: out.append(json.loads(l))
            except ValueError: pass                              # dòng cuối dở dang (như Store)
    return out


def base_key(k):
    return k[:-len('#error')] if k.endswith('#error') else k


def tree_hashes(wd):
    """sha256 của `driver` và mọi thư viện .so trong thư mục build của một case (review N3: phần lớn code chạy nằm trong .so). Symlink ghi
    đích của link."""
    out = {}
    for root, dirs, files in os.walk(wd):
        dirs.sort()
        for f in sorted(files):
            if not (f == 'driver' or f.endswith('.so') or '.so.' in f): continue
            p = os.path.join(root, f); rel = os.path.relpath(p, wd)
            out[rel] = 'link:' + os.readlink(p) if os.path.islink(p) else sha_file(p)
    return out


# ---------------- cổng ----------------
def option_lines(text):
    """Các dòng mở khối OPTION chưa chốt (rỗng thì đạt)."""
    return [f'{i}: {l.strip()[:120]}' for i, l in enumerate(text.splitlines(), 1) if OPTION_QUOTE.match(l) or OPTION_HEAD.match(l)]


def keys_check(repo, path=KEYS, want=KEYS_SHA256):
    p = os.path.join(repo, path)
    r = dict(path=path, want_sha256=want, ok=False)
    if not os.path.exists(p): return dict(r, reason=f'không có {path}')
    r['sha256'] = sha_file(p)
    if r['sha256'] != want: return dict(r, reason=f'sha256 của {path} là {r["sha256"]}, amendment ghi {want}')
    keys = [l.strip() for l in open(p) if l.strip()]
    if len(keys) != N_KEYS or keys != sorted(set(keys)) or not all(k.startswith(KEY_PREFIX) for k in keys):
        return dict(r, reason=f'{path}: cần {N_KEYS} key khác nhau, đã xếp, tiền tố {KEY_PREFIX}')
    return dict(r, ok=True, reason='ok', keys=keys, n=len(keys), smoke_key=keys[0])


def amendment_check(repo, commit=None, path=AMENDMENT, keys_path=KEYS):
    """Amendment đã commit, commit đó là HEAD hoặc tổ tiên của HEAD, không bị sửa sau commit (blob ở commit = blob ở HEAD, cây làm việc sạch),
    không còn khối OPTION, ghi đúng sha256 của keys.txt và của bản ghi S₀. keys.txt cũng phải đã commit và sạch. Trả dict ghi vào manifest."""
    r = dict(path=path, ok=False, rule='commit là HEAD hoặc tổ tiên; amendment không đổi từ commit tới HEAD và cây làm việc; '
                                       'không có dòng OPTION ở đầu khối trích dẫn')
    head = _git(repo, 'rev-parse', 'HEAD')
    if head.returncode != 0: return dict(r, reason=f'không đọc được HEAD của {repo}')
    r['head'] = head.stdout.strip()
    if not commit:
        commit = _git(repo, 'log', '-1', '--format=%H', 'HEAD', '--', path).stdout.strip()
        if not commit: return dict(r, reason=f'{path} chưa được commit')
        r['commit_source'] = 'git log -1 HEAD -- <amendment>'
    else:
        r['commit_source'] = 'tham số'
    c = _git(repo, 'rev-parse', '-q', '--verify', f'{commit}^{{commit}}')
    if c.returncode != 0 or not c.stdout.strip(): return dict(r, reason=f'commit {commit} không tồn tại')
    commit = r['commit'] = c.stdout.strip()
    if _git(repo, 'merge-base', '--is-ancestor', commit, r['head']).returncode != 0:
        return dict(r, reason=f'commit amendment {commit} không phải HEAD hay tổ tiên của HEAD {r["head"]} (hoặc clone nông)')
    b_c, b_h = (_git(repo, 'rev-parse', f'{x}:{path}') for x in (commit, r['head']))
    if b_c.returncode != 0: return dict(r, reason=f'{path} không có trong commit {commit}')
    r['blob'] = b_c.stdout.strip()
    if b_h.returncode != 0 or b_h.stdout.strip() != r['blob']: return dict(r, reason=f'{path} ở HEAD khác bản ở commit {commit}')
    for p in (path, keys_path):
        st = _git(repo, 'status', '--porcelain', '--untracked-files=all', '--', p)
        if st.returncode != 0 or st.stdout.strip(): return dict(r, reason=f'{p} chưa commit hoặc có thay đổi chưa commit')
    text = _git(repo, 'show', f'{commit}:{path}').stdout
    r['sha256'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
    bad = option_lines(text)
    if bad: return dict(r, reason=f'amendment còn khối OPTION: {bad[:3]}', option_lines=bad)
    missing = [h for h in (KEYS_SHA256, S0_SHA256) if h not in text]
    if missing: return dict(r, reason=f'amendment không ghi sha256 {missing} (hằng của module lệch amendment)')
    return dict(r, ok=True, reason='ok')


def machine_info_retry(tries=IMDS_TRIES, pause=IMDS_WAIT, fn=None):
    """machine_info đã freeze (IMDSv2, 1 giây mỗi lần gọi), thử lại tới khi đọc đủ instance id, loại máy, AMI (review L1)."""
    fn = fn or machine_info
    m = {}
    for i in range(tries):
        m = fn()
        if all(m.get(k) for k in IMDS_KEYS): return dict(m, imds_tries=i + 1)
        if i < tries - 1: time.sleep(pause)
    return dict(m, imds_tries=tries, imds_unreadable=True)


def env_check(minfo=None, clang=None, gcc=None, clang_rt=None):
    """Môi trường mục 7: loại máy, AMI, clang 18.1.3, gcc 13.3, libclang-rt-18-dev; instance id phải đọc được. Lớp `fail` (Le chốt
    2026-11-05): lệch hay không đọc được đều phát hiện trước mọi build hay thực thi, job ghi lý do, không ghi STOP.txt."""
    m = minfo if minfo is not None else machine_info_retry()
    clang = clang if clang is not None else tool(['clang', '--version'])
    gcc = gcc if gcc is not None else tool(['gcc', '--version'])
    rt = clang_rt if clang_rt is not None else tool(['sh', '-c', "dpkg-query -W -f='${Version}' libclang-rt-18-dev 2>/dev/null || echo 'không có'"])
    unreadable = [k for k in IMDS_KEYS if not m.get(k)]
    got = dict(instance_type=m.get('instance_type'), ami_id=m.get('ami_id'), clang=clang, gcc=gcc, libclang_rt=rt,
               instance_id=m.get('instance_id'))
    bad = [k for k, v in ENV_REQ.items() if k not in unreadable and not str(got.get(k) or '').startswith(v)]
    if not GCC_RE.search(gcc or ''): bad.append('gcc')
    if not rt or rt.startswith('n/a') or 'không có' in rt: bad.append('libclang_rt')
    ok = not bad and not unreadable
    reason = 'ok' if ok else '; '.join(([f'không đọc được IMDS sau {m.get("imds_tries", "?")} lần: {unreadable}'] if unreadable else []) +
                                        ([f'môi trường lệch mục 7: {bad}'] if bad else []))
    return dict(ok=ok, reason=reason, unreadable=unreadable, mismatch=bad, want=dict(ENV_REQ, gcc='13.3', libclang_rt='có'), got=got,
                machine=m, cmake=tool(['cmake', '--version']), ninja=tool(['ninja', '--version']), loadavg=_read('/proc/loadavg'))


def tractor_check():
    d = f'{CF.CORPUS}/tractor'
    h = _git(d, 'rev-parse', 'HEAD').stdout.strip()
    return dict(ok=h == CF.TRACTOR_COMMIT, head=h, want=CF.TRACTOR_COMMIT,
                reason='ok' if h == CF.TRACTOR_COMMIT else f'TRACTOR ở {h or "?"}, cần {CF.TRACTOR_COMMIT}')


def deadline_epoch():
    return calendar.timegm(time.strptime(DEADLINE_UTC, '%Y-%m-%dT%H:%M:%SZ'))


def deadline_check(now=None):
    now = time.time() if now is None else now
    dl = deadline_epoch()
    return dict(ok=now < dl, deadline_utc=DEADLINE_UTC, now_utc=_utc(now),
                reason='ok' if now < dl else 'đã quá hạn chót của luật dừng mục 10')


def inputs_check(s0, troot=None):
    """Amendment mục 6: đọc lại vector của cả 36 key và so với trường `input` đã lưu, kiểm san_timeout của S₀, trước mọi lần thực thi. Không
    chạy gì. Đọc được mà lệch (bad) là luật dừng; file không đọc được (unreadable) là `fail` (review R2-05)."""
    bad, unreadable = [], []
    for k, rec in sorted(s0.items()):
        try:
            for v in rec['vectors']:
                if v.get('san_timeout') != rec['timeout'] * R1.SAN_TIMEOUT_FACTOR: raise InputMismatch(f'{k}: san_timeout lệch timeout của case')
                vector_input(rec['bundle'], rec['case'], v['vector'], v, troot)
        except VectorUnreadable as e:
            unreadable.append(str(e)[:300])
        except (InputMismatch, ValueError, KeyError) as e:
            bad.append(f'{type(e).__name__}: {e}'[:300])
    return dict(ok=not bad and not unreadable, n_keys=len(s0), bad=bad[:10], unreadable=unreadable[:10],
                reason='ok' if not bad and not unreadable else f'{len(bad)} key lệch input hoặc S₀, {len(unreadable)} không đọc được vector')


def preflight(repo, a, need_env=True, need_corpus=True):
    """Mọi cổng trước khi build hoặc chạy. Trả dict; ok khi mọi mục ok. Có --s0 thì thêm cổng s0 (sha256, từng bản ghi), inputs (vector đọc
    được mà lệch) và vector_files (không đọc được), cho cả 36 key; chỉ khi TRACTOR đúng commit, vì vector đọc từ corpus."""
    from .main_run import freeze_check
    g = dict(keys=keys_check(repo, a.keys), amendment=amendment_check(repo, a.amendment_commit, keys_path=a.keys))
    g['freeze'] = (dict(ok=False, tag=a.freeze_tag, reason=f'lượt này chạy ở tag {FREEZE_TAG} (Le chốt); tham số là {a.freeze_tag}')
                   if a.freeze_tag != FREEZE_TAG else freeze_check(a.freeze_tag, repo))
    g['deadline'] = deadline_check()
    if need_env: g['env'] = env_check()
    if need_corpus: g['tractor'] = tractor_check()
    s0path = getattr(a, 's0', None)
    if s0path and g['keys']['ok']:
        try:
            s0, info = load_s0(s0path, g['keys']['keys'])
            g['s0'] = dict(ok=True, reason='ok', **info)
            if not need_corpus or g['tractor']['ok']:
                ic = inputs_check(s0)
                g['inputs'] = dict(ok=not ic['bad'], n_keys=ic['n_keys'], bad=ic['bad'],
                                   reason='ok' if not ic['bad'] else f'{len(ic["bad"])} key lệch input hoặc S₀: {ic["bad"][:2]}')
                g['vector_files'] = dict(ok=not ic['unreadable'], unreadable=ic['unreadable'],
                                         reason='ok' if not ic['unreadable'] else f'không đọc được vector: {ic["unreadable"][:2]}')
        except Refuse as e:
            g['s0'] = dict(ok=False, reason=str(e))
    g['ok'] = all(v['ok'] for v in g.values() if isinstance(v, dict))
    g['failed'] = [k for k, v in g.items() if isinstance(v, dict) and not v['ok']]
    return g


def classify(g):
    """'ok', 'stop' (luật dừng) hoặc 'fail' (lần thử này không hoàn tất)."""
    failed = set(g.get('failed') or [])
    if not failed: return 'ok'
    return 'stop' if failed & STOP_GATES else 'fail'


def require(g):
    cls = classify(g)
    if cls == 'ok': return
    msg = 'Từ chối: ' + '; '.join(f'{k}: {g[k]["reason"]}' for k in g['failed'])
    if cls == 'stop': raise Stop(msg)
    raise Refuse(msg)


# ---------------- bản ghi S₀ ----------------
def is_sbf(v):
    return v.get('outcome') == 'incomplete' and v.get('reason') == 'san_build_failed'


def load_s0(path, keys, want=S0_SHA256):
    """{key: bản ghi S₀} của đúng các key; kiểm sha256 file và từng bản ghi là not_re_examined vì san_build_failed, chưa có lần thử C-san."""
    got = sha_file(path)
    if got != want: raise Refuse(f'sha256 bản ghi S₀ {path} là {got}, amendment ghi {want}')
    recs = [json.loads(l) for l in open(path) if l.strip()]
    by = collections.defaultdict(list)
    for r in recs: by[r['key']].append(r)
    mech = sorted(r['key'] for r in recs if TARGET_REASON in (r.get('reasons') or []))
    if mech != sorted(keys): raise Refuse('danh sách key sinh lại từ S₀ khác keys.txt')
    out = {}
    for k in keys:
        rs = by.get(k) or []
        if len(rs) != 1: raise Refuse(f'S₀ có {len(rs)} bản ghi cho {k}')
        r = rs[0]
        vs = r.get('vectors') or []
        if r.get('outcome') != 'not_re_examined' or r.get('reasons') != [TARGET_REASON] or len(vs) != 1 or not all(is_sbf(v) for v in vs):
            raise Refuse(f'bản ghi S₀ của {k} không phải một vector san_build_failed')
        if any(v.get('san_attempts') != 0 or (v.get('obs') or {}).get('san', {}).get('attempts') for v in vs):
            raise Refuse(f'bản ghi S₀ của {k} đã có lần thử C-san')
        out[k] = r
    return out, dict(path=os.path.abspath(path), sha256=got, source=S0_SOURCE, n_records=len(recs))


def decision_runs(v):
    """Quan sát dùng để quyết định ở mỗi rep, giải mã như rq2.recompute_vector (lần chạy lại khi reran)."""
    out = []
    for e in v['obs']['runs']:
        ph = e['rerun'] if e['reran'] else e['first']
        out.append((R2.dec_obs(ph['c'], 'exe'), R2.dec_obs(ph['r'], 'exe'), e['reran']))
    return out


def vector_input(bundle, case, name, v, troot=None):
    """argv, stdin, env như rq2_pair; so sha256 từng blob với trường `input` đã lưu (amendment mục 6). Không đọc được file: VectorUnreadable
    (`fail`); đọc được mà khác (kể cả không phân tích được, rỗng): InputMismatch (dừng)."""
    from .vectors import read_vector, to_bytes, u2b
    try: vec = read_vector(f'{troot or CF.T}/{bundle}/{case}/test_vectors/{name}')
    except OSError as e: raise VectorUnreadable(f'{bundle}/{case}/{name}: không đọc được vector ({type(e).__name__})')
    except ValueError as e: raise InputMismatch(f'{bundle}/{case}/{name}: vector không phân tích được ({type(e).__name__})')
    if not vec: raise InputMismatch(f'{bundle}/{case}/{name}: vector rỗng')
    argv = [u2b(x) for x in (vec.get('argv') or [])]; stdin = u2b(vec.get('stdin') or ''); env = vec.get('env')
    st = v['input']
    got = dict(argv=[blob(to_bytes(x))['sha256'] for x in argv], stdin=blob(to_bytes(stdin))['sha256'], env=env, has_ub='has_ub' in vec)
    want = dict(argv=[b['sha256'] for b in st['argv']], stdin=st['stdin']['sha256'], env=st['env'], has_ub=v.get('has_ub'))
    if got != want: raise InputMismatch(f'{bundle}/{case}/{name}: input khác bản ghi S₀ ({got} != {want})')
    return argv, stdin, env


def new_vector(v, san, sink, outcome, reason, runs):
    """Bản ghi vector mới: trường như examine_vector (san, san_markers, san_attempts, san_cause, obs.san gồm mọi lần thử); obs.runs, runs,
    c_stable, input, output đã lưu giữ nguyên từ S₀. Trường `s0` giữ kết quả S₀ của vector."""
    d = {k: x for k, x in v.items() if k != 'would_be'}
    d.update(outcome=outcome, reason=reason, san=san['status'], san_markers=san.get('markers'), san_attempts=san.get('attempts'),
             san_cause=san.get('cause'),
             obs=dict(runs=v['obs']['runs'], san=dict(result=dict(san), attempts=[R2._enc_san_attempt(x, 'exe') for x in sink])),
             s0={k: v.get(k) for k in ('outcome', 'reason', 'san', 'san_cause', 'san_attempts', 'san_markers')})
    if reason == 'sanitizer_inconclusive':                      # như examine_vector: hướng của vector bị chặn bởi kiểm inconclusive
        c0 = runs[0][0]
        c_stable = all(R2._equal(c0, c, 'exe') for c, _, _ in runs[1:])
        all_differ = all(not R2._equal(c, r, 'exe') for c, r, _ in runs)
        d['would_be'] = 'supports_rejection' if c_stable and all_differ else 'agrees'
    return d


def supp_key(B, rec, san_fn=None, require_cached=True, troot=None, ctx=None):
    """Một key: build C-san PIC (đã cache ở bước 3), kiểm sanitizer phía C của mọi vector, tính lại outcome. Trả bản ghi cấp bản dịch."""
    t0 = time.time(); u0 = _utc(t0)
    if not pic_installed(): raise RuntimeError('SAN_FLAGS_EXE chưa được gán cờ PIC trong tiến trình này')
    bundle, case = rec['bundle'], rec['case']
    marker = f'{B}/c-san/{bundle}/{case}.build.json'
    if require_cached and not os.path.exists(marker): raise RuntimeError(f'chưa có build PIC đã qua cổng smoke: {marker}')
    cs = BD.build_c_exe(B, bundle, case, san=True)
    files = tree_hashes(f'{B}/c-san/{bundle}/{case}')
    timeout = rec['timeout']                                     # timeout theo case của S₀, không tính lại case_timeout (mục 6)
    vecs = []
    for v in rec['vectors']:
        if v.get('san_timeout') != timeout * R1.SAN_TIMEOUT_FACTOR: raise InputMismatch(f'{rec["key"]}: san_timeout lệch timeout của case')
        argv, stdin, env = vector_input(bundle, case, v['vector'], v, troot)
        runs = decision_runs(v)
        sink = []
        san = (san_fn or R1._exe_san)(cs, argv, stdin, timeout, env, runs[0][0]['status'], sink=sink)
        outcome, reason = R2.vector_outcome(runs, san['status'], 'exe', san.get('cause'))
        d = new_vector(v, san, sink, outcome, reason, runs)
        if tuple(R2.recompute_vector(d, 'exe')) != (outcome, reason): raise RuntimeError(f'{rec["key"]}: recompute_vector lệch')
        vecs.append(d)
    outcome, reasons = R2.translation_outcome([(x['outcome'], x['reason']) for x in vecs])
    base = {k: x for k, x in rec.items() if k not in ('outcome', 'reason', 'reasons', 'vectors', 'vector_outcomes', 'secs')}
    base.update(c_san_ok=cs.get('ok'), s0_outcome=rec['outcome'], s0_reason=rec['reason'], s0_reasons=rec['reasons'])
    return R2._done(base, outcome, reasons, vectors=vecs, vector_outcomes=dict(collections.Counter(x['outcome'] for x in vecs)),
                    secs=round(time.time() - t0, 2),
                    supp=dict(amendment=AMENDMENT, san_flags_exe=list(BD.SAN_FLAGS_EXE), utc_start=u0, utc_end=_utc(),
                              build=dict({k: cs.get(k) for k in ('ok', 'bin', 'sha256', 'preset', 'secs')}, files=files), **(ctx or {})))


def _safe_key(B, rec, ctx=None):
    """Lỗi của module thành bản ghi harness_error (mục 7 bước 5). InputMismatch không bị hạ: nó lan lên cmd_run, là luật dừng."""
    try: return supp_key(B, rec, ctx=ctx)
    except InputMismatch: raise
    except Exception:
        return dict(key=f'{rec["key"]}#error', status='harness_error', reason='harness_error', error=traceback.format_exc()[-3000:],
                    supp=dict(utc_end=_utc(), **(ctx or {})))


def _build_one(B, bundle, case):
    if not pic_installed(): raise RuntimeError('SAN_FLAGS_EXE chưa được gán cờ PIC trong tiến trình này')
    info = BD.build_c_exe(B, bundle, case, san=True)
    return dict(info, files=tree_hashes(f'{B}/c-san/{bundle}/{case}'))


def _cases(keys):
    return [tuple(k.split('/')[1:3]) for k in keys]


# ---------------- một job một đoạn: nhánh đã nộp và số lần thử (amendment mục 7 bước 5; Le chốt vòng 3, vòng 4) ----------------
def job_refs(listing, job):
    """Các ref đã nộp của một job trong output `git ls-remote`: results/<job> và results-failed/<job>-<run id> (guard của bước Publish đẩy
    sang đó khi bản mới có ít dòng rq[12]-*.jsonl hơn nhánh hiện có)."""
    pat = re.compile(rf'^refs/heads/(results/{re.escape(job)}|results-failed/{re.escape(job)}-\d+)$')
    out = []
    for line in (listing or '').splitlines():
        p = line.split()
        if len(p) == 2 and pat.match(p[1]): out.append((p[1], p[0]))
    return sorted(out)


def _jsonl(text):
    out = []
    for l in (text or '').splitlines():
        try: x = json.loads(l)
        except ValueError: continue
        if isinstance(x, dict): out.append(x)
    return out


def published(repo, ref, job):
    """Trạng thái một lần nộp: STOP.txt, complete.json, noop.txt, attempt.json, có run/manifest.json hay không (lần thử đã tính), các dòng
    rq2-supp-runs.jsonl (lịch sử lần thử chép tiếp). Tải lỗi thì Refuse (`fail`)."""
    local = 'refs/supp-scan/' + ref[len('refs/heads/'):]
    f = _git(repo, 'fetch', '-q', '--depth=1', 'origin', f'+{ref}:{local}')
    if f.returncode != 0: raise Refuse(f'{ref} có trên remote mà tải lỗi: {f.stderr.strip()[:200]}')
    c = _git(repo, 'rev-parse', local).stdout.strip()
    show = lambda name: _git(repo, 'show', f'{c}:ci-out/{job}/{name}')
    st, a = show('STOP.txt'), show(ATTEMPT)
    try: ad = json.loads(a.stdout) if a.returncode == 0 else {}
    except ValueError: ad = {}
    ad = ad if isinstance(ad, dict) else {}
    try: n = int(ad.get('attempt'))
    except (ValueError, TypeError): n = None
    h = show(RUNS)
    noop = show(NOOP).returncode == 0
    return dict(job=job, ref=ref, commit=c, stop=(st.stdout.strip().splitlines() or ['STOP.txt'])[0] if st.returncode == 0 else None,
                complete=show(COMPLETE).returncode == 0, noop=noop, attempt=n, run_id=ad.get('run_id'), run_attempt=ad.get('run_attempt'),
                counted=show(RUN_MANIFEST).returncode == 0 and not noop, history=_jsonl(h.stdout) if h.returncode == 0 else [])


def scan_remote(repo, jobs=tuple(JOBS.values())):
    """Mọi lần nộp của ba job trên remote (git ls-remote rồi fetch từng ref). ls-remote lỗi thì Refuse (`fail`)."""
    ls = _git(repo, 'ls-remote', 'origin', 'refs/heads/results/rq2-san-supp*', 'refs/heads/results-failed/rq2-san-supp*')
    if ls.returncode != 0: raise Refuse(f'git ls-remote lỗi (mã {ls.returncode}): {ls.stderr.strip()[:200]}')
    return [published(repo, ref, j) for j in jobs for ref, _ in job_refs(ls.stdout, j)]


def counted_attempts(found, job):
    """Các lần thử đã tính của một job (Le chốt vòng 4): hợp các dòng rq2-supp-runs.jsonl của mọi lần nộp (results/, results-failed/), bỏ
    trùng; cộng lần nộp có run/manifest.json mà lịch sử của chính nó thiếu dòng của nó (không xảy ra với code này; tính để không đếm thiếu)."""
    lines, seen = [], set()
    for x in found:
        if x['job'] != job: continue
        for l in x['history']:
            k = json.dumps(l, sort_keys=True)
            if k not in seen: seen.add(k); lines.append(l)
    for x in found:
        if x['job'] != job or not x['counted']: continue
        own = [l for l in x['history'] if l.get('attempt') == x['attempt'] and l.get('run_id') == x['run_id']
               and l.get('run_attempt') == x['run_attempt']]
        l = dict(attempt=x['attempt'] or 1, run_id=x['run_id'], run_attempt=x['run_attempt'], ref=x['ref'], from_ref_without_history=True)
        k = json.dumps(l, sort_keys=True)
        if not own and k not in seen: seen.add(k); lines.append(l)
    return sorted(lines, key=lambda l: (l.get('attempt') or 0, str(l.get('utc'))))


def attempt_decision(found, mode, declared=1):
    """(lớp, lý do, số lần thử). Lớp: 'stop' (STOP.txt ở bất kỳ nhánh nào, hoặc đây sẽ là lần thử thứ ba), 'noop' (job này đã hoàn tất;
    smoke và full đã hoàn tất; job gate khi smoke đã hoàn tất: không chạy, không kiểm hạn chót), 'ok'. Job smoke, đầy đủ:
    n = max(declared, lần thử đã tính lớn nhất + 1, số lần thử đã tính + 1) (Le chốt vòng 4). Job gate không giới hạn lần thử."""
    job = JOBS[mode]
    stops = [x for x in found if x['stop']]
    if stops: return 'stop', f'{stops[0]["ref"]} có STOP.txt: {stops[0]["stop"]}', None
    done = {x['job'] for x in found if x['complete']}
    if job in done: return 'noop', f'results của {job} đã hoàn tất, không chạy lại', None
    if {JOBS['smoke'], JOBS['full']} <= done: return 'noop', 'job smoke và job đầy đủ đã hoàn tất, không chạy gì', None
    if mode == 'gate':
        if JOBS['smoke'] in done: return 'noop', 'job smoke đã hoàn tất, job gate không chạy', None
        n = 1 + sum(1 for x in found if x['job'] == job and not x['noop'])
        return 'ok', f'job {job}: lần chạy thứ {n} (job gate không giới hạn lần thử)', n
    prior = [int(l.get('attempt') or 1) for l in counted_attempts(found, job)]
    n = max([int(declared or 1), len(prior) + 1] + [p + 1 for p in prior])
    if n > MAX_ATTEMPTS:
        return 'stop', f'job {job}: lần thử thứ {n}; đã có {n - 1} lần thử không hoàn tất (tối đa {MAX_ATTEMPTS} lần)', n
    return 'ok', f'job {job}: lần thử thứ {n} (khai báo {declared}, đã tính {sorted(prior)})', n


def cmd_scan(a, repo):
    found = scan_remote(repo)
    cls, why, n = attempt_decision(found, a.mode, a.declared_attempt)
    doc = dict(job=JOBS[a.mode], mode=a.mode, attempt=n, declared=a.declared_attempt, decision=cls, reason=why, found=found, utc=_utc(),
               run_id=os.environ.get('GITHUB_RUN_ID'), run_attempt=os.environ.get('GITHUB_RUN_ATTEMPT'), module_sha256=module_sha())
    os.makedirs(a.out, exist_ok=True)
    print(json.dumps(doc, ensure_ascii=False))
    if cls == 'noop':
        open(f'{a.out}/{NOOP}', 'w').write(why + '\n'); raise SystemExit(EXIT_NOOP)
    if cls == 'stop': raise Stop(why)
    json.dump(doc, open(f'{a.out}/{ATTEMPT}', 'w'), indent=1, ensure_ascii=False)
    hist = counted_attempts(found, JOBS[a.mode]) if a.mode != 'gate' else []
    if hist:                                                   # chép tiếp lịch sử để guard Publish không cho lần nộp sau đè mất nó
        with open(f'{a.out}/{RUNS}', 'w') as f:
            for l in hist: f.write(json.dumps(l, ensure_ascii=False, sort_keys=True) + '\n')
    print(f'ATTEMPT={n}')


def history_append(path, line):
    """Dòng của lần thử này (gọi ngay sau khi ghi run/manifest.json, trước khi giao key)."""
    if not path: return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'a') as f: f.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + '\n')


# ---------------- lệnh ----------------
def gate_check(path, cases):
    """Cổng smoke build đã đạt cho đúng các case."""
    g = jload(path) if path else None
    if not g: return dict(ok=False, reason=f'không đọc được {path}')
    ok = g.get('ok') is True and all((g.get('conditions') or {}).values()) and sorted(g.get('per_case') or {}) == sorted(cases)
    return dict(ok=ok, path=os.path.abspath(path), sha256=sha_file(path), reason='ok' if ok else 'cổng smoke build chưa đạt cho đủ 36 case')


def _params(mode, g, a, **kw):
    return dict(cmd='rq2_san_supp', mode=mode, gates=g, freeze_tag=a.freeze_tag, workers=getattr(a, 'workers', None),
                frozen_san_flags_exe=FROZEN_SAN_FLAGS_EXE, pic_flag=PIC_FLAG, san_attempts=R1.SAN_ATTEMPTS,
                san_timeout_factor=R1.SAN_TIMEOUT_FACTOR, exe_san_env=R1.EXE_SAN_ENV, mem_limit=OB.MEM_LIMIT, reps=R2.REPS,
                corpus_pin=_read(f'{CF.REPO}/experiments/02-harvest-repro/results/corpus-pin.txt'), deadline_utc=DEADLINE_UTC,
                b0_result=getattr(a, 'b0_result', None), module_sha256=module_sha(),
                smoke_gate_sha256=sha_file(f'{CF.REPO}/{SMOKE_GATE_PY}'), **kw)


def cmd_check(a, repo):
    g = preflight(repo, a)
    g['class'] = classify(g)
    print(json.dumps(g, ensure_ascii=False, indent=1))
    require(g)


def cmd_orig(a, repo):
    """S-orig (build đủ case smoke với cờ gốc) và S-ninja (configure cờ gốc các case còn lại). Không gán cờ trong tiến trình này."""
    if not orig_flags_in_effect(): raise Refuse('tiến trình đối chứng có SAN_FLAGS_EXE khác danh sách đã freeze')
    Bo, B = os.path.realpath(a.orig_root), os.path.realpath(a.build_root)
    if Bo == B: raise Refuse('thư mục build đối chứng trùng thư mục build PIC')
    g = preflight(repo, a); require(g)
    keys = g['keys']['keys']
    os.makedirs(a.out, exist_ok=True)
    manifest(a.out, _params('orig', g, a, orig_root=Bo, configure_rest=a.configure_rest, san_flags_exe=list(BD.SAN_FLAGS_EXE)))
    res = {}
    for i, (bundle, case) in enumerate(_cases(keys)):
        if i == 0:
            info = BD.build_c_exe(Bo, bundle, case, san=True); res[case] = dict(mode='build', **info)
        elif a.configure_rest:
            with configure_only(): info = BD.build_c_exe(Bo, bundle, case, san=True)
            res[case] = dict(mode='configure_only', **info)
        else: continue
        print(case, res[case]['mode'], 'ok' if info.get('ok') else 'ok=false', flush=True)
    json.dump(res, open(f'{a.out}/orig-builds.json', 'w'), indent=1, ensure_ascii=False)


def cmd_build(a, repo):
    """S-pic: build PIC của mọi key (không thực thi binary nào), tuần tự (BUILD_WORKERS). Ghi builds.json (marker và sha256 của driver, .so
    từng case) cho job đầy đủ và recompute đối chiếu. Có build không thành công: mã EXIT_BUILD (4), để cổng smoke xếp S-pic không đạt;
    preflight từ chối thì mã 1 hoặc 3 như mọi lệnh (review R2-03)."""
    g = preflight(repo, a); require(g)
    B = os.path.realpath(a.build_root)
    if B == os.path.realpath(a.orig_root): raise Refuse('thư mục build PIC trùng thư mục build đối chứng')
    install_pic()
    os.makedirs(a.out, exist_ok=True)
    manifest(a.out, _params('build', g, a, build_root=B, san_flags_exe=list(BD.SAN_FLAGS_EXE)))
    res = {}
    with ProcessPoolExecutor(a.workers, initializer=install_pic) as ex:
        futs = {ex.submit(_build_one, B, b, c): c for b, c in _cases(g['keys']['keys'])}
        for f, c in futs.items():
            res[c] = f.result(); print(c, 'ok' if res[c].get('ok') else 'BUILD LỖI', flush=True)
    json.dump(dict(build_root=B, san_flags_exe=list(BD.SAN_FLAGS_EXE), workers=a.workers, builds=dict(sorted(res.items()))),
              open(f'{a.out}/builds.json', 'w'), indent=1, ensure_ascii=False)
    if not all(x.get('ok') for x in res.values()): raise SystemExit(EXIT_BUILD)


def expect_builds(path, B, keys):
    """Job đầy đủ: marker build PIC hiện có và sha256 của driver, .so phải trùng builds.json của job smoke (cùng build đã qua cổng)."""
    want = (jload(path) or {}).get('builds') or {}
    bad = []
    for bundle, case in _cases(keys):
        m = f'{B}/c-san/{bundle}/{case}.build.json'
        got = jload(m) or {}
        w = want.get(case) or {}
        if not got.get('ok') or got.get('sha256') != w.get('sha256') or not w.get('files') \
                or tree_hashes(f'{B}/c-san/{bundle}/{case}') != w.get('files'):
            bad.append(case)
    if bad: raise Refuse(f'build PIC khác bản đã qua cổng smoke (hoặc thiếu): {bad[:5]}')


def cmd_run(a, repo):
    """Một đoạn duy nhất: chạy mọi key của chế độ. Từ chối trước khi ghi run/manifest.json thì lần chạy không được tính là lần thử; sau đó
    thì có (Le chốt vòng 4). Mã 0 chỉ khi mọi key có bản ghi cuối (job đầy đủ: bản ghi kết quả, hoặc hai bản ghi harness_error); harness_error
    của key smoke, worker hỏng: Refuse (lần thử của job không hoàn tất); hạn chót, input lệch, bản ghi xong sau hạn chót: Stop."""
    mode = 'smoke' if a.smoke else 'full'
    g = preflight(repo, a); require(g)
    keys = g['keys']['keys']
    sel = keys[:1] if mode == 'smoke' else keys[1:]
    store_path = f'{a.out}/{OUT_NAME}'
    if records(store_path): raise Refuse(f'{store_path} đã có bản ghi: mỗi job chạy một đoạn, thư mục ra phải trống')
    if mode == 'full' and a.workers != WORKERS: raise Refuse(f'job đầy đủ chạy {WORKERS} worker (mục 7); tham số --workers là {a.workers}')
    gc = gate_check(a.gate_json, [c for _, c in _cases(keys)])
    if not gc['ok']: raise Refuse(f'--gate-json: {gc["reason"]}')
    B = os.path.realpath(a.build_root)
    if a.expect_builds: expect_builds(a.expect_builds, B, sel)
    s0, s0info = load_s0(a.s0, keys)
    install_pic()
    commit = g['amendment'].get('commit')
    iid = (g.get('env') or {}).get('machine', {}).get('instance_id')
    os.makedirs(a.out, exist_ok=True)
    msha = module_sha()
    manifest(a.out, _params(mode, g, a, build_root=B, s0=s0info, selected=sel, san_flags_exe=list(BD.SAN_FLAGS_EXE),
                            expect_builds=a.expect_builds, gate_json=gc, key_tries=KEY_TRIES_FULL if mode == 'full' else 1, attempt=a.attempt))
    # Từ đây lần chạy là một lần thử (Le chốt vòng 4): ghi dòng lịch sử trước khi giao key đầu tiên
    history_append(a.history, dict(job=JOBS[mode], mode=mode, attempt=a.attempt, run_id=os.environ.get('GITHUB_RUN_ID'),
                                   run_attempt=os.environ.get('GITHUB_RUN_ATTEMPT'), utc=_utc(), module_sha256=msha,
                                   amendment_commit=commit, instance_id=iid))
    store = Store(store_path)
    print(f'rq2_san_supp {mode}: {len(sel)} key, {a.workers} worker', flush=True)
    t0 = time.time(); pending = list(sel); inflight = {}; tries = collections.Counter(); written = []
    stop_msg = broken = None
    with ProcessPoolExecutor(a.workers, initializer=install_pic) as ex:
        while pending or inflight:
            while pending and len(inflight) < a.workers and not broken and not stop_msg:
                dl = deadline_check()                              # hạn chót kiểm trước mỗi lần giao key
                if not dl['ok']: stop_msg = f'{dl["reason"]} ({dl["now_utc"]}); còn {len(pending)} key chưa giao'; break
                k = pending.pop(0); tries[k] += 1
                ctx = dict(try_no=tries[k], amendment_commit=commit, instance_id=iid, module_sha256=msha)
                try: inflight[ex.submit(_safe_key, B, s0[k], ctx)] = k
                except Exception as e:                             # pool hỏng lúc giao key: lần thử của job không hoàn tất
                    broken = f'{type(e).__name__}: {e}'; pending.clear(); break
            if not inflight: break
            done, _ = wait(list(inflight), return_when=FIRST_COMPLETED)
            for f in done:
                k = inflight.pop(f)
                try: r = f.result()
                except InputMismatch as e:
                    stop_msg = stop_msg or f'input lệch S₀ (mục 6): {e}'; pending.clear(); continue
                except Exception as e:                             # worker chết (BrokenProcessPool...): lần thử của job không hoàn tất
                    broken = broken or f'{type(e).__name__}: {e}'; pending.clear(); continue
                store.put(r); written.append(r)
                print(r.get('key'), r.get('outcome') or r.get('status'), r.get('reasons'), flush=True)
                if r.get('status') == 'harness_error' and mode == 'full' and tries[k] < KEY_TRIES_FULL and not stop_msg and not broken:
                    pending.append(k)                              # chạy lại một lần trong cùng job (mục 7 bước 5)
            if stop_msg or broken: pending.clear()
    late = [r['key'] for r in written if not (r.get('supp') or {}).get('utc_end') or r['supp']['utc_end'] >= DEADLINE_UTC]
    errs = [base_key(r['key']) for r in written if r.get('status') == 'harness_error']
    m = jload(f'{a.out}/manifest.json') or {}
    m.update(finished_utc=_utc(), wall_secs=round(time.time() - t0, 2), stop=stop_msg, broken=broken, late=late,
             harness_error_tries=dict(collections.Counter(errs)))
    json.dump(m, open(f'{a.out}/manifest.json', 'w'), indent=1, ensure_ascii=False)
    if stop_msg: raise Stop(stop_msg)
    if late: raise Stop(f'{len(late)} bản ghi xong sau hạn chót {DEADLINE_UTC} (mục 10): {late[:3]}')
    if broken: raise Refuse(f'worker hỏng, lần thử này của job không hoàn tất: {broken}')
    if mode == 'smoke' and errs: raise Refuse(f'key smoke {errs[0]} là harness_error: lần thử này của job smoke không hoàn tất')
    print(f'rq2_san_supp {mode}: xong, {len(written)} bản ghi, harness_error {len(errs)}', flush=True)


# ---------------- quyết định của job CI (test được) ----------------
B0_MACHINE = re.compile(r'^máy: instance_id=(\S*)', re.M)


def b0_branch(text, want=B0_INSTANCE):
    """Nhánh B0 (mục 7 bước 2) từ summary.txt của một lần chạy B0. Trả (nhánh, lý do): 'a', 'b' đi tiếp; 'c' luật dừng; 'fail' (chạy lại
    B0): không đọc được, instance id không đọc được, hoặc B0 chạy trên máy khác máy của S₀ (Le chốt vòng 3, review R2-02)."""
    if not text: return 'fail', 'không có summary.txt của B0'
    m = B0_MACHINE.search(text)
    if not m: return 'fail', 'summary B0 không có dòng `máy:`'
    iid = m.group(1)
    if not iid or iid == 'None': return 'fail', 'B0 không đọc được instance id (chạy lại B0)'
    if iid != want: return 'fail', f'B0 chạy trên {iid}, cần {want}: chạy lại B0 khi chỉ máy đó online'
    concl = next((l for l in text.splitlines() if l.startswith('KẾT LUẬN:')), None)
    if concl is None: return 'fail', 'summary B0 không có dòng KẾT LUẬN (B0 chưa chạy xong)'
    if 'KHÔNG tồn tại' in concl: return 'b', concl
    if concl.startswith('KẾT LUẬN: TRÙNG '): return 'a', concl
    return 'c', concl


def b0_collect(repo):
    """Mọi lần nộp của B0 (Le chốt vòng 4): results/rq2-san-log và mọi results-failed/rq2-san-log-<run> (git ls-remote, rồi fetch từng ref,
    không --depth). Bước Publish commit trên commit nguồn rồi push -f, nên mỗi ref chỉ có một commit kết quả: đọc summary.txt và các dòng
    rq2-san-log-runs.jsonl ở đầu mỗi ref. ls-remote hay fetch lỗi thì Refuse (`fail`). Trả dict(head, refs, history): head là đầu
    results/rq2-san-log (None khi chưa có), history là list (ref, nguồn, summary)."""
    ls = _git(repo, 'ls-remote', 'origin', f'refs/heads/results/{B0_JOB}', f'refs/heads/results-failed/{B0_JOB}-*')
    if ls.returncode != 0: raise Refuse(f'git ls-remote lỗi cho nhánh B0 (mã {ls.returncode}): {ls.stderr.strip()[:200]}')
    head, refs, hist = None, [], []
    for ref, _ in job_refs(ls.stdout, B0_JOB):
        local = 'refs/supp-b0/' + ref[len('refs/heads/'):]
        f = _git(repo, 'fetch', '-q', 'origin', f'+{ref}:{local}')
        if f.returncode != 0: raise Refuse(f'{ref} có trên remote mà tải lỗi: {f.stderr.strip()[:200]}')
        c = _git(repo, 'rev-parse', local).stdout.strip()
        sm = _git(repo, 'show', f'{c}:{B0_DIR}/summary.txt')
        rn = _git(repo, 'show', f'{c}:{B0_DIR}/{B0_RUNS}')
        src = _git(repo, 'show', f'{c}:ci-out/source-commit.txt').stdout.strip()
        if sm.returncode == 0: hist.append((ref, 'summary.txt', sm.stdout))
        if rn.returncode == 0:
            for l in rn.stdout.splitlines():
                try: hist.append((ref, B0_RUNS, (json.loads(l) or {}).get('summary')))
                except (ValueError, AttributeError): hist.append((ref, B0_RUNS, None))
        x = dict(ref=ref, commit=c, summary=sm.stdout if sm.returncode == 0 else None, has_runs=rn.returncode == 0, source=src)
        refs.append(x)
        if ref == f'refs/heads/results/{B0_JOB}': head = x
    return dict(head=head, refs=refs, history=hist)


def b0_c_runs(history):
    """Các lần chạy B0 cho nhánh (c) trong lịch sử (ref, nguồn)."""
    return [(ref, src) for ref, src, s in history if s and b0_branch(s)[0] == 'c']


def b0_decide(head_summary, has_runs, source_ok, history):
    """Mục 7 bước 2 (Le chốt vòng 3, vòng 4): một lần chạy B0 nào đó (summary hay dòng lịch sử ở results/ hay results-failed/) đã cho (c)
    thì dừng, lần chạy sau không thay được; đầu nhánh thiếu lịch sử, không dùng được, hoặc chạy ở commit không phải hậu duệ của commit
    amendment thì `fail`."""
    cs = b0_c_runs(history)
    if cs: return 'c', f'lịch sử B0 có lần chạy nhánh (c) ({cs[0][1]} ở {cs[0][0]})'
    if not has_runs: return 'fail', f'đầu nhánh B0 không có {B0_RUNS} (B0 không tải được lịch sử): chạy lại B0'
    br, why = b0_branch(head_summary)
    if br == 'fail': return br, why
    if not source_ok: return 'fail', 'commit nguồn của B0 nằm trước commit amendment hoặc ở nhánh khác: chạy lại B0 sau bước 1'
    return br, why


def cmd_b0(a, repo):
    am = amendment_check(repo, a.amendment_commit, keys_path=a.keys)
    if not am['ok']: raise Refuse(f'amendment: {am["reason"]}')
    col = b0_collect(repo)
    hd = col['head']
    if hd is None and not b0_c_runs(col['history']): raise Refuse(f'chưa có results/{B0_JOB} (mục 7 bước 2 phải chạy trước bước 3)')
    hd = hd or dict(summary=None, has_runs=False, source='', commit='')
    src = hd['source']
    source_ok = bool(src) and _git(repo, 'merge-base', '--is-ancestor', am['commit'], src).returncode == 0
    br, why = b0_decide(hd['summary'], hd['has_runs'], source_ok, col['history'])
    print(f'{br}: {why} (results/{B0_JOB} {hd["commit"][:12]}, chạy ở {src[:12] or "?"}; {len(col["refs"])} lần nộp B0: '
          f'{[x["ref"][len("refs/heads/"):] for x in col["refs"]]})')
    print(f'B0_COMMIT={hd["commit"]}')
    if br == 'c': raise Stop(f'B0 nhánh (c): {why}')
    if br == 'fail': raise Refuse(f'B0 không dùng được: {why}')


def smoke_accept(so, key, preflight_doc, minfo=None):
    """Job đầy đủ: điều kiện từ kết quả job smoke (mục 7 bước 4, 5). Trả (lớp, lý do, thông tin): 'ok', 'fail', 'stop'.
    Máy (Le chốt 2026-11-06, mục 7): job đầy đủ được chạy trên instance khác job smoke khi cả hai máy có loại máy, AMI của ENV_REQ và cổng
    môi trường của job smoke đạt; instance khác thì lý do và thông tin ghi lại (`different_instance`) để công bố ở notes. Loại máy hay AMI
    lệch ENV_REQ, hoặc không đọc được, là `fail`, cùng lớp với lệch môi trường ở preflight (mục 10)."""
    stop, fail = [], []
    complete = os.path.exists(f'{so}/{COMPLETE}')
    if not complete: fail.append(f'job smoke chưa hoàn tất (không có {COMPLETE})')
    g = jload(f'{so}/gate/smoke-gate.json')
    if g is None: fail.append('không có gate/smoke-gate.json của job smoke')
    elif not g.get('ok'): stop.append('cổng smoke build không đạt')
    recs = records(f'{so}/run/{OUT_NAME}')
    okr = [r for r in recs if r.get('key') == key and r.get('status') != 'harness_error']
    other = [r for r in recs if not (r.get('key') == key and r.get('status') != 'harness_error')]
    if len(okr) > 1: stop.append(f'{len(okr)} bản ghi kết quả của {key} (đã chạy lại sau khi có bản ghi)')
    elif not okr: (stop if complete else fail).append(f'không có bản ghi kết quả của {key}' + (' dù job smoke ghi hoàn tất' if complete else ''))
    if other: stop.append(f'job smoke có {len(other)} bản ghi khác bản ghi chính thức của {key}')
    if len(okr) == 1:                                          # luật 2 (Le chấp nhận): bản ghi smoke chính thức thiếu trường thì dừng
        need = ('outcome', 'reasons', 'reason', 'vectors', 'supp', 's0_outcome')
        miss = [f for f in need if f not in okr[0]]
        if miss: stop.append(f'bản ghi smoke chính thức thiếu trường {miss}')
        elif any(f not in v for v in okr[0]['vectors'] for f in ('san', 'san_attempts', 'san_markers', 'obs')):
            stop.append('vector của bản ghi smoke chính thức thiếu trường')
    m = jload(f'{so}/run/manifest.json')
    mi = minfo if minfo is not None else machine_info_retry()
    iid = mi.get('instance_id')
    iid_s = None
    mach = ('instance_type', 'ami_id')
    if m is None: fail.append('không có run/manifest.json của job smoke')
    else:
        pm = m.get('params') or {}
        env_s = (pm.get('gates') or {}).get('env') or {}
        ms = env_s.get('machine') or {}
        iid_s = ms.get('instance_id') or (m.get('machine') or {}).get('instance_id')
        if not iid_s: fail.append('manifest smoke không có instance id')
        if not env_s.get('ok'): fail.append('manifest smoke không ghi cổng môi trường đạt (mục 7)')
        bad_s = [k for k in mach if ms.get(k) != ENV_REQ[k]]
        if bad_s: fail.append(f'máy của job smoke lệch mục 7 ở {bad_s}: {[ms.get(k) for k in bad_s]}')
        ac_s = ((pm.get('gates') or {}).get('amendment') or {}).get('commit')
        ac = ((preflight_doc or {}).get('amendment') or {}).get('commit')
        if not ac_s or ac_s != ac: stop.append(f'commit amendment khác job smoke ({ac} khác {ac_s})')   # luật 3 (Le chấp nhận)
    if not iid: fail.append(f'không đọc được instance id của máy này sau {mi.get("imds_tries", "?")} lần')
    bad = [k for k in mach if mi.get(k) != ENV_REQ[k]]
    if bad: fail.append(f'máy này lệch mục 7 ở {bad}: {[mi.get(k) for k in bad]}')
    diff = bool(iid and iid_s and iid != iid_s)
    note = (f'máy khác job smoke ({iid} khác {iid_s}), cùng loại {ENV_REQ["instance_type"]} và AMI {ENV_REQ["ami_id"]}: công bố ở notes'
            if diff else None)
    cls = 'stop' if stop else ('fail' if fail else 'ok')
    why = '; '.join(stop + fail) or ('đạt; ' + note if note else 'đạt')
    return cls, why, dict(instance_id=iid, smoke_instance_id=iid_s, different_instance=diff,
                          machine={k: mi.get(k) for k in mach})


def cmd_accept_smoke(a, repo):
    keys = keys_check(repo, a.keys)
    if not keys['ok']: raise Stop(f'keys: {keys["reason"]}')
    cls, why, info = smoke_accept(a.smoke_dir, keys['smoke_key'], jload(a.preflight))
    print(f'điều kiện từ job smoke: {cls}: {why} ({info})')
    if cls == 'stop': raise Stop(why)
    if cls == 'fail': raise Refuse(why)


def build_parser():
    ap = argparse.ArgumentParser(prog='harness.rq2_san_supp')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('check', 'orig', 'build', 'run', 'b0'):
        p = sub.add_parser(name)
        p.add_argument('--keys', default=KEYS); p.add_argument('--amendment-commit')
        if name == 'b0': continue
        p.add_argument('--freeze-tag', default=FREEZE_TAG)
        p.add_argument('--build-root', default=os.environ.get('HARNESS_BUILD') or PIC_ROOT)
        p.add_argument('--orig-root', default=ORIG_ROOT)
        p.add_argument('--b0-result', help='commit kết quả B0 và nhánh (ghi vào manifest)')
        if name != 'check': p.add_argument('--out', required=True)
        if name == 'build': p.add_argument('--workers', type=int, default=BUILD_WORKERS)
        if name == 'run': p.add_argument('--workers', type=int, default=WORKERS)
        if name == 'orig': p.add_argument('--configure-rest', action='store_true', help='configure cờ gốc 35 case còn lại (S-ninja)')
        if name in ('check', 'run'): p.add_argument('--s0', required=name == 'run', help=f'bản ghi S₀ ({S0_SOURCE})')
        if name == 'run':
            g = p.add_mutually_exclusive_group(required=True)
            g.add_argument('--smoke', action='store_true', help='mục 7 bước 4: key đầu tiên của keys.txt')
            g.add_argument('--full', action='store_true', help='mục 7 bước 5: 35 key còn lại')
            p.add_argument('--gate-json', required=True, help='smoke-gate.json đã đạt')
            p.add_argument('--expect-builds', metavar='BUILDS_JSON', help='builds.json của job smoke để đối chiếu marker, driver, .so')
            p.add_argument('--attempt', type=int, help='số lần thử do scan quyết (ghi vào manifest và lịch sử)')
            p.add_argument('--history', help=f'{RUNS} của job: dòng của lần thử này ghi ngay sau run/manifest.json')
    p = sub.add_parser('scan'); p.add_argument('--mode', required=True, choices=sorted(JOBS)); p.add_argument('--out', required=True)
    p.add_argument('--declared-attempt', type=int, default=1, help='SUPP_ATTEMPT của script job (Actions run list ghi ở notes)')
    p = sub.add_parser('accept-smoke'); p.add_argument('--smoke-dir', required=True); p.add_argument('--preflight', required=True)
    p.add_argument('--keys', default=KEYS)
    return ap


def main(argv=None, repo=None):
    a = build_parser().parse_args(argv)
    repo = repo or CF.REPO
    cmds = dict(scan=cmd_scan, check=cmd_check, orig=cmd_orig, build=cmd_build, run=cmd_run, b0=cmd_b0, **{'accept-smoke': cmd_accept_smoke})
    try:
        cmds[a.cmd](a, repo)
    except Stop as e:
        print(f'DỪNG: {e.msg}', file=sys.stderr); raise


if __name__ == '__main__':
    main()
