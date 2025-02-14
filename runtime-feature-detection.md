# Runtime Feature Detection on Graviton

Different generations of Graviton support different features. For example, Graviton3 supports SVE but Graviton2 does
not. Graviton4 supports SVE2 and SVE. For some applications it may be advantageous to implement performance critical
kernels to make use of the highest performing feature set available which may not be known until runtime. For this, the
best practice is to consult HWCAPS. This guide covers the procedure for feature detection on Linux.

There are several existing libraries which can provide this runtime detection, one such example is [PyTorch's
cpuinfo](https://github.com/pytorch/cpuinfo). If you do not wish to use a library, continue reading to learn how to
implement this functionality yourself.

On Linux, the standard C library implements `getauxval` to read from the auxiliary vector. Reading the `AT_HWCAP` and
`AT_HWCAP2` values will return the hardware capability bitmaps which are filtered by the kernel to include only features
which the kernel also supports. The library function is defined in `sys/auxv.h` and the constants for masking the bitmap
are defined in `asm/hwcap.h`. Below is a [sample C program](sample-code/hwcaps-test.c) which implements two versions of
`sum_all` with and without SVE2. The program then tests for support for SVE2 and then uses that function only when the
runtime system is detected to support it. This program can be compiled on any generation of Graviton and then executed
on any generation of Graviton and select the correct function at runtime. Indeed, when testing the code for this
article, the author compiled the program on Ubuntu 24.04 with GCC 13.3 on Graviton1 and then subsequently tested on all
generations, including Graviton4, which supports SVE2.

```c
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
        sum = sum_all_sve2(&values[0], sizeof_array(values));
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
```

As shown, you will need to compile files which contain instructions or intrinsics for specific features with additional
compiler flags. This can be done by placing these functions in separate files and using your build infrastructure to add
additonal flags for those files, or it is also possible to embed these compiler directives directly on the functions to
which they apply. In an assembly file this can be accomplished with an assembler directive in the file. For example to
assemble with support for SVE instructions, include the following:
```
.arch  armv8-2+sve
```
In a C or C++ file, adding a pragama can achieve something similar:
```
#pragma GCC target("+sve")
#pragma clang attribute push(__attribute__((target("sve2"))), apply_to = function)
...
#pragma clang attribute pop
```

Once runtime detection is complete, use any polymorphism technique you wish to dispatch calls to the appropriate
versions of the functions, such as C++ classes, [ifuncs](https://sourceware.org/glibc/wiki/GNU_IFUNC), function
pointers, or a simpler control flow approach as shown above.

It is possible to consult system registers directly on the processor to detect support for different capabilities,
however this approach has some problems. For example, checking for SVE support by this method obscures the fact that the
kernel must also be configured for SVE support since the width of SVE registers can be different from NEON and so
context switching code must accommodate the different width. Without this kernel support, a context switch could result
in corruption of the content of SVE registers. Because of this, the processor is configured to trap executions of SVE
instructions by default and this trap must be disabled, a job done by the kernel if it is configured to support SVE.

## HWCAP by Generation

[A simple program](sample-code/hwcaps.c) can check and display the all capability bits on a system. This table shows the
results of the linked program executed on recent Linux Kernel. For more information on the meaning of each capability,
consult the [Arm Architectural Reference Manual](https://developer.arm.com/documentation/ddi0487/latest/). Most of the
features can be found by searching in the PDF for `FEAT_` + the symbol which follows `HWCAP_` in the table below.


| CAP                | Graviton1 | Graviton2 | Graviton3 | Graviton4 | 
|--------------------|-----------|-----------|-----------|-----------| 
| HWCAP_FP           | *         | *         | *         | *         | 
| HWCAP_ASIMD        | *         | *         | *         | *         | 
| HWCAP_EVTSTRM      | *         | *         | *         | *         | 
| HWCAP_AES          | *         | *         | *         | *         | 
| HWCAP_PMULL        | *         | *         | *         | *         | 
| HWCAP_SHA1         | *         | *         | *         | *         | 
| HWCAP_SHA2         | *         | *         | *         | *         | 
| HWCAP_CRC32        | *         | *         | *         | *         | 
| HWCAP_ATOMICS      |           | *         | *         | *         | 
| HWCAP_FPHP         |           | *         | *         | *         | 
| HWCAP_ASIMDHP      |           | *         | *         | *         | 
| HWCAP_CPUID        | *         | *         | *         | *         | 
| HWCAP_ASIMDRDM     |           | *         | *         | *         | 
| HWCAP_JSCVT        |           |           | *         | *         | 
| HWCAP_FCMA         |           |           | *         | *         | 
| HWCAP_LRCPC        |           | *         | *         | *         | 
| HWCAP_DCPOP        |           | *         | *         | *         | 
| HWCAP_SHA3         |           |           | *         | *         | 
| HWCAP_SM3          |           |           | *         |           | 
| HWCAP_SM4          |           |           | *         |           | 
| HWCAP_ASIMDDP      |           | *         | *         | *         | 
| HWCAP_SHA512       |           |           | *         | *         | 
| HWCAP_SVE          |           |           | *         | *         | 
| HWCAP_ASIMDFHM     |           |           | *         | *         | 
| HWCAP_DIT          |           |           | *         | *         | 
| HWCAP_USCAT        |           |           | *         | *         | 
| HWCAP_ILRCPC       |           |           | *         | *         | 
| HWCAP_FLAGM        |           |           | *         | *         | 
| HWCAP_SSBS         |           | *         | *         | *         | 
| HWCAP_SB           |           |           |           | *         | 
| HWCAP_PACA         |           |           | *         | *         | 
| HWCAP_PACG         |           |           | *         | *         | 
| HWCAP2_DCPODP      |           |           | *         | *         | 
| HWCAP2_SVE2        |           |           |           | *         | 
| HWCAP2_SVEAES      |           |           |           | *         | 
| HWCAP2_SVEPMULL    |           |           |           | *         | 
| HWCAP2_SVEBITPERM  |           |           |           | *         | 
| HWCAP2_SVESHA3     |           |           |           | *         | 
| HWCAP2_SVESM4      |           |           |           |           | 
| HWCAP2_FLAGM2      |           |           |           | *         | 
| HWCAP2_FRINT       |           |           |           | *         | 
| HWCAP2_SVEI8MM     |           |           | *         | *         | 
| HWCAP2_SVEF32MM    |           |           |           |           | 
| HWCAP2_SVEF64MM    |           |           |           |           | 
| HWCAP2_SVEBF16     |           |           | *         | *         | 
| HWCAP2_I8MM        |           |           | *         | *         | 
| HWCAP2_BF16        |           |           | *         | *         | 
| HWCAP2_DGH         |           |           | *         | *         | 
| HWCAP2_RNG         |           |           | *         | *         | 
| HWCAP2_BTI         |           |           |           | *         | 
| HWCAP2_MTE         |           |           |           |           | 
| HWCAP2_ECV         |           |           |           |           | 
| HWCAP2_AFP         |           |           |           |           | 
| HWCAP2_RPRES       |           |           |           |           | 
| HWCAP2_MTE3        |           |           |           |           | 
| HWCAP2_SME         |           |           |           |           | 
| HWCAP2_SME_I16I64  |           |           |           |           | 
| HWCAP2_SME_F64F64  |           |           |           |           | 
| HWCAP2_SME_I8I32   |           |           |           |           | 
| HWCAP2_SME_F16F32  |           |           |           |           | 
| HWCAP2_SME_B16F32  |           |           |           |           | 
| HWCAP2_SME_F32F32  |           |           |           |           | 
| HWCAP2_SME_FA64    |           |           |           |           | 
| HWCAP2_WFXT        |           |           |           |           | 
| HWCAP2_EBF16       |           |           |           |           | 
| HWCAP2_SVE_EBF16   |           |           |           |           | 
| HWCAP2_CSSC        |           |           |           |           | 
| HWCAP2_RPRFM       |           |           |           |           | 
| HWCAP2_SVE2P1      |           |           |           |           | 
| HWCAP2_SME2        |           |           |           |           | 
| HWCAP2_SME2P1      |           |           |           |           | 
| HWCAP2_SME_I16I32  |           |           |           |           | 
| HWCAP2_SME_BI32I32 |           |           |           |           | 
| HWCAP2_SME_B16B16  |           |           |           |           | 
| HWCAP2_SME_F16F16  |           |           |           |           | 
| HWCAP2_MOPS        |           |           |           |           | 
| HWCAP2_HBC         |           |           |           |           | 
| HWCAP2_SVE_B16B16  |           |           |           |           | 
| HWCAP2_LRCPC3      |           |           |           |           | 
| HWCAP2_LSE128      |           |           |           |           | 

## See Also
- https://www.kernel.org/doc/html/v5.4/arm64/elf_hwcaps.html
- https://man7.org/linux/man-pages/man3/getauxval.3.html
