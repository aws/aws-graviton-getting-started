# References

[Graviton Performance Runbook toplevel](./graviton_perfrunbook.md)

Experimental design:

* [Your load generator is probably lying to you](http://highscalability.com/blog/2015/10/5/your-load-generator-is-probably-lying-to-you-take-the-red-pi.html)
* [NIST Engineering Statistics: Choosing an experimental design](https://www.itl.nist.gov/div898/handbook/pri/section3/pri3.htm)

Performance measurement tools:

* [Top-down performance analysis](https://drive.google.com/file/d/0B_SDNxjh2Wbcc0lWemFNSGMzLTA/view)
* [Brendan Gregg's homepage](http://www.brendangregg.com/overview.html)
* [Flamegraph homepage](https://github.com/brendangregg/FlameGraph)
* https://github.com/andikleen/pmu-tools
* [Netstat man-page](https://linux.die.net/man/8/netstat)
* [Sar man-page](https://linux.die.net/man/1/sar)
* [perf-stat man-page](https://linux.die.net/man/1/perf-stat)
* [perf-record man-page](https://linux.die.net/man/1/perf-record)
* [perf-annotate man-page](https://linux.die.net/man/1/perf-annotate)

Optimization and tuning:

* [GCC10 manual](https://gcc.gnu.org/onlinedocs/gcc-10.2.0/gcc.pdf)
* [Optimizing network intensive workloads on Graviton1](https://aws.amazon.com/blogs/compute/optimizing-network-intensive-workloads-on-amazon-ec2-a1-instances/)
* [Optimizing NGINX on Graviton1](https://aws.amazon.com/blogs/compute/optimizing-nginx-load-balancing-on-amazon-ec2-a1-instances/)
* [sysctl tunings](https://github.com/amazonlinux/autotune/blob/master/src/ec2sys_autotune/ec2_instance_network_cfg_gen.py#L63-L64)
* [AL2 auto-tuning](https://github.com/amazonlinux/autotune)

Hardware reference manuals:

* [Arm64 Architecture Reference Manual](https://developer.arm.com/documentation/102105/latest)
* [Neoverse N1 Technical Reference Manual](https://developer.arm.com/documentation/100616/0400/debug-descriptions/performance-monitor-unit/pmu-events)
* Reference for Intel CPU PMU counters (c5/m5/r5): [Intel 64 and IA-32 Architecture Software Developer’s Manual, Volume 3B Chapter 19](https://software.intel.com/content/dam/develop/external/us/en/documents-tps/253669-sdm-vol-3b.pdf)
* Reference for AMD CPU PMU counters (c5a): [Processor Programming Reference (PPR) for AMD Family 17h Model 71h, Revision B0 Processors Section 2.1.15](https://www.amd.com/system/files/TechDocs/56176_ppr_Family_17h_Model_71h_B0_pub_Rev_3.06.zip)

