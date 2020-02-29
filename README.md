# Getting started with AWS Graviton

This document is meant to help new users start using the Arm-based AWS Graviton and Graviton2 processors
which power the 6th generation of Amazon EC2 instances (e.g. C6g/M6g/R6g). While it calls out specific
features of the Graviton processors this guide is also generically useful for anyone running code on Arm.

# Building for Graviton Processors

The Graviton CPU supports Arm V8.0 and includes support for CRC and crypto extensions.

The Graviton2 CPU uses the Neoverse-N1 core and supports Arm V8.2 plus several
other architectural extensions. In particular, Graviton2 supports the Large
Scale Extensions (LSE) which improve locking and synchronization performance
across large systems. In addition, it has support for fp16 and 8-bit dot
productions for machine learning, and relaxed consistency-processor consistent
(RCpc) memory ordering.

## C/C++

### Enabling Arm Architecture Specific Features
To build code with the optimal processor features use the following. If you want to support both Graviton
and Graviton2 you'll have to limit yourself to the Graviton features.

CPU      | GCC                  | LLVM
---------|----------------------|-------------
Graviton | `-march=armv8-a+crc+crypto` | `-march=armv8-a+crc+crypto`
Graviton2 | `-march=armv8.2-a+fp16+rcpc+dotprod` |`-march=armv8.2-a+fp16+rcpc+dotprod`

### Core Specific Tuning

CPU      | GCC < 9              | GCC >=9
---------|----------------------|-------------
Graviton | `-mtune=cortex-a72`  | `-mtune=cortex-a72`
Graviton2 | `-mtune=cortex-a72`  | `-mtune=neoverse-n1`

### Large Scale Extensions (LSE)
Graviton2 (C6g/M6g/R6g) supports Armv8.2 including the large-synchronization
extensions (LSE) which provide lower-cost, and fairer atomic operations. For
workloads that contain lots of sharing and synchronization (e.g. Databases)
please compile with `-march=armv8.2-a` as this will enable the use of these
operations. However, the code optimized for armv8.2 will not run on Gravtion
(e.g. EC2 A1 instances), it needs its own binary.

There's an option in GCC 10 called `-moutline-atomics` which allows building
a single binary with out-of-line atomics that detect if LSE is supported and
chose the correct locking primitives. This has a small performance degredation but
does allow code to support CPUs with and without LSE atomics in a single binary.

On benchmarks stressing locks the performance can improve by up to an order of magnitude.


# Common packages with recent performance improvements

There is a huge amount of activity in the Arm software ecosystem and improvements are being
made on a daily basis. As a general rule later versions of compilers and language runtimes
should be used whenever possible. The table below includes known recent changes to popular
packages that improve performance (if you know of others please let us know).

Package | Version | Improvements
--------|---------|-------------
PHP     | 7.4+    | PHP 7.4 includes a number of performance improvements that increase perf by up to 30%
Python3 |         | Python3 packages in Ubuntu, Amazon Linux 2 and RHEL were not compiled with link time optimizations (LTO). We have seen up to 30% better performance with LTO.
PCRE2   | 10.34+  | Added NEON vectorization to PCRE's JIT to match first and pairs of characters. This may improve performance of matching by up to 8x.
ffmpeg  |         | Improved performance of libswscale by 50% with better NEON vectorization which improves the performance and scalability of ffmpeg multi-thread encoders.


# Debugging Problems

It's possible that incorrect code will work fine on an existing system, but
produce an incorrect result on a Graviton based server. This could be because
it relies on undefined behavior in the language (e.g. assuming char is signed in C/C++,
or the behavior of signed integer overflow), contains memory management bugs that
happen to be exposed by aggressive compiler optimizations, or incorrect ordering.

## Sanitizers
The compiler may generate code and layout data slightly differently on Graviton
compared to an x86 system and this could expose memory bugs that were previously
hidden. On GCC, the easiest way to look for these bugs is to compile with the
memory sanitizers by adding the below to standard compiler flags:

```
    CFLAGS += -fsanitize=address -fsanitize=undefined
    LDFLAGS += -fsanitize=address  -fsanitize=undefined
```

Then run the resulting binary, any bugs detected by the sanitizers will cause
the program to exit immediately and print helpful stack traces and other
information.

## Ordering issues
Arm is weakly ordered, while x86 is a variant of total-store-ordering (TSO).
Code that relies on TSO may lack barriers to properly order memory references.
Armv8 based systems, including Graviton and Graviton2 are [weakly ordered
multi-copy-atomic](https://www.cl.cam.ac.uk/~pes20/armv8-mca/armv8-mca-draft.pdf).

While TSO allows reads to occur out-of-order with writes and a processor to
observe its own write before it is visible to others, the Armv8 memory model has
further relaxations. Code relying on pthread mutexes or locking abstractions
found in C++, Java or other languages shouldn't notice any difference. Code that
has a bespoke implementation of lockless data structures or implements its own
synchronization primitives will have to use the proper intrinsics and
barriers to correctly order memory transactions.

## Architecture specific optimization
Sometimes code will have architecture specific optimizations.  These can take many forms
sometimes their code is optimized in assembly like using specific instructions for
[CRC](https://github.com/php/php-src/commit/2a535a9707c89502df8bc0bd785f2e9192929422).
Other times it can be enabling a [feature](https://github.com/lz4/lz4/commit/605d811e6cc94736dd609c644404dd24c013fd6f)
that has been shown to work well on particular architectures. A quick way to see if any optimizations
are missing for Arm is to grep the code for `__x86_64__` `ifdef`s and see if there
is corresponding Arm code there too. If not that might be something to improve.

## Lock/Synchronization intensive
Graviton2 supports the Arm Large Scale Extensions (LSE). LSE based locking and synchronization
is an order of magnitude faster for highly contended locks with 64 cores running. For workloads
that have highly contended locks, compiling with `-march=armv8.2-a` will enable LSE based atomics
and can substantially increase performance. However, this will prevent the code
from running on an Arm v8.0 system such as AWS Graviton-based EC2 A1 instances.
With GCC 10 and newer an option `-moutline-atomics` will not inline atomics and
detect at run time the correct type of atomic to use. This is slightly worse
performing than `-march=armv8.2-a` but does retain backwards compatibility.

## Network intensive workloads
Depending on the workload it might make sense to enable adaptive RX interrupts
(e.g. `ethtool -C <interface> adaptive-rx on`).

## Profiling the code
If you aren't getting the performance you expect, one of the best ways to understand what is
going on in the system is to compare profiles of execution and understand where the CPUs are
spending time. This will frequently point to a hot function that could be optimized. A crutch
is comparing a profile between a system that is performing well and one that isn't to see the
relative difference in execution time.

Install the Linux perf tool:
```bash
# Amazon Linux 2
sudo yum install perf

# Ubuntu
sudo apt-get install linux-tools-$(uname -r)
```

Record a profile:
```
# If the program is run interactively
$ sudo perf record -g -F99 -o perf.data ./your_program

# If the program is a service, sample all cpus (-a) and run for 60 seconds while the system is loaded
$  sudo perf record -ag -F99 -o perf.data  sleep 60
```

Look at the profile:
```
$ perf report
```

Additionally, there is a tool that will generate a visual representation of the output which can sometimes
be more useful:
```
git clone https://github.com/brendangregg/FlameGraph.git
perf script -i perf.data | FlameGraph/stackcollapse-perf.pl | FlameGraph/flamegraph.pl > flamegraph.svg
```

For example, recently a we committed a patch to
[ffmpeg](http://ffmpeg.org/pipermail/ffmpeg-devel/2019-November/253385.html) to
improve performance. Comparing the execution time of a C5 vs an M6g
immediately uncovered an outlier function `ff_hscale_8_to_15_neon`.  Once we
identified this as the outlier we could focus on improving this function.

```
C5.4XL	                        M6g.4XL
19.89% dv_encode_video_segment	19.57% ff_hscale_8_to_15_neon
11.21% decode_significance_x86	18.02% get_cabac
8.68% get_cabac	                15.08% dv_encode_video_segment
8.43% ff_h264_decode_mb_cabac	5.85% ff_jpeg_fdct_islow_8
8.05% ff_hscale8to15_X4_ssse3	5.01% ff_yuv2planeX_8_neon
```

## Java
For languages that rely on a JIT (such an Java), the symbol information that is
captured is lacking making it difficult to understand where runtime is being consumed.
Similar to the code profiling example above, `libperf-jvmti.so` can be used to dump symbols for
JITed code as the JVM runs.

```bash
# find where libperf-jvmti.so is, on Ubuntu ... AL2 ...

# Run your java app with -agentpath:/path/to/libperf-jvmti.so added to the command line

# Inject the generated methods information into the perf.data file
$ perf inject -i perf.data -j /path/to/jit.dump -o perf.data.jit

# Process the new file
$ perf script -i perf.data.jit | ./FlameGraph/stackcollapse-perf.pl | ./FlameGraph/flamegraph.pl > ./flamegraph.svg
```
### Looking for x86 shared-objects in JARs
Java JARs can include shared-objects that are architecture specific. Some Java libraries check
if these shared objects are found and if they are they use a JNI to call to the native library
instead of relying on a generic Java implementation of the function. While the code might work,
without the JNI the performance can suffer.

A quick way to check if a JAR contains such shared objects is to simply unzip it and check if
any of the resulting files are shared-objects and if an aarch64 (arm64) shared-object is missing:
```
$ unzip foo.jar
$ find . -name "*.so" | xargs file
```
For each x86-64 ELF file, check there is a corresponding aarch64 ELF file
in the binaries. With some common packages (e.g. commons-crypto) we've seen that
even though a JAR can be built supporting Arm manually, artifact repositories such as
Maven don't have updated versions.

# Resources

Linaro and Arm maintain a tool ([Sandpiper](http://sandpiper.linaro.org/)) to
search for packages across multiple OSes and Docker official images. This can
be useful to see which versions of a package exist in distributions --
especially when there is a performance improvement in a particular version.

**Some specific resources:**
 * [AWS Graviton2](https://aws.amazon.com/ec2/graviton/)
 * [Neoverse N1 Software Optimization Guide](https://static.docs.arm.com/swog309707/a/Arm_Neoverse_N1_Software_Optimization_Guide.pdf?_ga=2.243116802.1800297234.1576266995-544296985.1575476490)
 * [Armv8 reference manual](https://static.docs.arm.com/ddi0487/ea/DDI0487E_a_armv8_arm.pdf?_ga=2.201302702.1800297234.1576266995-544296985.1575476490)


**Feedback?** ec2-arm-dev-feedback@amazon.com
