# Taking advantage of Arm Advanced SIMD instructions

## Background

Arm-v8 architecture include Advanced-SIMD instructions (NEON) helping boost performance for many applications that can take advantage of the wide registers.

A lot of the applications and libraries already taking advantage of Arm's Advanced-SIMD, yet this guide is written for developers writing new code or libraries. We'll guide on various ways to take advantage of these instructions, whether through compiler auto-vectorization or writing intrinsics.

Later we'll explain how to build portable code, that would detect at runtime which instructions are available at the specific cores, so developers can build one binary that supports cores with different capabilities. For example, to support one binary that would run on Graviton1, Graviton2, and arbitrary set of Android devices with Arm v8.x support.

## Compiler-driven auto-vectorization

Compilers keep improving to take advantage of the SIMD instructions without developers explicit guidance or specific coding style.

In general, GCC 9 has good support for auto-vectorization, while GCC 10 has shown impressive improvement over GCC 9 in most cases.

Compiling with *-fopt-info-vec-missed* is good practice to check which loops were not vectorized.

### How minor code changes improve auto-vectorization

The following example was run on Graviton2, with Ubuntu 20.04 and gcc 9.3.   Different combinations of server and compiler version may show different results

Starting code looked like:
```
  1 // test.c 
...
  5 float   a[1024*1024];
  6 float   b[1024*1024];
  7 float   c[1024*1024];
.....
 37 for (j=0; j<128;j++) { // outer loop, not expected to be vectorized
 38   for (i=0; i<n ; i+=1){ // inner loop, ideal for vectorization
 39         c[i]=a[i]*b[i]+j;
 40   }
 41 }
```

and compiling:

```
$ gcc test.c -fopt-info-vec-missed -O3
test.c:37:1: missed: couldn't vectorize loop
test.c:39:8: missed: not vectorized: complicated access pattern.
test.c:38:1: missed: couldn't vectorize loop
test.c:39:6: missed: not vectorized: complicated access pattern.
```

Line 37 is the outer loop and that's not expected to be vectorized
but the inner loop is prime candidate for vectorization, yet it was not done in this case

A small change to the code, to guarantee that the inner loop would always be aligned to 128-bit SIMD will be enough for gcc 9 to auto-vectorize it

```
  1 // test.c 
...
  5 float   a[1024*1024];
  6 float   b[1024*1024];
  7 float   c[1024*1024];
...
 19 #if(__aarch64__)
 20 #define ARM_NEON_WIDTH  128
 21 #define VF32    ARM_NEON_WIDTH/32
 22 #else
 23 #define VF32    1
 33 #endif
...
 37 for (j=0; j<128;j++) { // outer loop, not expected to be vectorized
 38   for (i=0; i<( n - n%VF32 ); i+=1){ // forcing inner loop to multiples of 4 iterations
 39         c[i]=a[i]*b[i]+j;
 40   }
 41   // epilog loop
 42   if (n%VF32)
 43         for ( ; i < n; i++) 
 44                 c[i] = a[i] * b[i]+j;
 45 }
```

The code above is forcing the inner loop to iterate multiples of 4 (128-bit SIMD / 32-bit per float). Results:

```
$ gcc test.c -fopt-info-vec-missed -O3
test.c:37:1: missed: couldn't vectorize loop
test.c:37:1: missed: not vectorized: loop nest containing two or more consecutive inner loops cannot be vectorized
```
And the outer loop is still not vectorized as expected, but the inner loop is vectorized (and 3-4X faster). 

Again, as compiler capabilities improve over time, the need for such techniques may no longer be needed. However, as long as target applications being built with gcc9 or older, this continues to be a good practice to follow.


## Using intrinsics

One way to build portable code is to use the intrinsic instructions defined by Arm and implemented by GCC and Clang. 

The instructions are defined in *arm_neon.h*.

A portable code that would detect (at compile-time) an Arm CPU and compiler would look like:

```
#if (defined(__clang__) || (defined(__GCC__)) && (defined(__ARM_NEON__) || defined(__aarch64__))
/* compatible compiler, targeting arm neon */
#include <arm_neon.h>
#include <arm_acle.h>
#endif
```

## Runtime detection of supported SIMD instructions

While Arm architecture version mandates specific instructions support, certain instructions are optional for a specific version of the architecture.

For example, a cpu core compliant with Arm-v8.4 architecture must support dot-product, but dot-products are optional in Arm-v8.2 and Arm-v8.3.
Graviton2 is Arm-v8.2 compliant, but supports both CRC and dot-product instructions.

A developer wanting to build an application or library that can detect the supported instructions in runtime, can follow this example:

```
#include<sys/auxv.h>
......
  uint64_t hwcaps = getauxval(AT_HWCAP);
  has_crc_feature = hwcaps & HWCAP_CRC32 ? true : false;
  has_lse_feature = hwcaps & HWCAP_ATOMICS ? true : false;
  has_fp16_feature = hwcaps & HWCAP_FPHP ? true : false;
  has_dotprod_feature = hwcaps & HWCAP_ASIMDDP ? true : false;
```

## Porting codes with SSE/AVX intrinsics to NEON

### Detecting arm64 systems

Projects may fail to build on arm64 with `error: unrecognized command-line
option '-msse2'`, or `-mavx`, `-mssse3`, etc.  These compiler flags enable x86
vector instructions.  The presence of this error means that the build system may
be missing the detection of the target system, and continues to use the x86
target features compiler flags when compiling for arm64.

To detect an arm64 system, the build system can use:
```
# (test $(uname -m) = "aarch64" && echo "arm64 system") || echo "other system"
```

Another way to detect an arm64 system is to compile, run, and check the return
value of a C program:
```
# cat << EOF > check-arm64.c
int main () {
#ifdef __aarch64__
  return 0;
#else
  return 1;
#endif
}
EOF

# gcc check-arm64.c -o check-arm64
# (./check-arm64 && echo "arm64 system") || echo "other system"
```

### Translating x86 intrinsics to NEON

When programs contain code with x64 intrinsics, the following procedure can help
to quickly obtain a working program on Arm, assess the performance of the
program running on Graviton processors, profile hot paths, and improve the
quality of code on the hot paths.

To quickly get a prototype running on Arm, one can use
https://github.com/DLTcollab/sse2neon a translator of x64 intrinsics to NEON.
sse2neon provides a quick starting point in porting performance critical codes
to Arm.  It shortens the time needed to get an Arm working program that then
can be used to extract profiles and to identify hot paths in the code.  A header
file `sse2neon.h` contains several of the functions provided by standard x64
include files like `xmmintrin.h`, only implemented with NEON instructions to
produce the exact semantics of the x64 intrinsic.  Once a profile is
established, the hot paths can be rewritten directly with NEON intrinsics to
avoid the overhead of the generic sse2neon translation.

## Additional resources

 * [Neon Intrinsics](https://developer.arm.com/architectures/instruction-sets/intrinsics/)
 * [Coding for Neon](https://developer.arm.com/documentation/102159/latest/)
 * [Neon Programmer's Guide for Armv8-A](https://developer.arm.com/architectures/instruction-sets/simd-isas/neon/neon-programmers-guide-for-armv8-a)
