# Monitoring tools for AWS Graviton
Listed below are some monitoring and profiling tools supported on AWS Gravtion. Also listed are some differences when compared to the tools available on x86 processor architectures.

Some of the most commonly used tools such as _top, htop, iostat, lstopo, hwloc, dmidecode, lmbench, Linux perf_ are supported on AWS Graviton processors. There are some tools such as Intel MLC, Intel VTune Profiler, PCM that are supported only on Intel processors and some tools such as _turbostat_ supported on x86 processors.

## Details
### Info utilities
#### *lscpu* utility
The *lscpu* utility shows details of the processor features such as architecture, number of cores, active CPUs, caches, NUMA, instruction support and optionally CPU frequency.

*$ lscpu*
|Attribute| Value|
|---    |---    |
|Architecture| aarch64|
|CPU(s)| 64|
|On-line CPU(s) list| 0-63|
|L1d| 4 MiB (64 instances)|
|...|...|
|NUMA node(s)|  1|
|...|...|

#### *dmidecode* to get CPU frequency info
The *dmidecode* utility is a tool for listing details of the system's hardware components.

*$ sudo dmidecode | less*
|Attribute| Value|
|---    |---    |
|Socket Designation| CPU00|
|Type| Central Processor|
|Family| ARMv8|
|Manufacturer| AWS|
|...|...|
|Max Speed| 2600 MHz|
|Current Speed| 2600 MHz|
|...|...|

#### *hwloc* and *lstopo* utilities
Shown below is sample output for these utilities on a c6g.2xlarge instance.

*$ hwloc-info*

    depth 0:           1 Machine (type #0)
        depth 1:          1 Package (type #1)
            depth 2:         1 L3Cache (type #6)
                depth 3:        8 L2Cache (type #5)
                    depth 4:       8 L1dCache (type #4)
                        depth 5:      8 L1iCache (type #9)
            ...


*$ lstopo*

    Machine (15GB total)
        Package L#0
            NUMANode L#0 (P#0 15GB)
                L3 L#0 (32MB)
                L2 L#0 (1024KB) + L1d L#0 (64KB) + L1i L#0 (64KB) + Core L#0 + PU L#0 (P#0)
                L2 L#1 (1024KB) + L1d L#1 (64KB) + L1i L#1 (64KB) + Core L#1 + PU L#1 (P#1)
                L2 L#2 (1024KB) + L1d L#2 (64KB) + L1i L#2 (64KB) + Core L#2 + PU L#2 (P#2)
        ...

### Perf monitoring utilities
On AWS Graviton processors, the **Linux perf** tool comes handy to collect an application execution profile, hardware perf counters. Much of the functionality provided by tools such as Intel *VTune Profiler* and *PCM* are supported in *Linux perf*. Below are some details of its usage/ syntax.

#### Collect basic CPU statistics for the specified command or system wide
*$ perf stat command*

Shown below are *Linux perf* stats collected at system wide on a c6g.2xlarge instance.

*$ perf stat*

 Performance counter stats for 'system wide':

          87692.26 msec cpu-clock                 #    8.000 CPUs utilized
               441      context-switches          #    5.029 /sec
                13      cpu-migrations            #    0.148 /sec
                 2      page-faults               #    0.023 /sec
          25115021      cycles                    #    0.000 GHz
          28853592      instructions              #    1.15  insn per cycle
             68126      branch-misses

      10.961122204 seconds time elapsed

#### Collect basic/ specific CPU hardware counters, for a specific command or system wide, for 10 seconds
One can collect hardware events/ counters for an application, on a specific CPU, for a PID or system wide as follows:

*$ perf stat -e cycles,instructions,cache-references,cache-misses,bus-cycles -a sleep 10*

 Performance counter stats for 'system wide':

         161469308      cycles                                                        (80.01%)
         120685678      instructions              #    0.75  insn per cycle           (79.97%)
          42132948      cache-references                                              (80.01%)
           2001520      cache-misses              #    4.750 % of all cache refs      (80.02%)
         160016796      bus-cycles                                                    (60.00%)

      10.002896494 seconds time elapsed

#### View the profile using perf report command
*$ perf report*
|Overhead  |   Command  |       Shared Object   |       Symbol|
|---	|---	|---	|---    |
|72.44%   |       functionA |       functionA       |       classA::functionA|
|7.66%    |       functionB |       libB.so       |       classB::functionB|
|...      |                 |                       |                 |
|0.81%    |       functioA  |       libc-2.31.so    |       memcmp|

More details on how to use Linux perf utility on AWS Graviton processors is available [here](https://github.com/aws/aws-graviton-getting-started/blob/main/optimizing.md#profiling-the-code).

## Summary: Utilities on AWS Graviton vs. Intel x86 architectures
|Processor	|x86	|Graviton2,3	|
|---	|---	|---	|
|CPU frequency listing	|*lscpu, /proc/cpuinfo, dmidecode*	|*dmidecode*	|
|*turbostat* support	|Yes	|No	|
|*hwloc* support	|Yes	|Yes	|
|*lstopo* support	|Yes	|Yes	|
|*i7z* Works	|Yes	|No	|
|*lmbench*	|Yes	|Yes	|
|Intel *MLC*  |Yes    |No     |
|Performance monitoring tools	|_[VTune Profiler](https://www.intel.com/content/www/us/en/developer/tools/oneapi/vtune-profiler.html) and [PCM](https://github.com/opcm/pcm), [Linux perf](https://www.brendangregg.com/perf.html)_	|_[Linux perf](https://www.brendangregg.com/perf.html), [Arm Forge](https://developer.arm.com/Tools%20and%20Software/Arm%20Forge)_	|

Utilities such as *lmbench* are available [here](http://lmbench.sourceforge.net/) and can be built for AWS Graviton processors to obtain latency and bandwidth stats.

**Notes**:

**1.** The ARM Linux kernel community has decided not to put CPU frequency in _/proc/cpuinfo_ which can be read by tools such as _lscpu_ or directly.

**2.** On AWS Graviton 2/3 processors, Turbo isn’t supported. So, utilities such as ‘turbostat’ aren’t supported/ relevant for Arm architecture (and not on AWS Graviton processor either). Also, tools such as *[i7z](https://code.google.com/archive/p/i7z/)* for discovering CPU frequency, turbo, sockets and other information are only supported on Intel architecture/ processors. Intel *MLC* is a memory latency checker utility that is only supported on Intel processors.
