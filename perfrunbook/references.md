# References

[Graviton Performance Runbook toplevel](./README.md)

Experimental design:

* [Your load generator is probably lying to you](http://highscalability.com/blog/2015/10/5/your-load-generator-is-probably-lying-to-you-take-the-red-pi.html)
* [NIST Engineering Statistics: Choosing an experimental design](https://www.itl.nist.gov/div898/handbook/pri/section3/pri3.htm)

Performance measurement tools:

* [Top-down performance analysis (Yasin, ISPASS 2014)](https://ieeexplore.ieee.org/document/6844459)
* [The PMCs of EC2: Measuring IPC (Brendan Gregg)](https://www.brendangregg.com/blog/2017-05-04/the-pmcs-of-ec2.html)
* [Brendan Gregg's homepage](http://www.brendangregg.com/overview.html)
* [Flamegraph homepage](https://github.com/brendangregg/FlameGraph)
* https://github.com/andikleen/pmu-tools
* [Netstat man-page](https://man7.org/linux/man-pages/man8/netstat.8.html)
* [Sar man-page](https://man7.org/linux/man-pages/man1/sar.1.html)
* [perf-stat man-page](https://man7.org/linux/man-pages/man1/perf-stat.1.html)
* [perf-record man-page](https://man7.org/linux/man-pages/man1/perf-record.1.html)
* [perf-annotate man-page](https://man7.org/linux/man-pages/man1/perf-annotate.1.html)

Optimization and tuning:

* [GCC online documentation](https://gcc.gnu.org/onlinedocs/)
* [Optimizing network intensive workloads on Graviton1](https://aws.amazon.com/blogs/compute/optimizing-network-intensive-workloads-on-amazon-ec2-a1-instances/)
* [Optimizing NGINX on Graviton1](https://aws.amazon.com/blogs/compute/optimizing-nginx-load-balancing-on-amazon-ec2-a1-instances/)
* [sysctl tunings](https://github.com/amazonlinux/autotune/blob/master/src/ec2sys_autotune/ec2_instance_network_cfg_gen.py#L63-L64)
* [AL2 auto-tuning](https://github.com/amazonlinux/autotune)

Hardware reference manuals:

* [Arm64 Architecture Reference Manual](https://developer.arm.com/documentation/102105/latest)
* [Neoverse N1 Technical Reference Manual](https://developer.arm.com/documentation/100616/0400/debug-descriptions/performance-monitor-unit/pmu-events)
* Reference for Intel CPU PMU counters (c5/m5/r5): [Intel 64 and IA-32 Architectures Software Developer's Manual](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html) (see Volume 3B, Performance Monitoring chapters)
* Reference for AMD CPU PMU counters (c5a): [Processor Programming Reference (PPR) for AMD Family 17h Model 71h, Revision B0 Processors Section 2.1.15](https://www.amd.com/system/files/TechDocs/56176_ppr_Family_17h_Model_71h_B0_pub_Rev_3.06.zip)

