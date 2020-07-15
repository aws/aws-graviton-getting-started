# Optimizing for Graviton

## Debugging Problems

It's possible that incorrect code will work fine on an existing system, but
produce an incorrect result when using a new compiler. This could be because
it relies on undefined behavior in the language (e.g. assuming char is signed in C/C++,
or the behavior of signed integer overflow), contains memory management bugs that
happen to be exposed by aggressive compiler optimizations, or incorrect ordering.
Below are some techniques / tools we have used to find issues
while migrating our internal services to newer compilers and Graviton2.

### Using Sanitizers
The compiler may generate code and layout data slightly differently on Graviton
compared to an x86 system and this could expose latent memory bugs that were previously
hidden. On GCC, the easiest way to look for these bugs is to compile with the
memory sanitizers by adding the below to standard compiler flags:

```
    CFLAGS += -fsanitize=address -fsanitize=undefined
    LDFLAGS += -fsanitize=address  -fsanitize=undefined
```

Then run the resulting binary, any bugs detected by the sanitizers will cause
the program to exit immediately and print helpful stack traces and other
information.

### Ordering issues
Arm is weakly ordered, similar to POWER and other modern architectures. While
x86 is a variant of total-store-ordering (TSO).
Code that relies on TSO may lack barriers to properly order memory references.
Armv8 based systems, including Graviton and Graviton2 are [weakly ordered
multi-copy-atomic](https://www.cl.cam.ac.uk/~pes20/armv8-mca/armv8-mca-draft.pdf).

While TSO allows reads to occur out-of-order with writes and a processor to
observe its own write before it is visible to others, the Armv8 memory model has
further relaxations for performance and power efficiency.
Code relying on pthread mutexes or locking abstractions
found in C++, Java or other languages shouldn't notice any difference. Code that
has a bespoke implementation of lockless data structures or implements its own
synchronization primitives will have to use the proper intrinsics and
barriers to correctly order memory transactions. If you run into an issue with
memory ordering please feel free to open an issue in this GitHub repo, and one
of our AWS experts will contact you.

### Architecture specific optimization
Sometimes code will have architecture specific optimizations. These can take many forms:
sometimes the code is optimized in assembly using specific instructions for
[CRC](https://github.com/php/php-src/commit/2a535a9707c89502df8bc0bd785f2e9192929422),
other times the code could be enabling a [feature](https://github.com/lz4/lz4/commit/605d811e6cc94736dd609c644404dd24c013fd6f)
that has been shown to work well on particular architectures. A quick way to see if any optimizations
are missing for Arm is to grep the code for `__x86_64__` `ifdef`s and see if there
is corresponding Arm code there too. If not, that might be something to improve.
We welcome suggestions by opening an issue in this repo.

### Lock/Synchronization intensive workload
Graviton2 supports the Arm Large Scale Extensions (LSE). LSE based locking and synchronization
is an order of magnitude faster for highly contended locks with high core counts (e.g. 64 with Graviton2).
For workloads that have highly contended locks, compiling with `-march=armv8.2-a` will enable LSE based atomics and can substantially increase performance. However, this will prevent the code
from running on an Arm v8.0 system such as AWS Graviton-based EC2 A1 instances.
With GCC 10 and newer an option `-moutline-atomics` will not inline atomics and
detect at run time the correct type of atomic to use. This is slightly worse
performing than `-march=armv8.2-a` but does retain backwards compatibility.

### Network intensive workloads
In some workloads, the packet processing capability of Graviton2 is both faster and
lower-latency than other platforms, which reduces the natural “coalescing”
capability of Linux kernel and increases the interrupt rate.
Depending on the workload it might make sense to enable adaptive RX interrupts
(e.g. `ethtool -C <interface> adaptive-rx on`).

## Profiling the code
If you aren't getting the performance you expect, one of the best ways to understand what is
going on in the system is to compare profiles of execution and understand where the CPUs are
spending time. This will frequently point to a hot function that could be optimized. A crutch
is comparing a profile between a system that is performing well and one that isn't to see the
relative difference in execution time. Feel free to open an issue in this
GitHub repo for advice or help.

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

For example, in March 2020, we committed a patch to
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