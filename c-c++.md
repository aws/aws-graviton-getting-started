# C/C++ on Graviton

### Enabling Arm Architecture Specific Features
To build code with the optimal processor features use the following. If you want to support both Graviton
and Graviton2 you'll have to limit yourself to the Graviton features.

CPU      | GCC                  | LLVM
---------|----------------------|-------------
Graviton | `-march=armv8-a+crc+crypto` | `-march=armv8-a+crc+crypto`
Graviton2 | `-march=armv8.2-a+fp16+rcpc+dotprod+crypto` |`-march=armv8.2-a+fp16+rcpc+dotprod+crypto`

### Core Specific Tuning

CPU      | GCC < 9              | GCC >=9
---------|----------------------|-------------
Graviton | `-mtune=cortex-a72`  | `-mtune=cortex-a72`
Graviton2 | `-mtune=cortex-a72`  | `-mtune=neoverse-n1`

### Large-System Extensions (LSE)

The Graviton2 processor in C6g, M6g, and R6g instances has support for the
Armv8.2 instruction set.  Armv8.2 specification includes the large-system
extensions (LSE) introduced in Armv8.1. LSE provides low-cost atomic operations.
LSE improves system throughput for CPU-to-CPU communication, locks, and mutexes.
The improvement can be up to an order of magnitude when using LSE instead of
load/store exclusives.

POSIX threads library needs LSE atomic instructions.  LSE is important for
locking and thread synchronization routines.  The dynamic linker on Linux can
detect CPU capabilities and load libc built with LSE.  For example, Ubuntu 20.04
contains the libc6-lse package.  When installed on a Graviton2 system, all
applications will link against this library.  ldd command line utility displays
the path of the linked dynamic libraries.  If libpthreads.so is in atomics
directory, the library uses LSE atomic instructions.  The following systems
distribute a libc compiled with LSE instructions: Ubuntu 20.04.

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

GCC's `-moutline-atomics` flag produces a binary that runs on both Graviton and
Graviton2.  Supporting both platforms with the same binary comes at a small
extra cost: one load and one branch.  To check that an application
has been compiled with `-moutline-atomics`, `nm` command line utility displays
the name of functions and global variables in an application binary.  The boolean
variable that GCC uses to check for LSE hardware capability is
`__aarch64_have_lse_atomics` and it should appear in the list of symbols:
```
$ nm app | grep __aarch64_have_lse_atomics | wc -l
# the output should be 1 if app has been compiled with -moutline-atomics
```

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

### Using Arm instructions to speed-up common code sequences
The Arm instruction set includes instructions that can be used to speedup common
code sequences. The table below lists common operations and links to code sequences:

Operation | Description
----------|------------
[crc](sample-code/crc.c) | Graviton processors support instructions to accelerate both CRC32 which is used by Ethernet, media and compression and CRC32C (Castagnoli) which is used by filesystems.