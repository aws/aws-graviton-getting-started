# Taking advantage of Arm Advanced SIMD instructions

## Background

Arm-v8 architecture include Advanced-SIMD instructions (A.k.a neon) helping boost performance for many applications that can take advantage of the wide registers.

A lot of the applications and libraries already taking advantage of Arm's Advanced-SIMD, yet this guide is written for developers writing new code or libraries. We'll guide on various ways to take advantage of these instructions, whether through compiler auto-vectorization or writing intrinsics.

Later we'll explain how to build portable code, that would detect in runtime which instructions are available at the specific cores, so developers can build one binary that support cores with different capabilities. For example, to support one binary that would run on Graviton1, Graviton2, and arbiterary set of Android devices with Arm v8.x support.

## Compiler-driven auto-vectorization

Compilers keep improving to take advantage of the SIMD instructions without developers explicit guidance or specific coding style.

In general, GCC 9 have a good support for auto-vectorization, while GCC 10 has shown impressive improvement over GCC 9 in most cases.

Compiling with *-fopt-info-vec-missed* is good practice to check which loops where not vectorized.

### Example how minor code change improve auto-vectorization

The following example was ran on Graviton2, with Ubuntu 20.04 and gcc 9.3.   Different combinations of server and compiler version may show different results

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

Again, as compiler capabilities improve over time, the need for such technique may no longer be needed. However, as long as target applications being built with gcc9 or older, this continues to be a good practice to follow.


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

While Arm architecture version mandate specific instructions support, certain instructions are optional for a specific version of the architecture.

For example, a cpu core compliant with Arm-v8.4 architecture must support dot-product,  but dot-products are optional in Arm-v8.2 and Arm-v8.3.
Graviton2 is Arm-v8.2 compliant, but supports both CRC and dot-product instructions.

A developer wanting to build an application or library that can detect the supported instructions in runtime, can follow the next example:

```
#include<sys/auxv.h>
......
  uint64_t auxv = getauxval(AT_HWCAP);
  has_crc_feature = hwcaps & HWCAP_CRC32 ? true : false;
  has_lse_feature = hwcaps & HWCAP_ATOMICS ? true : false;
  has_fp16_feature = hwcaps & HWCAP_FPHP ? true : false;
  has_dotprod_feature = hwcaps & HWCAP_ASIMDDP ? true : false;
```
