# Getting started with AWS Graviton

This repository is meant to help new users start using the Arm-based AWS Graviton and Graviton2 processors which power the latest generation of Amazon EC2 instances. While it calls out specific features of the Graviton processors themselves, this repository is also generically useful for anyone running code on Arm.

# Contents
* [Building for Graviton](#building-for-graviton-and-graviton2)
* [Optimizing for Graviton](optimizing.md)
* [Recent software updates relevant to Graviton](#recent-software-updates-relevant-to-graviton)
* Language-specific considerations
	* [C/C++](c-c++.md)
	* [Java](java.md)
	* [Python](python.md) 
* [Containers on Graviton](containers.md)
* [Known issues and workarounds](#known-issues-and-workarounds)
* [Additional resources](#additional-resources)

# Building for Graviton and Graviton2
The Graviton CPU (powering [A1](https://aws.amazon.com/ec2/instance-types/a1/) instances) supports Arm V8.0 and includes support for CRC and crypto extensions.

The Graviton2 CPU (powering [M6g](https://aws.amazon.com/ec2/instance-types/m6/)/[C6g](https://aws.amazon.com/ec2/instance-types/c6/)/[R6g](https://aws.amazon.com/ec2/instance-types/r6/) instances) uses the Neoverse-N1 core and supports Arm V8.2 plus several
other architectural extensions. In particular, Graviton2 supports the Large
System Extensions (LSE) which improve locking and synchronization performance
across large systems. In addition, it has support for fp16 and 8-bit dot
productions for machine learning, and relaxed consistency-processor consistent
(RCpc) memory ordering.

# Optimizing for Graviton
Please refer [here](optimizing.md) for debugging and profiling information.

# Recent software updates relevant to Graviton
There is a huge amount of activity in the Arm software ecosystem and improvements are being
made on a daily basis. As a general rule later versions of compilers and language runtimes
should be used whenever possible. The table below includes known recent changes to popular
packages that improve performance (if you know of others please let us know).

Package | Version | Improvements
--------|---------|-------------
PHP     | 7.4+    | PHP 7.4 includes a number of performance improvements that increase perf by up to 30%
PCRE2   | 10.34+  | Added NEON vectorization to PCRE's JIT to match first and pairs of characters. This may improve performance of matching by up to 8x. This fixed version of the library now is shipping with Ubuntu 20.04 and PHP 8.
ffmpeg  |   4.3+  | Improved performance of libswscale by 50% with better NEON vectorization which improves the performance and scalability of ffmpeg multi-thread encoders. The changes are available in FFMPEG version 4.3.

# Containers on Graviton
Please refer [here](containers.md) for information about running container-based workloads on Graviton.

# Known issues and workarounds
As of July 7th 2020, [Cassandra](https://cassandra.apache.org/) will fail to install [via Debian package](https://cassandra.apache.org/download/) on Graviton instances running Ubuntu or other Debian-based distros. (Full details in the [open JIRA ticket](https://issues.apache.org/jira/browse/CASSANDRA-15889).) The workaround is to specify `amd64` as the desired arch. Cassandra is not arch-specific, so the "amd64" package works normally:
```
deb [arch=amd64] https://downloads.apache.org/cassandra/debian 311x main
```

Note that Redhat variants like Amazon Linux 2 avoid this issue. In our out of box Cassandra performance testing (early July 2020), Amazon Linux 2 using [the Corretto 8 JDK](https://docs.aws.amazon.com/corretto/latest/corretto-8-ug/amazon-linux-install.html) outperformed Ubuntu 20.04 by up to 23%.

# Additional resources
Linaro and Arm maintain a tool ([Sandpiper](http://sandpiper.linaro.org/)) to
search for packages across multiple OSes and Docker official images. This can
be useful to see which versions of a package exist in distributions --
especially when there is a performance improvement in a particular version.

**Some specific resources:**
 * [AWS Graviton2](https://aws.amazon.com/ec2/graviton/)
 * [Neoverse N1 Software Optimization Guide](https://static.docs.arm.com/swog309707/a/Arm_Neoverse_N1_Software_Optimization_Guide.pdf?_ga=2.243116802.1800297234.1576266995-544296985.1575476490)
 * [Armv8 reference manual](https://static.docs.arm.com/ddi0487/ea/DDI0487E_a_armv8_arm.pdf?_ga=2.201302702.1800297234.1576266995-544296985.1575476490)

**Feedback?** ec2-arm-dev-feedback@amazon.com
