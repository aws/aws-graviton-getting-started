# Runtime Feature Detection on Graviton

Different generations of Graviton support different features. For example, Graviton3 supports SVE but Graviton2 does
not. Graviton4 supports SVE2 and SVE. For some applications it may be adventageous to implement performance critical
kernels to make use of the highest performing feature set available which may not be known until runtime. For this, the
best practice is to consult HWCAPS. This guide covers the procedure for feature detection on Linux.

On Linux, the standard C library implements `getauxval` to read from the auxiliary vector. Reading the `AT_HWCAP` and
`AT_HWCAP2` values will return the hardware capability bitmaps which are filtered by the kernel to include only features
which the kernel also supports. The library function is defined in `sys/auxv.h` and the constants for masking the bitmap
are defined in `asm/hwcap.h`. Below is a simple C program to print all of the hardware capabilities and print an
asterisk next to features which are supported by your CPU and Kernel combination.

You will need to compile files which contain instructions or intrinsics for specific features with additional compiler
flags. In an assembly file this can be accomplished with an assembler directive in the file. For example to assemble
with support for SVE instructions, include the following:
```
.arch  armv8-2+sve
```
In a C or C++ file, adding a pragama can achieve something similar:
```
#pragma GCC target("+sve")
```

Once runtime detection is complete, use any polymorphism technique you wish to dispatch calls to the appropriate
versions of the functions, such as C++ classes, [ifuncs](https://sourceware.org/glibc/wiki/GNU_IFUNC) or a simpler
C-style function pointer approach.

You may also wish to use a library to provide this functionality.
- https://github.com/pytorch/cpuinfo

Note: In `HWCAP2_LIST`, bits at `HWCAP2_ECV` and higher may not be defined in the header distributed by your compiler.
If you encounter build errors, simply remove those lines.
```c

#include <stdio.h>
#include <sys/auxv.h>
#include <asm/hwcap.h>

#define HWCAP1_LIST(XX)         \
    XX(HWCAP_FP)                \
    XX(HWCAP_ASIMD)             \
    XX(HWCAP_EVTSTRM)           \
    XX(HWCAP_AES)               \
    XX(HWCAP_PMULL)             \
    XX(HWCAP_SHA1)              \
    XX(HWCAP_SHA2)              \
    XX(HWCAP_CRC32)             \
    XX(HWCAP_ATOMICS)           \
    XX(HWCAP_FPHP)              \
    XX(HWCAP_ASIMDHP)           \
    XX(HWCAP_CPUID)             \
    XX(HWCAP_ASIMDRDM)          \
    XX(HWCAP_JSCVT)             \
    XX(HWCAP_FCMA)              \
    XX(HWCAP_LRCPC)             \
    XX(HWCAP_DCPOP)             \
    XX(HWCAP_SHA3)              \
    XX(HWCAP_SM3)               \
    XX(HWCAP_SM4)               \
    XX(HWCAP_ASIMDDP)           \
    XX(HWCAP_SHA512)            \
    XX(HWCAP_SVE)               \
    XX(HWCAP_ASIMDFHM)          \
    XX(HWCAP_DIT)               \
    XX(HWCAP_USCAT)             \
    XX(HWCAP_ILRCPC)            \
    XX(HWCAP_FLAGM)             \
    XX(HWCAP_SSBS)              \
    XX(HWCAP_SB)                \
    XX(HWCAP_PACA)              \
    XX(HWCAP_PACG)

#define HWCAP2_LIST(XX)         \
    XX(HWCAP2_DCPODP)           \
    XX(HWCAP2_SVE2)             \
    XX(HWCAP2_SVEAES)           \
    XX(HWCAP2_SVEPMULL)         \
    XX(HWCAP2_SVEBITPERM)       \
    XX(HWCAP2_SVESHA3)          \
    XX(HWCAP2_SVESM4)           \
    XX(HWCAP2_FLAGM2)           \
    XX(HWCAP2_FRINT)            \
    XX(HWCAP2_SVEI8MM)          \
    XX(HWCAP2_SVEF32MM)         \
    XX(HWCAP2_SVEF64MM)         \
    XX(HWCAP2_SVEBF16)          \
    XX(HWCAP2_I8MM)             \
    XX(HWCAP2_BF16)             \
    XX(HWCAP2_DGH)              \
    XX(HWCAP2_RNG)              \
    XX(HWCAP2_BTI)              \
    XX(HWCAP2_MTE)              \
    XX(HWCAP2_ECV)              \
    XX(HWCAP2_AFP)              \
    XX(HWCAP2_RPRES)            \
    XX(HWCAP2_MTE3)             \
    XX(HWCAP2_SME)              \
    XX(HWCAP2_SME_I16I64)       \
    XX(HWCAP2_SME_F64F64)       \
    XX(HWCAP2_SME_I8I32)        \
    XX(HWCAP2_SME_F16F32)       \
    XX(HWCAP2_SME_B16F32)       \
    XX(HWCAP2_SME_F32F32)       \
    XX(HWCAP2_SME_FA64)         \
    XX(HWCAP2_WFXT)             \
    XX(HWCAP2_EBF16)            \
    XX(HWCAP2_SVE_EBF16)        \
    XX(HWCAP2_CSSC)             \
    XX(HWCAP2_RPRFM)            \
    XX(HWCAP2_SVE2P1)           \
    XX(HWCAP2_SME2)             \
    XX(HWCAP2_SME2P1)           \
    XX(HWCAP2_SME_I16I32)       \
    XX(HWCAP2_SME_BI32I32)      \
    XX(HWCAP2_SME_B16B16)       \
    XX(HWCAP2_SME_F16F16)       \
    XX(HWCAP2_MOPS)             \
    XX(HWCAP2_HBC)              \
    XX(HWCAP2_SVE_B16B16)       \
    XX(HWCAP2_LRCPC3)           \
    XX(HWCAP2_LSE128)

void aarch64_get_cpu_flags()
{
    unsigned long hwcap = getauxval(AT_HWCAP);
    unsigned long hwcap2 = getauxval(AT_HWCAP2);

#define XX(cap)              \
    printf( "%s " #cap "\n", (hwcap & cap) ? "*" : " ");
    HWCAP1_LIST(XX)
#undef XX

#define XX(cap)              \
    printf( "%s " #cap "\n", (hwcap2 & cap) ? "*" : " ");
    HWCAP2_LIST(XX)
#undef XX
}

int main(int argc, char *argv[])
{
    aarch64_get_cpu_flags();
    return 0;
}
```

It is possible to consult system registers directly on the processor to detect support for different capabilities,
however this approach has some problems. For example, checking for SVE support by this method obscures the fact that the
kernel must also be configured for SVE support since the width of SVE registers can be different from NEON and so
context switching code must accommodate the different width. Without this kernel support, a context switch could result
in corruption of the content of SVE registers. Because of this, the processor is configured to trap executions of SVE
instructions by default and this trap must be disabled, a job done by the kernel if it is configured to support SVE.

## See Also
- https://www.kernel.org/doc/html/v5.4/arm64/elf_hwcaps.html
- https://man7.org/linux/man-pages/man3/getauxval.3.html
