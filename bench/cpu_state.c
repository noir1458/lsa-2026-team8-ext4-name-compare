/* How fast is a byte-by-byte compare on this VM right now? (4차 측정의 상태 확인)
 * Same loop as memcmp() in lib/string.c of Linux 5.4, in user space. On 2026-11-25 the VM
 * turned out to have been about three times slower during rounds 1 to 3. This program was
 * written after that: it prints about 62 ns for 120 equal bytes at today's speed.
 * Prints the best of 20 runs: "len 120: 62.34 ns/call, 0.519 ns/byte". */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

__attribute__((noinline)) static int bytecmp(const void *cs, const void *ct, size_t count)
{
    const unsigned char *a, *b;
    int res = 0;

    for (a = cs, b = ct; 0 < count; ++a, ++b, count--)
        if ((res = *a - *b) != 0)
            break;
    return res;
}

static double now(void)
{
    struct timespec t;

    clock_gettime(CLOCK_MONOTONIC_RAW, &t);
    return t.tv_sec * 1e9 + t.tv_nsec;
}

int main(void)
{
    static unsigned char x[256], y[256];
    const int lens[] = {10, 120};
    volatile int sink = 0;

    memset(x, 'a', sizeof x);
    memset(y, 'a', sizeof y);
    for (int k = 0; k < 2; k++) {
        int n = lens[k];
        double best = 1e30;

        y[n - 1] = 'b';
        for (int r = 0; r < 20; r++) {
            double t = now();

            for (int i = 0; i < 200000; i++)
                sink += bytecmp(x, y, n);
            t = (now() - t) / 200000;
            if (t < best)
                best = t;
        }
        printf("len %d: %.2f ns/call, %.3f ns/byte\n", n, best, best / n);
        y[n - 1] = 'a';
    }
    return 0;
}
