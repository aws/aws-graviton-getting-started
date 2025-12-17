# Debugging performance — “What part of the hardware is slow?”

[Graviton Performance Runbook toplevel](./README.md)

Sometimes, hardware, not code, is the reason for worse than expected performance. This may show up in the on-cpu profiles as every function is slightly slower on Graviton as more CPU time is consumed, but no obvious hot-spot function exists.  If this is the case, then measuring how the hardware performs can offer insight.  To do this requires counting special events in the CPU to understand which component of the CPU is bottlenecking the code from executing as fast as possible.

Modern server CPUs, whether they are from Intel, AMD or AWS all attempt to execute as many instructions as possible in a fixed amount of time by doing the following 4 fundamental operations in addition to executing at high frequencies: 
  * Executing instructions using multiple steps (pipelining)
  * Parallel instruction execution (out-of-order execution)
  * Predicting what instructions are needed next (speculation)
  * Predicting what values from DRAM should be cached nearby the processor (caching).   

The PMU (Performance Monitoring Unit) on modern CPUs have counters that can be programmed to count a set of events to give statistics on how aspects of those 4 fundamental operations are behaving.  When one aspect of the CPU starts becoming a bottleneck, for instance if caching starts to store the wrong values, then the CPU will execute instructions more slowly as it will be forced to access the correct values in main memory which is many times slower compared to a cache. 

There are hundreds of events available to monitor in a server CPU today which is many times more than the 4 fundamental underpinnings of a modern CPU. This is because hundreds of components work together to enable a modern CPU to execute instructions quickly. The guide below describes the primary events to count with the PMU and explains their meaning to enable a first level root cause analysis of the observed performance issue.

## How to Collect PMU counters

Not all instance sizes support PMU event collection.  Generally
instance sizes which have an entire dedicated socket have full access
to all PMU events, and smaller instance sizes of the newer generations
have a reduced set of events suitable for most profiling needs.  For
older generations smaller instance sizes may not support any PMU event
collection.  The table below captures these details:

|Instance Family |  Minimum Size for Full PMU Event Support | Basic Support at Smaller Sizes
|------|------------|------|
|*9g   | 48xlarge   | yes  |
|*8a   | 24xlarge   | yes  |
|*8i   | 48xlarge   | yes  |
|*8g   | 24xlarge   | yes  |
|*7a   | 24xlarge   | yes  |
|*7g   | 16xlarge   | yes  |
|*7i   | 24xlarge   | yes  |
|*6a   | 24xlarge   | no   |
|*6g   | 16xlarge   | yes  |
|*6i   | 16xlarge   | no   |
|*5   | c5.9xlarge, *5.12xlarge | no


To measure the standard CPU PMU events, do the following:

1. Reserve SUT instances, i.e. a m6g.16xl and c5.12xl to get access to all events
2. Cut memory and vCPUs down to the size you need to represent your intended instance sizes
  ```bash
  # Cut memory down to the required size
  %> ssh <username>@<instance-ip>
  %> cd ~/aws-graviton-getting-started/perfrunbook/utilities/
  %> sudo ./configure_mem_size.sh <size in GB>
  %> sudo reboot now
    
  # Cut down vCPUs needed to the required size on x86
  %> sudo ./configure_vcpus.sh <# vcpus> threads
  # Cut down vCPUs needed on Graviton
  %> sudo ./configure_vcpus.sh <# vcpus> cores
  ```
3. Measure individual hardware events or useful ratios (i.e. instruction commit event count over cycle tick counts to get instruction throughput per cycle) with our helper script. It will plot a time-series curve of the event count's behavior over time and provide geomean and percentile statistics.
  ```bash
  # In terminal 1
  %> <start load generator or benchmark>
    
  # In terminal 2
  %> cd ~/aws-graviton-getting-started/perfrunbook/utilities
  # AMD (5a, 6a and 7a) instances not supported currently.
  %> sudo python3 ./measure_and_plot_basic_pmu_counters.py --stat ipc
    
  # Example Output
  1.6 ++-----------------------+------------------------+------------------------+-----------------------+------------------------+-----------------------++
       +                        +                        +                        +                       +                        +                        +
       |                                                                                           *                                                        |
  1.55 ++                                           *           *                                 **                                  *                    ++
       |         *                                 * *         * *               **              * *              *                 ***                     |
       |        **      *                ******    * *  **     *  *     *    **** *     **      *  *             * *             ***   *                    |
       | ***   *  *    * *   ***  *    **         *   **  *  **   *   ** * **     *   **  *     *   *     ***** *   *       ** **      *                    |
   1.5 ++*  ***   *    *  * *    * *  *        ***         **      ***    *       *   *    *** *    *     *    *     *      * *        *     ***    **     ++
       |*         *   *    *    *   * *                                            *  *        *    *    *            *    *            *    *  **** *      |
       |*          ***               *                                             * *        *     *    *            *    *            *    *       *      |
  1.45 +*          *                                                               * *              *   *              *   *            *    *       *     ++
       *                                                                           * *              *   *               * *              *  *        *      |
       *                                                                           * *              *   *               * *              *  *        *      |
   1.4 ++                                                                          * *              *  *                 *               *  *         *    ++
       |                                                                            **               * *                 *                * *         *     |
       |                                                                            *                **                                   * *         *     |
  1.35 ++                                                                           *                **                                   * *         *    ++
       |                                                                            *                *                                    **          *     |
       |                                                                                                                                   *          *     |
       |                                                                                                                                   *          *     |
   1.3 ++                                                                                                                                             *    ++
       |                                                                                                                                              *     |
       |                                                                                                                                              *     |
  1.25 ++                                                                                                                                             *    ++
       |                                                                                                                                              *     |
       |                                                                                                                                               *    |
   1.2 ++                                                                                                                                              *   ++
       |                                                                                                                                               *    |
       |                                                                                                                                               *    |
       |                                                                                                                                               *    |
  1.15 ++                                                                                                                                              *   ++
       |                                                                                                                                                    |
       +                        +                        +                        +                       +                        +                        +
   1.1 ++-----------------------+------------------------+------------------------+-----------------------+------------------------+-----------------------++
       0                        10                       20                       30                      40                       50                       60
                                                           gmean:   1.50 p50:   1.50 p90:   1.50 p99:   1.61
  ```
1. You can also measure all relevant ratios at once using our aggregate PMU measuring script if you do not need a time-series view.  It prints out a table of measured PMU ratios at the end and supports the same events.
  ```bash
  # In terminal 1
  %> <start load generator or benchmark>
    
  # In terminal 2
  %> cd ~/aws-graviton-getting-started/perfrunbook/utilities
  # AMD (5a, 6a, and 7a) instances not supported currently.
  %> sudo python3 ./measure_aggregated_pmu_stats.py --timeout 300
|Ratio               |   geomean|       p10|       p50|       p90|       p95|       p99|     p99.9|      p100|
|ipc                 |      1.81|      1.72|      1.81|      1.90|      1.93|      1.95|      1.95|      1.95|
|branch-mpki         |      0.01|      0.01|      0.01|      0.01|      0.01|      0.02|      0.02|      0.02|
|code_sparsity       |      0.00|      0.00|      0.00|      0.00|      0.00|      0.00|      0.00|      0.00|
|data-l1-mpki        |     11.24|     10.48|     11.25|     12.05|     12.21|     12.62|     12.62|     12.62|
|inst-l1-mpki        |      0.08|      0.07|      0.08|      0.09|      0.10|      0.15|      0.15|      0.15|
|l2-ifetch-mpki      |      0.06|      0.05|      0.06|      0.06|      0.07|      0.12|      0.12|      0.12|
|l2-mpki             |      0.71|      0.66|      0.70|      0.76|      0.77|      1.03|      1.03|      1.03|
|l3-mpki             |      0.49|      0.42|      0.49|      0.55|      0.63|      0.67|      0.67|      0.67|
|stall_frontend_pkc  |      1.97|      1.61|      1.90|      2.49|      2.68|      5.28|      5.28|      5.28|
|stall_backend_pkc   |    425.00|    414.64|    424.81|    433.63|    435.82|    441.57|    441.57|    441.57|
|inst-tlb-mpki       |      0.00|      0.00|      0.00|      0.00|      0.00|      0.00|      0.00|      0.00|
|inst-tlb-tw-pki     |      0.00|      0.00|      0.00|      0.00|      0.00|      0.00|      0.00|      0.00|
|data-tlb-mpki       |      1.49|      1.23|      1.55|      1.65|      1.66|      1.78|      1.78|      1.78|
|data-tlb-tw-pki     |      0.00|      0.00|      0.00|      0.01|      0.01|      0.01|      0.01|      0.01|
|inst-neon-pkc       |      0.31|      0.30|      0.30|      0.31|      0.31|      0.40|      0.40|      0.40|
|inst-scalar-fp-pkc  |      2.43|      2.37|      2.44|      2.49|      2.51|      2.52|      2.52|      2.52|
|stall_backend_mem_pkc|     90.73|     83.97|     90.71|     97.67|     97.98|    100.98|    100.98|    100.98|
|inst-sve-pkc        |    419.00|    409.92|    419.83|    426.79|    430.73|    433.08|    433.08|    433.08|
|inst-sve-empty-pkc  |      0.00|      0.00|      0.00|      0.00|      0.00|      0.00|      0.00|      0.00|
|inst-sve-full-pkc   |    180.89|    176.99|    181.24|    184.31|    185.91|    187.16|    187.16|    187.16|
|inst-sve-partial-pkc|      2.39|      2.27|      2.38|      2.50|      2.53|      2.58|      2.58|      2.58|
|flop-sve-pkc        |   1809.47|   1768.84|   1813.91|   1842.77|   1860.45|   1871.86|   1871.86|   1871.86|
|flop-nonsve-pkc     |      2.48|      2.41|      2.48|      2.54|      2.56|      2.57|      2.57|      2.57|
  ```

## Top-down method to debug hardware performance

This checklist describes the top-down method to debug whether the hardware is under-performing and what part is underperforming.  The checklist describes event ratios to check that are included in the helper-script.  All ratios are in terms of either misses-per-1000(kilo)-instruction or per-1000(kilo)-cycles.  This checklist aims to help guide whether a hardware slow down is coming from the front-end of the processor or the backend of the processor and then what particular part.  The front-end of the processor is responsible for fetching and supplying the instructions.  The back-end is responsible for executing the instructions provided by the front-end as fast as possible.  A bottleneck in either part will cause stalls and a decrease in performance.  After determining where the bottleneck may lie, you can proceed to [Section 6](./optimization_recommendation.md) to read suggested optimizations to mitigate the problem.

1. Start by measuring `ipc` (Instructions per cycle) on each instance-type.  A higher IPC is better. A lower number for `ipc` on Graviton compared to x86 indicates *that* there is a performance problem.  At this point, proceed to attempt to root cause where the lower IPC bottleneck is coming from by collecting frontend and backend stall metrics.
2. Next, measure `stall_frontend_pkc` and `stall_backend_pkc` (pkc = per kilo cycle) and determine which is higher.  If stalls in the frontend are higher, it indicates the part of the CPU responsible for predicting and fetching the next instructions to execute is causing slow-downs.  If stalls in the backend are higher, it indicates the machinery that executes the instructions and reads data from memory is causing slow-downs

### Drill down front end stalls

Front end stalls commonly occur if the CPU cannot fetch the proper instructions, either because it is speculating the wrong destination for a branch, or stalled waiting to get instructions from memory.  Below are steps to identify if this is the case.

1. Measure `branch-mpki` which defines how many predicted branches are wrong and fetched the wrong instructions to execute next. Every time the CPU predicts incorrectly it has to flush the current set of instructions it was working on and start over by fetching new instructions from the correct place.  A `branch-mpki` average value of >10 indicates the branch prediction logic is bottlenecking the processor.
2. Measure `inst-l1-mpki`.  A value >20 indicates the working-set code footprint is large and is spilling out of the fastest cache on the processor and is potentially a bottleneck.
3. Measure `inst-tlb-mpki`. A value >0 indicates the CPU has to do extra stalls to translate the virtual addresses of instructions into physical addresses before fetching them and the footprint is too large.
4. Measure `inst-tlb-tw-pki` . A value >0 indicates the instruction footprint might be too large.
5. Measure `code-sparsity` . A number >0.5 indicates the code being executed by the CPU is very sparse. This counter is only available on Graviton 16xlarge or metal instances. If the number is >0.5 for the workload under test please see [Optimizing For Large Instruction Footprints](./optimization_recommendation.md#optimizing-for-large-instruction-footprint).
5. If front-end stalls are the root cause, the instruction footprint needs to be made smaller, proceed to [Section 6](./optimization_recommendation.md) for suggestions on how to reduce front end stalls for your application..

### Drill down back-end stalls

Backend stalls are caused when the CPU is unable to make forward progress executing instructions because a computational resource is full.  This is commonly due to lacking enough resources to execute enough memory operations in parallel because the data set is large and current memory requests are waiting for responses.  This checklist details how to gather information on how well the core is caching the data-set and identify if the backend is stalling because of it.

1. Measure `data-l1-mpki` .  If this number is >20, indicates the working set data footprint could be an issue.
2. Measure `l2-mpki`.  If this number is >10, indicates the working set data footprint could be an issue.
3. Measure `l3-mpki`. If this number is >10, indicates the working set data footprint is not fitting in L3 and data references are being served by DRAM.  The l3-mpki also indicates the DRAM bandwidth requirement of your application, a higher number means more DRAM bandwidth will be consumed, this may be an issue if your instance is co-located with multiple neighbors also consuming a measurable amount of DRAM bandwidth.
4. Measure `data-tlb-mpki` . A number >0 indicates the CPU has to do extra stalls to translate the virtual address of load and store instructions into physical addresses the DRAM understands before issuing the load/store to the memory system.  A TLB (translation lookaside buffer) is a cache that holds recent virtual address to physical address translations.
5. Measure `data-tlb-tw-pki` . A number >0 indicates the CPU has to do extra stalls to translate the virtual address of the load/store instruction into physical addresses the DRAM understands before issuing to the memory system. In this case the stalls are because the CPU must walk the OS built page-table, which requires **extra memory references** before the requested memory reference from the application can be executed.
6. If back-end stalls due to the cache-system and memory system are the problem, the data-set size and layout needs to be optimized.
7. Proceed to [Section 6](./optimization_recommendation.md) to view optimization recommendations for working with a large data-set causing backend stalls.

### Drill down Vectorization

Vectorization is accomplished either by SVE or NEON instructions.  SVE vectorization will use 256-bit vectors on Graviton 3 processors, but the scalable nature of SVE makes both the code and binary vector-length agnostic.  NEON vectorization is always a 128-bit vector size, and does not have the predicate feature of SVE.

For SVE instructions there are metrics which describe how many SVE instructions had empty, full and partially-filled SVE predicates: `inst-sve-empty-pkc`, `inst-sve-partial-pkc`, and `inst-sve-full-pkc`.  These metrics apply to all SVE instructions (loads, stores, integer, and floating-point operations).  The `pkc` term indicates the counters are in units of "per kilo cycle".

A single SVE instruction can execute multiple (vectorized) floating point operations in the ALU.  These are counted individually by `flop-sve-pkc`.  For example: a single SVE `FMUL` instruction on 32-bit floats on Graviton 3's 256-bit vector will increment the `flop-sve-pkc` counter by eight because the operation is executed on the eight 32-bit floats that fit in the 256-bit vector.  Some instructions, such as `FMA` and (Fused Multiply Add) excute two floating point operations per item in the vector and increment the counter accordingly.  The `flop-sve-pkc` counter is incremented assuming a full SVE predicate.

Floating point operations for NEON and scalar instructions are counted together in the `flop-nonsve-pkc` counter.  For a single NEON `FMUL` instruction on 32-bit floats, the `inst-neon-pkc` counter will increment by one, and the `flop-nonsve-pkc` counter will increment by four (the number of 32-bit floats in a 128-bit NEON register).  For a single scalar `FMUL` instruction, the `flop-nonsve-pkc` counter will increment by one.  Some instructions (e.g., Fused Multiply Add) will increment the value by two.

The total number of floating-point instructions retired every 1000 cycles is `inst-scalar-fp-pkc + (inst-neon-pkc + inst-sve-pkc)*<alpha>`, where `<alpha>` is a user-provided estimate of the fraction of SVE and NEON instructions which task the floating-point ALU vs loads, stores, or integer operations.  The total number of floating-point operations executed by those instructions is `flop-nonsve-pkc + flop-sve-pkc*<beta>`, where `<beta>` is a user-provided estimate of how often the predicate was full.  To calculate a maximum expected value for these metrics, consult the ARM Software Optimization Guide and determine a FLOP per kilocycle from the instruction throughput and element size of the operation.  A code with no loads, stores, or dependencies performing `FMUL` entirely in L1 cache on 32-bit floats could theoretically observe `flop-sve-pkc` of 16,000 with SVE, or `flop-nonsve-pkc` of 16,000 with NEON SIMD, or `flop-nonsve-pkc` of 4,000 with scalar operations.

A footnote to readers of the ARM architecture PMU event description: SVE floating point operations are reported by hardware in units of "floating point operations per 128-bits of vector size", however the aggregation script we provide has already accounted for the Graviton 3 vector width before reporting.

## Additonal PMUs and PMU events

On metal instances, all available hardware PMUs and their events are exposed to instances and can be accessed so long as driver support by the OS in use is available.  
These extra PMUs help with diagnosing specific use cases, but are generally less applicable than the more widely used CPU PMU.
These PMU and events include: the Statistical Profiling Extension that provides precise data for sampled instructions, and
the Coherent Mesh Network PMU on Graviton instances to measure system level events such as system wide DRAM bandwidth use.
These PMUs will be covered in this section with links to documentation and Linux kernel support.

### Capturing Statistical Profiling Extension (SPE) hardware events on Graviton metal instances

The SPE PMU on Graviton enables cores to precisely trace events for individual instructions and record them to a memory buffer with the
linux `perf` tool.  It samples instructions from the executed instruction stream at random.  It is particularly useful for finding information
about particular loads that are always long latency, false sharing of atomic variables, or branches that are often mis-predicted and causing slow-downs.
Because SPE is precise, this information can be attributed back to individual code lines that need to be optimized.
SPE is enabled Graviton 2 and 3 metal instances.  The below table shows for which Linux distributions and kernel versions SPE is known to be
enabled.

| Distro       | Kernel  |
|--------------|---------|
| AL2          | 5.10    |
| AL2023       | >=6.1.2 |
| Ubuntu 20.04 | >=5.15  |
| Ubuntu 22.04 | >=6.2   |

On Amazon Linux 2 and 2023, the SPE PMU is available by default on Graviton metal instances, you can check for its existence by verifying:
```
# Returns the directory exists
ls /sys/devices/arm_spe_0
```

On Ubuntu to enable SPE requires four extra steps
```
# Install the arm_spe_pmu.ko module
sudo apt install linux-modules-extra-$(uname -r)

# Add kpti=off to the kernel boot command line: GRUB_CMDLINE_LINUX in /etc/default/grub, to set it for all the installed kernels.
# Note, the options passed to GRUB_CMDLINE_LINUX_DEFAULT will only propagate to the default kernel and not to all the installed kernels.
# Reboot instance

sudo modprobe arm_spe_pmu

# Verify exists
ls /sys/devices/arm_spe_0
```

SPE can be used via Linux `perf`. An example that samples every 1000'th branch on core 0 system wide is shown below:
`perf record -C0 -c1000 -a -e arm_spe_0/branch_filter=1,ts_enable=1,pct_enable=1,pa_enable=1,jitter=1/ -- sleep 30`

Processing the data can be done with `perf report` to inspect hot functions and annotate assembly. If you want to look at
the samples directly, you can use the [Arm SPE Parser](https://gitlab.arm.com/telemetry-solution/telemetry-solution/-/tree/spe-parser-prototype/tools/spe-parser).

Be aware that SPE produces a large of volume of data (many GBs) if the sampling period is low and you collect the data over a long time.

### Capturing cache coherence issues
The `perf c2c` command can be used to analyze cache coherence issues and false sharing in multi-core systems. It needs SPE PMU available on Graviton metal instances.

`perf c2c record ./application`

### Capturing Coherent Mesh Network (CMN) hardware events on Graviton metal instances

On Graviton the CMN connects the CPUs to each other, to the memory controller, the I/O subsystem and provides the System Level Cache.
Its PMU counts events such as requests to SLC, DRAM (memory bandwidth), IO bus requests or coherence snoop events.
These metrics can be used to assess an application's utilization of such system level resources and if resources are used efficiently.
CMN counters are only accessible on Graviton metal-type instances and certain OSes and kernels.


|Distro      |Kernel   | Graviton2 (c6g) | Graviton3 (c7g) |
|------------|---------|-----------------|-----------------|
|Ubuntu-20.04| 5.15    |  yes            |    no           |
|Ubuntu-20.04| >=5.19  |  yes            |    yes          |
|Ubuntu-22.04| 5.15    |  no             |    no           |
|Ubuntu-22.04| >=5.19  |  yes            |    yes          |
|AL2         | 5.10    |  no             |    no           |
|AL2023      | 6.1.2   |  yes            |    yes          |


General procedure on Ubuntu
```
sudo apt install linux-modules-extra-aws
sudo modprobe arm-cmn
ls /sys/devices/arm_cmn_0/events
```
On AL2023/AL2:
```
sudo modprobe arm_cmn
ls /sys/devices/arm_cmn_0/events
```
Examples for capturing events:
```
sudo perf stat -C 0 -e /arm_cmn_0/hnf_mc_reqs/ sleep 15 #count of memory request
sudo perf stat -C 0 -e /arm_cmn_0/rnid_rxdat_flits/ sleep 15 #count AXI 'master' read requests
sudo perf stat -C 0 -e /arm_cmn_0/rnid_txdat_flits/ sleep 15 #count AXI 'master' write requests
```
Further information about capturing fabric events is available here:

[ARM documentation for Graviton2's CMN-600](https://developer.arm.com/documentation/100180/0302/?lang=en)

[ARM documentation for Graviton3's CMN-650](https://developer.arm.com/documentation/101481/0200/?lang=en)

