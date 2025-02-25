
#include <stdio.h>
#include <sys/auxv.h>
#include <asm/hwcap.h>
#include <arm_sve.h>

#define sizeof_array(a) (sizeof(a) / sizeof((a)[0]))

uint64_t sum_all(uint32_t *values, int length)
{
    uint64_t sum = 0;
    for (int i = 0; i < length; i++)
        sum += values[i];
    return sum;
}

#pragma GCC target("+sve2")
#pragma clang attribute push(__attribute__((target("sve2"))), apply_to = function)
uint64_t sum_all_sve2(uint32_t *values, int length)
{
    svuint64_t sum = svdup_u64(0);
    int i = 0;
    svbool_t predicate = svwhilelt_b32(i, length);
    do {
        svuint32_t a = svld1(predicate, (uint32_t *) &values[i]);
        sum = svadalp_u64_x(predicate, sum, a);
        i += svcntw();
        predicate = svwhilelt_b32(i, length);
    } while (svptest_any(svptrue_b32(), predicate));
    return svaddv_u64(svptrue_b64(), sum);
}
#pragma clang attribute pop

void test() {
    uint32_t values[13] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13};

    int have_sve = !!(getauxval(AT_HWCAP2) & HWCAP2_SVE2);
    uint64_t sum = 0;
    if (have_sve) {
        sum = sum_all_sve(&values[0], sizeof_array(values));
    } else {
        sum = sum_all(&values[0], sizeof_array(values));
    }

    printf("sum: %lu, computed %s SVE2\n", sum, (have_sve) ? "with" : "without");
}

int main(int argc, char *argv[])
{
    test();
    return 0;
}
