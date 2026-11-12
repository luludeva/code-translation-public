"""Pipeline số liệu Chương 4 (writing/scripts/gen-rq-macros.py, gen-rq-tables.py): tên macro hợp lệ và không trùng, tử số và mẫu số
nhất quán, ?? khi thiếu nguồn, kiểm chéo split với summary của harness.metrics, chặn số pilot ghi vào writing/generated/.
Fixture: tests/fixtures/rq-macros/ (pilot, R6; sơ bộ, chưa kiểm tay), census lấy từ các file đã commit trong experiments/.
Chạy: python3 -m unittest tests.test_rq_macros"""
import copy, glob, importlib.util, io, json, os, re, shutil, subprocess, tempfile, unittest
from contextlib import redirect_stderr

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
FIX = f'{ROOT}/tests/fixtures/rq-macros'


def _load(name, fn):
    spec = importlib.util.spec_from_file_location(name, f'{ROOT}/writing/scripts/{fn}')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


G = _load('gen_rq_macros', 'gen-rq-macros.py')
TB = _load('gen_rq_tables', 'gen-rq-tables.py')


class Args:
    def __init__(self, indir=None, pilot=True):
        self.indir, self.pilot, self.harness_root, self.prefix = indir, pilot, ROOT, 'rq'


def run(indir=FIX, pilot=True, metrics=None, split=None):
    """(macro dict, cảnh báo, danh sách họ). metrics/split: thay nội dung fixture (đã sửa) để thử trường hợp lỗi."""
    with tempfile.TemporaryDirectory() as d, redirect_stderr(io.StringIO()):
        if metrics is not None or split is not None:
            for n, v in (('metrics.json', metrics), ('metrics-split.json', split)):
                if v is not None:
                    with open(f'{d}/{n}', 'w') as f: json.dump(v, f)
            indir = d
        D, fams, files, hroot = G.prepare(Args(indir, pilot))
        tex, macros = G.render(D, fams, files, hroot, 'rq', pilot)
    return dict(macros), D.warn, fams, tex


def read(p):
    with open(p) as f: return f.read()


def fixture(n):
    return json.loads(read(f'{FIX}/{n}'))


def num(v):
    return None if v in ('??', 'n/a') else float(v)


class Names(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.warn, cls.fams, cls.tex = run()

    def test_valid_unique_and_no_collision_with_other_generated_files(self):
        names = re.findall(r'^\\rqSet\{([^}]*)\}', self.tex, re.M)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(re.fullmatch(r'[A-Za-z]+', n) for n in names))
        other = set()
        for f in glob.glob(f'{ROOT}/writing/generated/*.tex'):
            if os.path.basename(f) == 'rq-numbers.tex': continue
            other |= set(re.findall(r'\\(?:newcommand|providecommand|renewcommand|def)\{?\\([A-Za-z]+)', read(f)))
        self.assertFalse(set(names) & other)

    def test_tok(self):
        self.assertEqual(G.tok('B1-whitespace'), 'BOneWhitespace')
        self.assertEqual(G.tok('incomplete_harness_run:run_unobserved'), 'IncompleteHarnessRunRunUnobserved')
        self.assertEqual(G.tok('stderr+stdout'), 'StderrStdout')
        self.assertEqual(len(set(G.SYS_TOK.values())), len(G.SYSTEMS))

    def test_fixture_consistent(self):
        self.assertEqual(self.warn, [])     # split '_all' khớp metrics.json; |P_rep| census = n_translations; R_run = bản ghi RQ2


class NumDen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m, cls.warn, cls.fams, _ = run()

    def bases(self):
        for n in self.m:
            if n.endswith('Num'): yield n[:-3]

    def test_pct_matches_num_den(self):
        for b in self.bases():
            if b + 'Pct' not in self.m: continue
            n, d, p = self.m[b + 'Num'], self.m[b + 'Den'], self.m[b + 'Pct']
            if '??' in (n, d): self.assertEqual(p, '??', b); continue
            self.assertEqual(p, 'n/a' if float(d) == 0 else f'{100 * float(n) / float(d):.1f}', b)

    def test_rates_are_proportions(self):
        for b in self.bases():
            if b + 'Pct' not in self.m: continue
            n, d = num(self.m[b + 'Num']), num(self.m[b + 'Den'])
            if n is None or d is None: continue
            self.assertTrue(0 <= n <= d, f'{b}: {n}/{d}')

    def test_systems_and_groups_add_up(self):
        m = self.m
        for fam in ('FP', 'Pacc', 'Ptest', 'Lp', 'FF', 'FFDisagree', 'NBHi', 'SRLo', 'SRHi', 'Lr'):
            for kind in ('Exe', 'Lib'):
                for f in ('Num', 'Den'):
                    tot = num(m[f'rq{fam}{kind}All{f}'])
                    self.assertEqual(sum(num(m[f'rq{fam}{kind}All{s}{f}']) for s in G.SYS_TOK.values()), tot, (fam, kind, f))
                    self.assertEqual(sum(num(m[f'rq{fam}{kind}{g}{f}']) for g in ('BOne', 'BTwo', 'PZero', 'POne')), tot, (fam, kind, f))

    def test_values_follow_metrics_and_formulas(self):
        mt, m = fixture('metrics.json'), self.m
        a = mt['rq1_exe']['by_group']['all']
        self.assertEqual((m['rqFPExeAllNum'], m['rqFPExeAllDen']), (str(a['D_all']), str(a['P_test'])))
        self.assertEqual(m['rqFFLibAllNum'], str(mt['rq2_lib']['F'])); self.assertEqual(m['rqFFLibAllDen'], str(mt['rq2_lib']['R_test']))
        for kind in ('Exe', 'Lib'):
            for s in [''] + list(G.SYS_TOK.values()):
                g = lambda f, fld='Num': num(m[f'rq{f}{kind}All{s}{fld}'])
                self.assertEqual(g('Lp'), g('Pacc') - g('Ptest'))
                self.assertEqual(g('SRLo'), g('Pacc') - g('FP') - g('Lp') + g('FF'))
                self.assertEqual(g('SRHi'), g('Pacc') - g('FP') + g('FF') + g('Lr'))
                self.assertEqual(g('SRWidth'), g('Lp') + g('Lr'))
                self.assertEqual(g('Lr'), g('RZeroTest') - g('FFDisagree') - g('FF'))
                self.assertEqual(g('Pacc'), g('Prep') + sum(g(f'PreRep{G.tok(x)}') for x in G.PRE_REP_CAUSES))

    def test_empty_census_group_is_zero_not_missing(self):
        # library không có nhóm P00 trong census: tập rỗng hợp lệ, không phải thiếu nguồn
        self.assertEqual((self.m['rqFPLibPZeroNum'], self.m['rqFPLibPZeroDen'], self.m['rqFPLibPZeroPct']), ('0', '0', 'n/a'))


class Missing(unittest.TestCase):
    def test_no_inputs_renders_qq_but_census_numbers(self):
        m, warn, _, _ = run(indir=None, pilot=False)
        for n in ('rqFPExeAllNum', 'rqFPExeAllDen', 'rqFFLibAllKiroPct', 'rqSRLoExeAllPct', 'rqRobExactLibAllNum'):
            self.assertEqual(m[n], '??', n)
        self.assertRegex(m['rqPzeroExeAllNum'], r'^\d+$'); self.assertRegex(m['rqPaccLibAllKiroNum'], r'^\d+$')

    def test_metrics_without_split(self):
        with tempfile.TemporaryDirectory() as d, redirect_stderr(io.StringIO()):
            shutil.copy(f'{FIX}/metrics.json', d)
            D, fams, files, hroot = G.prepare(Args(d, True))
            m = dict(G.build_macros(D, fams, 'rq'))
        self.assertNotEqual(m['rqFPExeAllNum'], '??')
        self.assertEqual(m['rqFPExeAllKiroNum'], '??')          # theo hệ cần metrics-split.json
        self.assertEqual(m['rqFFLibBOneNum'], '??')            # RQ2 theo nhóm cần split
        self.assertNotEqual(m['rqFFLibAllNum'], '??')

    def test_old_schema_scalar_missing_is_qq(self):
        mt = fixture('metrics.json'); del mt['rq1_exe']['by_group']['all']['SA1']
        m, warn, _, _ = run(metrics=mt, split=fixture('metrics-split.json'))
        self.assertEqual(m['rqRobCCrashExeAllNum'], '??')
        self.assertEqual(m['rqRobCCrashExeAllPct'], '??')

    def test_split_mismatch_drops_per_system(self):
        sp = fixture('metrics-split.json'); sp['rq1']['exe']['all']['_all']['D_all'] += 1
        m, warn, _, _ = run(metrics=fixture('metrics.json'), split=sp)
        self.assertTrue(any('split lệch' in w for w in warn))
        self.assertEqual(m['rqFPExeAllKiroNum'], '??'); self.assertNotEqual(m['rqFPExeAllNum'], '??')
        self.assertNotEqual(m['rqFPLibAllKiroNum'], '??')      # kind khác không bị ảnh hưởng

    def test_pilot_split_requires_pilot_flag(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            G.prepare(Args(FIX, False))

    def test_pilot_never_written_to_generated(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            G.main(['--in', FIX, '--pilot', '--out', f'{ROOT}/writing/generated/rq-numbers.tex'])
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            TB.main(['--in', FIX, '--pilot', '--outdir', f'{ROOT}/writing/generated'])


class Channels(unittest.TestCase):
    def test_combo_and_channel_counts(self):
        mt, sp = fixture('metrics.json'), fixture('metrics-split.json')
        mt['rq2_exe'].update(F=3, A=mt['rq2_exe']['A'] - 3, ff_channels={'stderr+stdout': 2, 'stdout': 1})
        for g in sp['rq2']['exe'].values():
            for v in g.values(): v.update(F=0, ff_channels={})
        sp['rq2']['exe']['all']['_all'] = copy.deepcopy(mt['rq2_exe'])
        m, warn, fams, _ = run(metrics=mt, split=sp)
        self.assertEqual(m['rqFFChanStdoutExeAllNum'], '3'); self.assertEqual(m['rqFFChanStderrExeAllNum'], '2')
        self.assertEqual(m['rqFFComboStderrStdoutExeAllNum'], '2'); self.assertEqual(m['rqFFComboStdoutExeAllDen'], '3')
        self.assertEqual(m['rqFFComboStdoutLibAllNum'], '0')


class Tables(unittest.TestCase):
    def test_tables_only_reference_defined_macros(self):
        with tempfile.TemporaryDirectory() as d, redirect_stderr(io.StringIO()):
            G.main(['--in', FIX, '--pilot', '--out', f'{d}/rq-numbers.tex'])
            out = TB.main(['--in', FIX, '--pilot', '--outdir', d])
            defined = set(re.findall(r'^\\rqSet\{([A-Za-z]+)\}', read(f'{d}/rq-numbers.tex'), re.M))
            self.assertGreaterEqual(len(out), 15)
            for name, tex in out.items():
                used = set(re.findall(r'\\(rq[A-Z][A-Za-z]*)', tex))
                self.assertTrue(used, name); self.assertFalse(used - defined, name)
                self.assertNotIn('\u2014', tex)
                self.assertEqual(tex.count('\\begin{tabular}'), 1); self.assertIn('\\bottomrule', tex)
                # bảng không chứa số đo: ngoài macro, tiêu đề cột chỉ có chữ số của nhãn seed/phân tích
                body = re.sub(r'\\rq[A-Za-z]+|\\cmidrule\([a-z]*\)\{[\d-]+\}|\\multicolumn\{\d+\}|%.*', '', tex)
                self.assertFalse(re.search(r'\d{3,}', body), name)

    @unittest.skipUnless(shutil.which('pdflatex'), 'không có pdflatex')
    def test_compiles(self):
        with tempfile.TemporaryDirectory() as d, redirect_stderr(io.StringIO()):
            G.main(['--in', FIX, '--pilot', '--out', f'{d}/rq-numbers.tex'])
            out = TB.main(['--in', FIX, '--pilot', '--outdir', d])
            doc = ['\\documentclass{article}', '\\usepackage[a4paper,landscape,margin=1cm]{geometry}', '\\usepackage{booktabs}',
                   '\\newcommand{\\code}[1]{\\texttt{#1}}', '\\input{rq-numbers.tex}', '\\input{rq-numbers.tex}', '\\begin{document}']
            doc += [f'\\input{{{n}}}\\par' for n in sorted(out)] + ['\\end{document}']
            with open(f'{d}/t.tex', 'w') as f: f.write('\n'.join(doc))
            p = subprocess.run(['pdflatex', '-interaction=nonstopmode', '-halt-on-error', 't.tex'], cwd=d, capture_output=True, text=True,
                               env=dict(os.environ, TEXMFVAR=d))
            self.assertEqual(p.returncode, 0, p.stdout[-2000:])


class MapDoc(unittest.TestCase):
    def test_every_family_in_map(self):
        doc = read(f'{ROOT}/docs/proposal/rq-macro-map.md')
        with redirect_stderr(io.StringIO()):
            D, fams, _, _ = G.prepare(Args(None, False))
        for kind in G.KINDS:
            for f in fams[kind]:
                if f.name.startswith('FFCombo'): continue        # họ động theo dữ liệu, mô tả chung trong map
                self.assertRegex(doc, re.escape(f'\\rq{f.name}') + '(Exe|Lib)All', f.name)   # cùng họ ở hai kind ghi một dòng


if __name__ == '__main__':
    unittest.main()
