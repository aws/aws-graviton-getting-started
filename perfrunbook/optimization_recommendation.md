# Optimizing performance

[Graviton Performance Runbook toplevel](./graviton_perfrunbook.md)

This section describes multiple different optimization suggestions to try on Graviton2 instances to attain higher performance for your service.  Each sub-section defines some optimization recommendations that can help improve performance if you see a particular signature after measuring the performance using the previous checklists.

## Optimizing for large instruction footprint

1. On C/C++ applications, `-flto`, `-Os`, and [Feedback Directed Optimization](https://gcc.gnu.org/wiki/AutoFDO/Tutorial) can help with code layout using GCC.
2. On Java, `-XX:-TieredCompilation`, `-XX:ReservedCodeCacheSize` and `-XX:InitialCodeCacheSize` can be tuned to reduce the pressure the JIT places on the instruction footprint. The JDK defaults to setting up a 256MB region by default for the code-cache which over time can fill, become fragmented, and live code may become sparse.
    1. We recommend setting the code cache initially to: `-XX:-TieredCompilation -XX:ReservedCodeCacheSize=64M -XX:InitialCodeCacheSize=64M` and then tuning the size up or down as required.
    2. Experiment with setting `-XX:+TieredCompilation` to gain faster start-up time and better optimized code.
    3. When tuning the code JVM code cache, watch for `code cache full` error messages in the logs indicating that the cache has been set too small.  A full code cache can lead to worse performance.

## Optimizing for high TLB miss rates

A TLB (translation lookaside buffer) is a cache that holds recent virtual address to physical address translations for the CPU to use.  Making sure this cache never misses can improve application performance.

1. Enable Transparent Huge Pages (THP)
     `echo always > /sys/kernel/mm/transparent_hugepage/enabled` 
2. If your application can use pinned hugepages because it uses mmap directly, try reserving huge pages directly via the OS.  This can be done by two methods.
    1. At runtime: `sysctl -w vm.nr_hugepages=X`
    2. At boot time by specifying on the kernel command line in `/etc/default/grub`: `hugepagesz=2M hugepages=512`

## Porting and optimizing assembly routines

1. If you need to port an optimized routine that uses x86 vector instruction instrinsics to Graviton’s vector instructions (called NEON instructions), you can use the [SSE2NEON](https://github.com/DLTcollab/sse2neon) library to assist in the porting.  While SSE2NEON won’t produce optimal code, it generally gets close enough to reduce the performance penalty of not using the vector intrinsics.
2. For additional information on the vector instructions used on Graviton
    1. [Arm instrinsics guide](https://developer.arm.com/architectures/instruction-sets/intrinsics/)
    2. [Graviton2 core software optimization guide](https://developer.arm.com/documentation/pjdoc466751330-9707/2-0)

## Optimizing synchronization heavy optimizations

1. Look for specialized back-off routines for custom locks tuned using x86 `PAUSE` or the equivalent x86 `rep; nop` sequence. Graviton2 should use a single `ISB` instruction as a drop in replacement, for an example and explanation see recent commit to the [Wired Tiger storage layer](https://github.com/wiredtiger/wiredtiger/pull/6080/files#diff-08a92383c3904f531b067c488d6d6e34ddad0e3008313982b1b0712c0c3a7598).
2. If a locking routine tries to acquire a lock in a fast path before forcing the thread to sleep via the OS to wait, try experimenting with modifying the fast path to attempt the fast path a few additional times before executing down the slow path. [An example of this from the Finagle code-base where on Graviton2 we will spin longer for a lock before sleeping](https://github.com/twitter/finagle/blob/develop/finagle-stats-core/src/main/scala/com/twitter/finagle/stats/NonReentrantReadWriteLock.scala).
3. If you do not intend to run your application on Graviton1, try compiling your code on GCC using `-march=armv8.2-a` instead of using `-moutline-atomics` to reduce overhead of using synchronization builtins.

## Network heavy workload optimizations

1. Check ENA device tunings with `ethtool -c ethN` where `N` is the device number and check `Adaptive RX` setting. By default on instances without extra ENI’s this will be `eth0`.
    1. Set to `ethtool -C ethN adpative-rx off` for a latency sensitive workload
    2. ENA tunings via `ethtool` can be made permanent by editing `/etc/sysconfig/network-scripts/ifcfg-ethN` files.
2. Disable `irqbalance` from dynamically moving IRQ processing between vCPUs and set dedicated cores to process each IRQ.  Example script below:
  ```bash
  # Assign eth0 ENA interrupts to the first N-1 cores
  systemctl stop irqbalance
    
  irqs=$(grep "eth0-Tx-Rx" /proc/interrupts | awk -F':' '{print $1}')
  cpu=0
  for i in $irqs; do
    echo $cpu > /proc/irq/$i/smp_affinity_list
    let cpu=${cpu}+1
  done
  ```
3. Disable Receive Packet Steering (RPS) to avoid contention and extra IPIs. 
    1.  `cat /sys/class/net/ethN/queues/rx-N/rps_cpus` and verify they are set to `0`. In general RPS is not needed on Graviton2. 
    2. You can try using RPS if your situation is unique.  Read the [documentation on RPS](https://www.kernel.org/doc/Documentation/networking/scaling.txt) to understand further how it might help. Also refer to [Optimizing network intensive workloads on Amazon EC2 A1 Instances](https://aws.amazon.com/blogs/compute/optimizing-network-intensive-workloads-on-amazon-ec2-a1-instances/) for concrete examples.

## Metal instance IO optimizations

1. If on Graviton2 metal instances, try disabling the System MMU (Memory Management Unit) to speed up IO handling:
  ```bash
  %> cd ~/aws-gravition-getting-started/perfrunbook/utilities
  # Configure the SMMU to be off on metal, which is the default on x86.
  # Leave the SMMU on if you require the additional security protections it offers.
  # Virtualized instances do not expose an SMMU to instances.
  %> sudo ./configure_graviton_metal_iommu.sh off
  %> sudo shutdown now -r
  ```

