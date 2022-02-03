# Debugging performance — “What part of the hardware is slow?”

[Graviton Performance Runbook toplevel](./graviton_perfrunbook.md)

Sometimes, hardware, not code, is the reason for worse than expected performance. This may show up in the on-cpu profiles as every function is slightly slower on Graviton as more CPU time is consumed, but no obvious hot-spot function exists.  If this is the case, then measuring how the hardware performs can offer insight.  To do this requires measuring special counters in the CPU to understand which component of the CPU is bottlenecking the code from executing as fast as possible.

Modern server CPUs, whether they are from Intel, AMD or AWS all attempt to execute as many instructions as possible in a fixed amount of time by doing the following 4 fundamental operations in addition to executing at high frequencies: 
  * Executing instructions using multiple steps (pipelining)
  * Parallel instruction execution (out-of-order execution)
  * Predicting what instructions are needed next (speculation)
  * Predicting what values from DRAM should be cached nearby the processor (caching).   

The PMU counters give statistics on how aspects of those 4 fundamental operations are behaving.  When one aspect of the CPU starts becoming a bottleneck, for instance if caching starts to store the wrong values, then the CPU will execute instructions more slowly as it will be forced to access the correct values in main memory which is many times slower compared to a cache. 

There are hundreds of counters in a server CPU today which is many times more than the 4 fundamental underpinnings of a modern CPU. This is because hundreds of components work together to enable a modern CPU to execute instructions quickly. The guide below describes the primary counters to collect and explains their meaning to enable a first level root cause analysis of the observed performance issue.

## How to Collect PMU counters

PMU counters are available on all Graviton2 instances (a limited subset is available on *6g sizes <16xl, we recommend using a 16xl for experiments needing PMU counters to get access to all of them), and on 5th generation instances >c5.9xl, >c/m/r5.12xl, and >c5a.24xl.  To measure performance counters, do the following:

1. Reserve SUT instances, i.e. a m6g.16xl and c5.12xl to get access to all counters
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
3. Measure a set of hardware counters with our helper script. It will plot a time-series curve of the counter's behavior over time and provide geomean and percentile statistics.
  ```bash
  # In terminal 1
  %> <start load generator or benchmark>
    
  # In terminal 2
  %> cd ~/aws-graviton-getting-started/perfrunbook/utilities
  # Use --uarch Graviton2 for Graviton2 instances, and --uarch CXL for c/m/r5 instances
  # C5a instances not supported currently.
  %> sudo python3 ./measure_and_plot_basic_pmu_counters.py --stat ipc --uarch Graviton2
    
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

## Top-down method to debug hardware performance

This checklist describes the top-down method to debug whether the hardware is under-performing and what part is underperforming.  The checklist describes counters to check that are included in the helper-script.  All metrics are in terms of either misses-per-1000(kilo)-instruction or per-1000(kilo)-cycles.  This checklist aims to help guide whether a hardware slow down is coming from the front-end of the processor or the backend of the processor and then what particular part.  The front-end of the processor is responsible for fetching and supplying the instructions.  The back-end is responsible for executing the instructions provided by the front-end as fast as possible.  A bottleneck in either part will cause stalls and a decrease in performance.  After determining where the bottleneck may lie, you can proceed to [Section 6](./optimization_recommendation.md) to read suggested optimizations to mitigate the problem.

1. Start by measuring `ipc` (Instructions per cycle) on each instance-type.  A higher IPC is better. A lower number for `ipc` on Graviton2 compared to x86 indicates *that* there is a performance problem.  At this point, proceed to attempt to root cause where the lower IPC bottleneck is coming from by collecting frontend and backend stall metrics.
2. Next, measure `stall_frontend_pkc` and `stall_backend_pkc` (pkc = per kilo cycle) and determine which is higher.  If stalls in the frontend are higher, it indicates the part of the CPU responsible for predicting and fetching the next instructions to execute is causing slow-downs.  If stalls in the backend are higher, it indicates the machinery that executes the instructions and reads data from memory is causing slow-downs

### Drill down front end stalls

Front end stalls commonly occur if the CPU cannot fetch the proper instructions, either because it is speculating the wrong destination for a branch, or stalled waiting to get instructions from memory.  Below are steps to identify if this is the case.

1. Measure `branch-mpki` which defines how many predicted branches are wrong and fetched the wrong instructions to execute next. Every time the CPU predicts incorrectly it has to flush the current set of instructions it was working on and start over by fetching new instructions from the correct place.  A `branch-mpki` average value of >10 indicates the branch prediction logic is bottlenecking the processor.
2. Measure `inst-l1-mpki`.  A value >20 indicates the working-set code footprint is large and is spilling out of the fastest cache on the processor and is potentially a bottleneck.
3. Measure `inst-tlb-mpki`. A value >0 indicates the CPU has to do extra stalls to translate the virtual addresses of instructions into physical addresses before fetching them and the footprint is too large.
4. Measure `inst-tlb-tw-pki` . A value >0 indicates the instruction footprint might be too large.
5. Measure `code-sparsity` . A number >0.5 indicates the code being executed by the CPU is very sparse. This counter is only available on Graviton 16xlarge or metal instances. If the number is >0.5 for please see [Optimizing For Large Instruction Footprints](./optimization_recommendation.md#optimizing-for-large-instruction-footprint).
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

