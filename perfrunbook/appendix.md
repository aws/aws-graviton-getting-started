# Appendix:

[Graviton Performance Runbook toplevel](./graviton_perfrunbook.md)

This Appendix contains additional information for engineers that want to go deeper on a particular topic, such as using different PMU counters to understand how the code is executing on the hardware, discussion on load generators, and additional tools to help with code observability.

## Useful Graviton2 PMU Counters and ratios

The following list of counter ratios has been curated to list counters useful for performance debugging. The more extensive list of counters is contained in the following references:

* [Arm ARM](https://developer.arm.com/documentation/102105/latest)
* [Neoverse N1 TRM](https://developer.arm.com/documentation/100616/0400/debug-descriptions/performance-monitor-unit/pmu-events)
* [Neoverse N1 PMU Guide](https://developer.arm.com/documentation/PJDOC-466751330-547673/r4p1?lang=en&rev=0)

|METRIC	|Counter #1	|Counter #2	|Formula	|Description	|
|---	|---	|---	|---	|---	|
|IPC	|0x8 (INST_RETIRED)	|0x11 (CPU_CYCLES)	|#1 / #2	|Instructions per cycle, metric to understand how much parallelism in the core is left unused.	|
|Stalls Frontend PKC	|0x23 (STALL_FRONTEND)	|0x11 (CPU_CYCLES)	|(#1 / #2) * 1000	|Stalls per kilo-cycle caused by frontend not having an instruction available for dispatch stage to issue.	|
|Stalls Backend PKC	|0x24 (STALL_BACKEND)	|0x11 (CPU_CYCLES)	|(#1 / #2) * 1000	|Stalls per kilo-cycle caused by backend preventing instruction dispatch from frontend due to ALUs IQ full, LSQ full, MCQ full.	|
|Core Mem BW	|0x37	| 	|(#1 * 64) / (sample period)	|Read demand memory bandwidth estimate (excludes writes, prefetch, tablewalks) in Bytes / s from a core.	|
|LLC MPKI	|0x37 (LLC_CACHE_MISS_RD)	|0x8 (INST_RETIRED)	|(#1 / #2) * 1000	|From the cores perspective, is the LLC operating well, infer if it should be increased	|
|BMPKI	|0x10 (BR_MIS_PRED)	|0x8 (INST_RETIRED)	|(#1 / #2) * 1000	|Branch Miss per Kilo Instruction, metric to understand if branch prediction logic is on average performing well or not. Branches exist every ~4 instructions, BMPKI > 10 is not good.	|
|L2C Inst MPKI	|0x108 (L2_REFILL_IFETCH)	|0x8	|(#1 / #2) * 1000	|Instruction fetch miss from L2 MPKI, infer if code size and fetch misses are stalling core	|
|L1C Inst MPKI	|0x1 (L1I_CACHE_REFILL)	|0x8	|(#1 / #2) * 1000	|Instruction fetch miss L1 MPKI, >20 is generally an indicator of code size pressure	|
|L2 MPKI	|0x17 (L2D_CACHE_REFILL)	|0x8	|(#1 / #2) * 1000	|L2 Cache overall MPKI,	|
|L1C Data MPKI	|0x4 (L1_DATA_REFILL)	|0x8	|(#1 / #2) * 1000	|L1 Data cache overall MPKI.	|
|Old Atomics failures	|0x6E (STREX_FAIL_SPEC)	|0x8	|(#1 / #2) * 1000	|PKI of store-exclusive failures, indicates software not using LSE in production.	|
|L2 TLB MPKI	|0x2D	|0x8	|(#1 / #2) *1000	|L2 TLB MPKI	|
|L1I TLB MPKI	|0x2	|0x8	|(#1 / #2) * 1000	|Instruction L1 TLB MPKI	|
|L1I Page Walk PKI	|0x35	|0x8	|(#1 / #2) * 1000	|Instruction PKI that requires a page-table walk	|
|L1D TLB MPKI	|0x5	|0x8	|(#1 / #2) * 1000	|Data L1 TLB MPKI	|
|L1D Page Walk PKI	|0x34	|0x8	|(#1 / #2) * 1000	|Data PKI that requires a page-table walk	|

## Load generators

There are many load generators out there, and most if not all allow for the same basic configurations such as number of simulated clients (or number of connections), number of outstanding requests, target throughput, programmable way to define request mix etc. Pick one that is easy to work with, offers the features needed, is extensible for creating the tests desired, and allows fine grained control over how load is generated. After finding the ideal load generator, it is also important to understand how the load generator creates load to avoid easy measurement mistakes. Load generators fall into two main types: closed and open loop.

### **Closed loop**

A closed loop load generator uses simple, synchronous IO calls for load generation in a similar fashion to below:
```C
void generate_load(socket_t sock)
{
   int wret, rret = 0;
   const char *msg = "GENERATE SOME LOAD";
   char *buf = (char *)malloc(128);
   do {
     wret = write(sock, msg, strlen(msg));
     rret = read(sock, buf, 128);
   } while(wret >= 0 && rret);
}
```

This code is simple, and load is increased by creating more threads and connections that sit in a tight loop making requests to the SUT (System Under Test).  Closed loop testers can also be implemented with event loops that multiplex sockets among a few threads, but allow only 1 outstanding request per socket, which requires more connections to drive more concurrent load.  The [Wrk](https://github.com/wg/wrk) load generator is an example of this. Some pitfalls with closed-loop testing:

1. Maximum load achievable is coupled to the observed round-trip network latency between the driver and the SUT, if one SUT is further away than another from the load generator, it will see less throughput with the same number of connections.
2. Not good for testing non-client facing services, like middle-layer web-caches, that leverage request pipelining on small number of connections.
3. Can quickly saturate the CPU on the load generator because high loads require many threads and/or connections.

Advantages of closed loop testers are: many to choose from, highly configurable and approximate client behavior well. 
Closed loop load generator suggestions (we highly recommend the Wrk2 load generator):

1. [Wrk2](https://github.com/giltene/wrk2)
2. [Wrk](https://github.com/wg/wrk)
3. [JMeter](https://jmeter.apache.org/)

### **Open loop**

Open-loop generators generate load in an asynchronous fashion. They use non-blocking IO to send requests onto a small set of connections regardless of whether a response was returned for the previous request or not. Since open-loop generators send requests regardless of responses received, they can approximate a greater variety of load scenarios because the sending side will send requests according to a specified time schedule (i.e. every 100us on average following an exponential distribution) instead of waiting until responses from the SUT before generating new requests. This allows an open-loop tester to load the SUT more completely and be less sensitive to latency of the network connection to the SUT. 

Some pitfalls of open-loop testing:

1. Not common
2. Less configurable
3. Can not be used with SUTs that only allow synchronous connections.  For instance, many DBMS engines like [Postgresql only allow a single command to be issued per connection](https://www.postgresql.org/docs/current/libpq-async.html).

Advantages of open loop testers are they are more accurate in measuring latency of an application than closed-loop testers.

Open loop load generator suggestions:

1. [Lancet](https://github.com/epfl-dcsl/lancet-tool), [Usenix paper](https://www.usenix.org/system/files/atc19-kogias-lancet.pdf)
2. [Mutilate](https://github.com/leverich/mutilate)
3. [MCPerf](https://github.com/shaygalon/memcache-perf)
4. [TRex](https://trex-tgn.cisco.com/) - This is for high performance stateless network testing

## eBPF (extended Berkley Packet Filter) — “Inspecting fine-grained code behavior” 

If you find a specific function that is mis-behaving, either putting the CPU to sleep more often, or taking longer to execute, but manual code inspection and flamegraphs are not yielding results, you can use eBPF to obtain detailed statistics on the function’s behavior. This can be leveraged for investigating reasons a function causes large latency spikes. Or measuring if it behaves differently on one machine compared to the other. These tools are useful for measuring a very specific issue, are extremely powerful and flexible. Warning: these tools can also have high overhead as they measure an event every time it happens compared to the sampling methods used in the previous sections.  If measuring something that happens millions of times a second, any injected eBPF will also run at that rate. 

1. Install the BCC tools
  ```bash
  # AL2 
  %> sudo `amazon-linux-extras enable BCC
  %> sudo yum install bcc
    
  # Ubuntu
  %> sudo apt-get install linux-headers-$(uname -r) bpfcc-tools`
  ```
2. Write an eBPF program in C that can be embedded in a python file
3. Run the eBPF program using the python to interface via the BCC tools and collect the statistics
4. Review the statistics and compare against the x86 SUT to compare.

Example eBPF programs can be found: https://github.com/iovisor/bcc.
