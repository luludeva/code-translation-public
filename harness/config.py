"""Đường dẫn, commit đã pin và hằng dùng chung. Tham số thuộc Protocol Freeze (timeout, budget) đọc từ CLI, không cứng ở đây."""
import os

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CORPUS = os.environ.get('CORPUS', os.path.expanduser('~/corpus'))
T = f'{CORPUS}/tractor/Public-Tests'
H = f'{CORPUS}/harvest/Test-Corpus'
TRACTOR_COMMIT = '37960ee08a7c644ee66e29855eca33903f702e67'
HARVEST_COMMIT = '38352c21068c8ebcf58457ee246cd97feefeea86'
SYSTEMS = ['kiro', 'claude', 'codex-gpt54', 'c2rust', 'laertes', 'c2saferrust', 'smartc2rust', 'gpt-5.4', 'kimi',
           'gemini-3.1-pro-preview']
PILOT_EXE = {('B02_organic', 'qmath'), ('B02_synthetic', 'tu_linkage'), ('B02_synthetic', 'static_vars_fpts')}
PILOT_LIB = {('B01_synthetic', '001_helloworld_lib'), ('B01_synthetic', '029_strcspn_lib'), ('B01_organic', 'gaussian_kernel_lib'),
             ('B02_organic', 'aabb_lib'), ('B02_organic', 'encode_base64_lib'), ('B02_synthetic', 'memchra2_lib'),
             ('P01_sphincs_plus', '053_blake_128f_s_initialize_hash_function_lib'),
             ('P01_sphincs_plus', '054_blake_128f_s_prf_addr_lib'),
             ('P01_sphincs_plus', '055_blake_128f_s_gen_message_random_lib'), ('P01_sphincs_plus', '056_blake_128f_s_hash_message_lib')}
NO_INPUT_LIB = {'001_helloworld_lib', '013_poor_quality_addition_lib', '014_dead_code_lib', 'parse_uname_lib'}
# Cờ C-san như build_pairs.sh (exp 04) và spike_lib.py (exp 05)
SAN_FLAGS_EXE = ['-DCMAKE_C_FLAGS=-fsanitize=address,undefined -fno-sanitize-recover=undefined -g',
                 '-DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined']
SAN_FLAGS_LIB = ['-DCMAKE_C_FLAGS=-fsanitize=address,undefined -fno-sanitize-recover=undefined -g -fPIC -shared-libsan',
                 '-DCMAKE_SHARED_LINKER_FLAGS=-fsanitize=address,undefined -shared-libsan']
SAN_MARKERS = (b'runtime error:', b'AddressSanitizer', b'UndefinedBehaviorSanitizer', b'LeakSanitizer')
# Bản vá v2 (2026-10-23): như bản exp 05, thêm trường state_debug để phân biệt NaN, inf, -inf (serde_json ghi cả ba thành null).
# Bản v1 giữ nguyên ở experiments/05-library-spike/scripts/ cho kết quả exp 05.
STATE_DUMP_PATCH = f'{REPO}/harness/patches/cando2-state-dump-v2.patch'
TIMEOUT_RERUN_FACTOR = 10     # A3.3 mục 1.2: một phía timeout thì chạy lại hai phía với timeout gấp 10

# Case executable không đọc input chỉ chạy ở seed này (Le chọn 25/10; harness/rq1.py, harness/metrics.py).
INSENSITIVE_SEED = 0
