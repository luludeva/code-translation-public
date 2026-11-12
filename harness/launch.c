/* Bộ khởi chạy cho mọi tiến trình đo của harness (decision-log 2026-10-23, "Bộ khởi chạy C thay preexec_fn").
 * Đặt giới hạn tài nguyên rồi exec chương trình đo với argv[0] cho trước. Thay preexec_fn của Python: preexec_fn buộc subprocess fork
 * cả tiến trình worker (không dùng được vfork), làm mỗi lần khởi chạy chậm khoảng 10 lần (đo 23/10: 13 ms so với 1,4 ms).
 * Dùng: launch <as_bytes> <fsize_bytes> <binary> <argv0> [args...]   (0 = không đặt giới hạn đó)
 * RLIMIT_CORE luôn đặt 1 byte (0 nếu giới hạn cứng là 0): kernel bỏ qua core khi core_pattern là pipe và giới hạn bằng 1; khi
 * core_pattern là file thì 1 byte nhỏ hơn một trang nên không ghi. */
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/resource.h>

static void lim(int res, unsigned long long v) {
    struct rlimit r; r.rlim_cur = r.rlim_max = (rlim_t)v;
    if (setrlimit(res, &r) != 0) { perror("harness-launch setrlimit"); _exit(126); }
}

int main(int argc, char **argv) {
    if (argc < 5) { fprintf(stderr, "harness-launch: thiếu tham số\n"); return 126; }
    unsigned long long as = strtoull(argv[1], 0, 10), fs = strtoull(argv[2], 0, 10);
    if (as) lim(RLIMIT_AS, as);
    if (fs) lim(RLIMIT_FSIZE, fs);
    struct rlimit c; getrlimit(RLIMIT_CORE, &c);
    lim(RLIMIT_CORE, c.rlim_max == 0 ? 0 : 1);
    execv(argv[3], argv + 4);
    perror("harness-launch exec");
    return 127;
}
