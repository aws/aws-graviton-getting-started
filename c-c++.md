# C/C++ on Graviton

### Enabling Arm Architecture Specific Features

TLDR: To target all current generation Graviton instances (Graviton2,
Graviton3, and Graviton4), use `-march=armv8.2-a`.

C and C++ code can be built for Graviton with a variety of flags, depending on
the goal. If the goal is to get the best performance for a specific generation,
select a flag from the table column "performance". If the goal is to get a good
compromise of feature availability and performance balanced across generations,
select the flag from the "balanced" column. If you want to target multiple
generations of Graviton, select the "balanced" flag for the oldest generation
planned for deployment, since code built for a newer generation may not run on
an older generation. On arm64 `-mcpu=` acts as both specifying the appropriate
architecture and tuning and it's generally better to use that vs `-march` if
you're building for a specific CPU.


CPU          | Flag (performance)    | Flag (balanced)           | GCC version      | LLVM version
-------------|-----------------------|---------------------------|------------------|---------------
Graviton2    | `-mcpu=neoverse-n1` ¹ | `-march=armv8.2-a`        | GCC-9            | Clang/LLVM 10+
Graviton3(E) | `-mcpu=neoverse-v1`   | `-mcpu=neoverse-512tvb` ² | GCC 11           | Clang/LLVM 14+
Graviton4    | `-mcpu=neoverse-v2`   | `-mcpu=neoverse-512tvb` ² | GCC 13           | Clang/LLVM 16+

¹ Requires GCC-9 or later (or GCC-7 for Amazon Linux 2); otherwise we suggest
using `-mcpu=cortex-a72`

² If your compiler doesn't support `neoverse-512tvb`, please use the Graviton2
tuning.

For some applications, it may be necessary to support a broad range of Arm64
targets while still making use of more advanced features such as LSE (Large
System Extensions) or SVE (Scalable Vector Extension). For this case choose a
more conservative build flag, such as `-march=armv8-a` and make use of runtime
CPU support detection of features such as SVE. You can enable runtime detection
and use of LSE atomics instructions by adding the additional compiler flag,
`-moutline-atomics`.

### Compilers

Newer compilers provide better support and optimizations for Graviton processors.
We have seen 15% better performance on Graviton2 when using gcc-10 instead of Amazon Linux 2 system's compiler gcc-7.
When possible please use the latest compiler version available on your system.
The table shows GCC and LLVM compiler versions available in Linux distributions.
Starred version marks the default system compiler.

Distribution    | GCC                  | Clang/LLVM
----------------|----------------------|-------------
Amazon Linux 2023  | 11*               | 15*
Amazon Linux 2  | 7*, 10               | 7, 11*
Ubuntu 24.04    | 9, 10, 11, 12, 13*, 14 | 14, 15, 16, 17, 18*
Ubuntu 22.04    | 9, 10, 11*, 12       | 11, 12, 13, 14*
Ubuntu 20.04    | 7, 8, 9*, 10         | 6, 7, 8, 9, 10, 11, 12
Ubuntu 18.04    | 4.8, 5, 6, 7*, 8     | 3.9, 4, 5, 6, 7, 8, 9, 10
Debian10        | 7, 8*                | 6, 7, 8
Red Hat EL8     | 8*, 9, 10            | 10
SUSE Linux ES15 | 7*, 9, 10            | 7


### Large-System Extensions (LSE)

All Graviton processors after Graviton1 have support for the Large-System Extensions (LSE)
which was first introduced in vArmv8.1. LSE provides low-cost atomic operations which can
improve system throughput for CPU-to-CPU communication, locks, and mutexes.
The improvement can be up to an order of magnitude when using LSE instead of
load/store exclusives.

POSIX threads library needs LSE atomic instructions.  LSE is important for
locking and thread synchronization routines.  The following systems distribute
a libc compiled with LSE instructions:
- Amazon Linux 2
- Amazon Linux 2023
- Ubuntu 18.04 (needs `apt install libc6-lse`)
- Ubuntu 20.04
- Ubuntu 22.04
- Ubuntu 24.04

The compiler needs to generate LSE instructions for applications that use atomic
operations.  For example, the code of databases like PostgreSQL contain atomic
constructs; c++11 code with std::atomic statements translate into atomic
operations.  GCC's `-march=armv8.2-a` flag enables all instructions supported by
Graviton2, including LSE.  To confirm that LSE instructions are created,
the output of `objdump` command line utility should contain LSE instructions:
```
$ objdump -d app | grep -i 'cas\|casp\|swp\|ldadd\|stadd\|ldclr\|stclr\|ldeor\|steor\|ldset\|stset\|ldsmax\|stsmax\|ldsmin\|stsmin\|ldumax\|stumax\|ldumin\|stumin' | wc -l
```
To check whether the application binary contains load and store exclusives:
```
$ objdump -d app | grep -i 'ldxr\|ldaxr\|stxr\|stlxr' | wc -l
```

GCC's `-moutline-atomics` flag produces a binary that runs on both Graviton1 and later
Gravitons with LSE support.  Supporting both platforms with the same binary comes at a small
extra cost: one load and one branch.  To check that an application
has been compiled with `-moutline-atomics`, `nm` command line utility displays
the name of functions and global variables in an application binary.  The boolean
variable that GCC uses to check for LSE hardware capability is
`__aarch64_have_lse_atomics` and it should appear in the list of symbols:
```
$ nm app | grep __aarch64_have_lse_atomics | wc -l
# the output should be 1 if app has been compiled with -moutline-atomics
```

GCC 10.1+ enables `-moutline-atomics` by default as does the version of GCC 7 used by Amazon Linux 2.

### Porting codes with SSE/AVX intrinsics to NEON

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

### Signed vs. Unsigned char
The C standard doesn't specify the signedness of char. On x86 char is signed by
default while on Arm it is unsigned by default. This can be addressed by using
standard int types that explicitly specify the signedness (e.g. `uint8_t` and `int8_t`)
or compile with `-fsigned-char`.
When using the `getchar` function, instead of the commonly used but incorrect:
 
```
char c;
while((c = getchar()) != EOF) {
    // Do something with the character c
}
// Assume we have reached the end of file here
```

you should use an `int` type and the standard function `feof` and `ferror` to
check for the end of file, as follows:

```
int c;

while ((c = getchar()) != EOF) {
    // Do something with the character c
}
// Once we get EOF, we should check if it is actually an EOF or an error

if (feof(stdin)) {
    // End of file has been reached
} else if (ferror(stdin)) {
    // Handle the error (check errno, etc)
}
```

### Using Arm instructions to speed-up Machine Learning

Graviton2 and later processors been optimized for performance and power efficient machine learning by enabling [Arm dot-product instructions](https://community.arm.com/developer/tools-software/tools/b/tools-software-ides-blog/posts/exploring-the-arm-dot-product-instructions) commonly used for Machine Learning (quantized) inference workloads, and enabling [Half precision floating point - \_float16](https://developer.arm.com/documentation/100067/0612/Other-Compiler-specific-Features/Half-precision-floating-point-intrinsics) to double the number of operations per second, reducing the memory footprint compared to single precision floating point (\_float32), while still enjoying large dynamic range.

### Using SVE

The scalable vector extensions (SVE) require both a new enough tool-chain to
auto-vectorize to SVE (GCC 11+, LLVM 14+) and a 4.15+ kernel that supports SVE.
One notable exception is that Amazon Linux 2 with a 4.14 kernel doesn't support SVE;
please upgrade to a 5.4+ AL2 kernel.  Graviton3 and Graviton4 support SVE, earlier Gravitons does not.

### Using Arm instructions to speed-up common code sequences
The Arm instruction set includes instructions that can be used to speedup common
code sequences. The table below lists common operations and links to code sequences:

Operation | Description
----------|------------
[crc](sample-code/crc.c) | Graviton processors support instructions to accelerate both CRC32 which is used by Ethernet, media and compression and CRC32C (Castagnoli) which is used by filesystems.
