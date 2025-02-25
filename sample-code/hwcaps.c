
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

#if !defined(HWCAP2_MTE3)
#define HWCAP2_MTE3 (1UL << 63)
#endif
#if !defined(HWCAP2_SME)
#define HWCAP2_SME (1UL << 63)
#endif
#if !defined(HWCAP2_SME_I16I64)
#define HWCAP2_SME_I16I64 (1UL << 63)
#endif
#if !defined(HWCAP2_SME_F64F64)
#define HWCAP2_SME_F64F64 (1UL << 63)
#endif
#if !defined(HWCAP2_SME_I8I32)
#define HWCAP2_SME_I8I32 (1UL << 63)
#endif
#if !defined(HWCAP2_SME_F16F32)
#define HWCAP2_SME_F16F32 (1UL << 63)
#endif
#if !defined(HWCAP2_SME_B16F32)
#define HWCAP2_SME_B16F32 (1UL << 63)
#endif
#if !defined(HWCAP2_SME_F32F32)
#define HWCAP2_SME_F32F32 (1UL << 63)
#endif
#if !defined(HWCAP2_SME_FA64)
#define HWCAP2_SME_FA64 (1UL << 63)
#endif
#if !defined(HWCAP2_WFXT)
#define HWCAP2_WFXT (1UL << 63)
#endif
#if !defined(HWCAP2_EBF16)
#define HWCAP2_EBF16 (1UL << 63)
#endif
#if !defined(HWCAP2_SVE_EBF16)
#define HWCAP2_SVE_EBF16 (1UL << 63)
#endif
#if !defined(HWCAP2_CSSC)
#define HWCAP2_CSSC (1UL << 63)
#endif
#if !defined(HWCAP2_RPRFM)
#define HWCAP2_RPRFM (1UL << 63)
#endif
#if !defined(HWCAP2_SVE2P1)
#define HWCAP2_SVE2P1 (1UL << 63)
#endif
#if !defined(HWCAP2_SME2)
#define HWCAP2_SME2 (1UL << 63)
#endif
#if !defined(HWCAP2_SME2P1)
#define HWCAP2_SME2P1 (1UL << 63)
#endif
#if !defined(HWCAP2_SME_I16I32)
#define HWCAP2_SME_I16I32 (1UL << 63)
#endif
#if !defined(HWCAP2_SME_BI32I32)
#define HWCAP2_SME_BI32I32 (1UL << 63)
#endif
#if !defined(HWCAP2_SME_B16B16)
#define HWCAP2_SME_B16B16 (1UL << 63)
#endif
#if !defined(HWCAP2_SME_F16F16)
#define HWCAP2_SME_F16F16 (1UL << 63)
#endif
#if !defined(HWCAP2_MOPS)
#define HWCAP2_MOPS (1UL << 63)
#endif
#if !defined(HWCAP2_HBC)
#define HWCAP2_HBC (1UL << 63)
#endif
#if !defined(HWCAP2_SVE_B16B16)
#define HWCAP2_SVE_B16B16 (1UL << 63)
#endif
#if !defined(HWCAP2_LRCPC3)
#define HWCAP2_LRCPC3 (1UL << 63)
#endif
#if !defined(HWCAP2_LSE128)
#define HWCAP2_LSE128 (1UL << 63)
#endif

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

#define XX(cap) \
    printf( "%-20s %s\n", #cap, (hwcap & cap) ? "*" : " " );
    HWCAP1_LIST(XX)
#undef XX

#define XX(cap) \
    printf( "%-20s %s\n", #cap, (hwcap2 & cap) ? "*" : " " );
    HWCAP2_LIST(XX)
#undef XX
}

int main(int argc, char *argv[])
{
    aarch64_get_cpu_flags();
    return 0;
}
