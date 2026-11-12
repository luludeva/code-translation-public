"""Bản ghi JSONL có khoá resume, manifest, lưu output lớn (harness-design.md mục 6; G2: lưu đủ stdout, stderr)."""
import base64, gzip, hashlib, json, os, platform, shutil, subprocess, time, urllib.request

from . import VERSION
from .config import HARVEST_COMMIT, REPO, STATE_DUMP_PATCH, TRACTOR_COMMIT


class Store:
    """JSONL append-only; khoá resume là trường `key` của mỗi bản ghi. Ghi xong từng dòng mới flush."""

    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.done = set()
        if os.path.exists(path):
            for l in open(path):
                l = l.strip()
                if not l: continue
                try: self.done.add(json.loads(l)['key'])
                except Exception: pass        # dòng cuối dở dang khi job bị dừng: bỏ, ghi lại
        self.f = open(path, 'a')

    def has(self, key): return key in self.done

    def put(self, rec):
        self.f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + '\n'); self.f.flush()
        self.done.add(rec['key'])


# F8, A8 (a) (Le chọn 25/10, exp 22): trần blob bằng trần output (observe.OUTPUT_CAP, 32 MiB), nên output dưới trần lưu đủ. Trước đây 1 MiB.
BLOB_LIMIT = 32 << 20


def blob(b, limit=BLOB_LIMIT):
    """bytes -> dict lưu được trong JSON: gzip + base64, kèm sha256 và độ dài; cắt ở limit byte (ghi cờ truncated)."""
    if b is None: return None
    if isinstance(b, str): b = b.encode('utf-8', 'replace')
    return dict(sha256=hashlib.sha256(b).hexdigest(), len=len(b), truncated=len(b) > limit,
                gz64=base64.b64encode(gzip.compress(b[:limit], mtime=0)).decode())


def obs_exe(o, keep_output=True):
    d = {k: o.get(k) for k in ('status', 'rc', 'sig', 'secs')}
    d['out_sha256'] = hashlib.sha256(o['out']).hexdigest()
    if keep_output: d.update(out=blob(o['out']), err=blob(o['err']))
    return d


def write_inputs(path, rows):
    """Tập input của một (case, seed), gzip JSONL (mtime 0, tất định). Trả về đường dẫn, số dòng, sha256 của nội dung chưa nén (F8)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    h, n = hashlib.sha256(), 0
    with open(path, 'wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as f:   # không ghi tên file: byte tất định
        for r in rows:
            line = json.dumps(r, ensure_ascii=False, sort_keys=True).encode() + b'\n'
            f.write(line); h.update(line); n += 1
    return dict(path=path, n=n, sha256=h.hexdigest(), gz_bytes=os.path.getsize(path))


def compress_files(paths):
    """Nén từng file (nếu có) thành <file>.gz rồi xoá bản thô (F8: ổ máy đo không chứa đủ bản ghi divergence thô của lượt chính)."""
    for p in paths:
        if not os.path.exists(p): continue
        with open(p, 'rb') as src, open(p + '.gz', 'wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as dst:
            shutil.copyfileobj(src, dst)
        os.remove(p)


def open_text(p):
    """Đọc file .jsonl hoặc .jsonl.gz như văn bản."""
    return gzip.open(p, 'rt', encoding='utf-8') if p.endswith('.gz') else open(p, encoding='utf-8')


def machine_info():
    """Loại máy (F8): metadata EC2 (IMDSv2, chờ tối đa 1 giây mỗi lần gọi), CPU và RAM. Ngoài EC2: source 'none'."""
    m = dict(source='none')
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # metadata chỉ truy cập trực tiếp, không qua proxy
    try:
        tok = op.open(urllib.request.Request('http://169.254.169.254/latest/api/token', method='PUT',
                                     headers={'X-aws-ec2-metadata-token-ttl-seconds': '60'}), timeout=1).read().decode()
        get = lambda k: op.open(urllib.request.Request(f'http://169.254.169.254/latest/meta-data/{k}',
                                               headers={'X-aws-ec2-metadata-token': tok}), timeout=1).read().decode()
        m = dict(source='ec2-imds', instance_type=get('instance-type'), instance_id=get('instance-id'),
                 availability_zone=get('placement/availability-zone'), ami_id=get('ami-id'))
    except Exception as e:
        m['error'] = type(e).__name__
    try:
        info = open('/proc/cpuinfo').read()
        m['cpu_model'] = next((l.split(':', 1)[1].strip() for l in info.splitlines() if l.startswith('model name')), None)
        m['mem_total_kb'] = int(next(l.split()[1] for l in open('/proc/meminfo') if l.startswith('MemTotal')))
    except Exception: pass
    return m


def _sha_file(p):
    try: return hashlib.sha256(open(p, 'rb').read()).hexdigest()
    except OSError: return None


def tool(cmd):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip().splitlines()[0]
    except Exception as e: return f'n/a ({e})'


def manifest(out_dir, params):
    dirty = subprocess.run(['git', '-C', REPO, 'status', '--porcelain', '--untracked-files=no'], capture_output=True, text=True).stdout
    m = dict(harness_version=VERSION, created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
             repo_commit=tool(['git', '-C', REPO, 'rev-parse', 'HEAD']), repo_dirty=bool(dirty.strip()), tractor_commit=TRACTOR_COMMIT,
             harvest_commit=HARVEST_COMMIT, host=platform.node(), uname=' '.join(platform.uname()), nproc=os.cpu_count(),
             machine=machine_info(), python=platform.python_version(),
             rustc=tool(['rustc', '--version']), clang=tool(['clang', '--version']), gcc=tool(['gcc', '--version']),
             afl=tool(['sh', '-c', 'afl-fuzz -h 2>&1 | grep -m1 -o "afl-fuzz++[0-9.a-z]*"']),
             cando2=dict(source='tractor/tools/cando2 tại tractor_commit', state_dump_patch_sha256=_sha_file(STATE_DUMP_PATCH)),
             rustup_toolchain=os.environ.get('RUSTUP_TOOLCHAIN'), blob_limit=BLOB_LIMIT, params=params)
    os.makedirs(out_dir, exist_ok=True)
    json.dump(m, open(f'{out_dir}/manifest.json', 'w'), indent=1, ensure_ascii=False)
    return m
