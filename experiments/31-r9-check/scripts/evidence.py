#!/usr/bin/env python3
"""Sinh phiếu bằng chứng cơ học cho R9/R18 từ results/items.jsonl (README.md, mục "Phiếu bằng chứng"). Không đưa nhãn của script (mã luật,
kênh khác biệt `channels`, cờ retained) vào phiếu. Mỗi luồng output giải nén, hiển thị tối đa LIMIT ký tự, ghi tổng số byte và cờ cắt.
Dùng: python3 experiments/31-r9-check/scripts/evidence.py experiments/31-r9-check/results/items.jsonl OUT.md"""
import base64, gzip, json, sys

LIMIT = 1500
HIDE = {'channels', 'retained', 'san', 'san_attempts', 'san_markers', 'c_ub', 'c_flag', 'key', 'kind', 'bundle', 'case', 'system', 'idx'}


def unblob(b):
    if not isinstance(b, dict) or 'gz64' not in b: return None
    raw = gzip.decompress(base64.b64decode(b['gz64'])).decode('latin-1')
    shown = raw if len(raw) <= LIMIT else raw[:LIMIT] + f'\n…[hiển thị {LIMIT}/{len(raw)} ký tự]'
    return dict(text=shown, bytes=b.get('len'), truncated_by_harness=b.get('truncated'))


def render(v):
    if isinstance(v, dict) and 'gz64' in v: return unblob(v)
    if isinstance(v, dict): return {k: render(x) for k, x in v.items()}
    if isinstance(v, list): return [render(x) for x in v]
    if isinstance(v, str) and len(v) > LIMIT: return v[:LIMIT] + f'…[hiển thị {LIMIT}/{len(v)} ký tự]'
    return v


def main(src, out):
    with open(out, 'w', encoding='utf-8') as f:
        f.write('# Phiếu bằng chứng R9/R18\n\nMỗi mục: một divergence (cùng input, hai phía C và Rust). Trường `c_*`/`c` là phía C, `r_*`/`r` là '
                'phía Rust. Mục đã lọc: sanitizer phía C không báo UB, khác biệt ổn định qua lần chạy lại.\n')
        for l in open(src, encoding='utf-8'):
            it = json.loads(l); d = it['div']
            ev = {k: render(v) for k, v in sorted(d.items()) if k not in HIDE}
            f.write(f'\n## {it["id"]} ({it["kind"]})\n\n```json\n{json.dumps(ev, ensure_ascii=False, indent=1)}\n```\n')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
