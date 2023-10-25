# Getting Started with Ampere CPUs Technical Guide

This repository provides technical guidance for users and developers using instances using Ampere Computing processors. While it calls out specific features of the Graviton processors themselves, this repository is also generally useful for anyone running code on Arm-based systems.

# Contents
* [Transitioning to Graviton](#transitioning-to-graviton)
* [Building for Graviton](#building-for-graviton-and-graviton2)
* [Optimizing for Graviton](optimizing.md)
* [Taking advantage of Arm Advanced SIMD instructions](SIMD_and_vectorization.md)
* [Recent software updates relevant to Graviton](#recent-software-updates-relevant-to-graviton)
* Language-specific considerations
	* [C/C++](c-c++.md)
	* [Go](golang.md)
	* [Java](java.md)
	* [.NET](dotnet.md)
	* [Python](python.md)
	* [Rust](rust.md)
* [Containers on Graviton](containers.md)
* [Headless website testing with Chrome and Puppeteer on Graviton](software/ChromeAndPuppeteer.md)
* [Lambda on Graviton](#lambda-on-graviton)
* [Operating Systems support](os.md)
* [Third-party Software Vendors](isv.md)
* [Finding and managing AMIs for Graviton, with AWS SystemManager or CloudFormation](amis_cf_sm.md)
* [DPDK, SPDK, and other datapath software](dpdk_spdk.md)
* [PyTorch](machinelearning/pytorch.md)
* [R](R.md)
* [TensorFlow](machinelearning/tensorflow.md)
* [Spark on Graviton](DataAnalytics.md)
* [Known issues and workarounds](#known-issues-and-workarounds)
* [AWS Managed Services available on Graviton](managed_services.md)
* [Graviton Performance Runbook](perfrunbook/graviton_perfrunbook.md)
* [Additional resources](#additional-resources)
* [How To Resources](howtoresources.md)

# Transitioning to Graviton
If you are new to Graviton and want to understand how to identify target workloads, how to plan a transition project, how to test your workloads on AWS Graviton and finally how deploy in production, please read [the key considerations to take into account when transitioning workloads to AWS Graviton based Amazon EC2 instances](transition-guide.md).

# Building for Graviton2, Graviton3 and Graviton3E

|Processor	|Graviton2	|Graviton3(E)	|
|---	|---	|---	|
|Instances	|[M6g/M6gd](https://aws.amazon.com/ec2/instance-types/m6g/), [C6g/C6gd/C6gn](https://aws.amazon.com/ec2/instance-types/c6g/), [R6g/R6gd](https://aws.amazon.com/ec2/instance-types/r6g/), [T4g](https://aws.amazon.com/ec2/instance-types/t4g), [X2gd](https://aws.amazon.com/ec2/instance-types/x2/), [G5g](https://aws.amazon.com/ec2/instance-types/g5g/), and [I4g/Im4gn/Is4gen](https://aws.amazon.com/ec2/instance-types/i4g/)	|[C7g/C7gd/C7gn](https://aws.amazon.com/ec2/instance-types/c7g/), [M7g/M7gd](https://aws.amazon.com/ec2/instance-types/m7g/), [R7g/R7gd](https://aws.amazon.com/ec2/instance-types/r7g/), and [HPC7g](https://aws.amazon.com/ec2/instance-types/)	|
|Core	|[Neoverse-N1](https://developer.arm.com/documentation/100616/0301)	|[Neoverse-V1](https://developer.arm.com/documentation/101427/latest/)	|
|Frequency	|2500MHz	|2600MHz	|
|Turbo supported	|No	|No	|
|Instruction latencies	|[Instruction Latencies](https://developer.arm.com/documentation/PJDOC-466751330-9707/r4p1/?lang=en)	|[Instruction Latencies](https://developer.arm.com/documentation/pjdoc466751330-9685/latest/)	|
|Interconnect	|CMN-600	|CMN-650	|
|Architecture revision	|ARMv8.2-a	|ARMv8.4-a	|
|Additional  features	|fp16, rcpc, dotprod, crypto	|sve, rng, bf16, int8, crypto	|
|Recommended -mcpu flag	|neoverse-n1	|neoverse-512tvb	|
|RNG Instructions	|No	|Yes	|
|SIMD instructions	|2x Neon 128bit vectors	|4x Neon 128bit vectors / 2x SVE 256bit	|
|LSE (atomic mem operations)	|yes	|yes	|
|Pointer Authentication	|no	|yes	|
|Cores	|64	|64	|
|L1 cache (per core)	|64KB inst / 64KB data	|64KB inst / 64KB data	|
|L2 cache (per core)	|1MB	|1MB	|
|LLC (shared)	|32MB	|32MB	|
|DRAM	|8x DDR4	|8x DDR5	|
|DDR Encryption	|yes	|yes	|

# Optimizing for Graviton
Please refer to [optimizing](optimizing.md) for general debugging and profiling information.  For detailed checklists on optimizing and debugging performance on Graviton, see our [performance runbook](perfrunbook/graviton_perfrunbook.md).

Different architectures and systems have differing capabilities, which means some tools you might be familiar with on one architecture don't have equivalent on AWS Graviton. Documented [Monitoring Tools](Monitoring_Tools_on_Graviton.md) with some of these utilities.

# Recent software updates relevant to Graviton
There is a huge amount of activity in the Arm software ecosystem and improvements are being
made on a daily basis. As a general rule later versions of compilers, language runtimes, and applications
should be used whenever possible. The table below includes known recent changes to popular
packages that improve performance (if you know of others please let us know).

Package | Version | Improvements
--------|:-:|-------------
bazel	| [3.4.1+](https://github.com/bazelbuild/bazel/releases) | Pre-built bazel binary for Graviton/Arm64. [See below](#bazel-on-linux) for installation.
Cassandra | 4.0+ | Supports running on Java/Corretto 11, improving overall performance
FFmpeg  |   5.1+  | Improved performance of libswscale by 50% with better NEON vectorization which improves the performance and scalability of FFmpeg multi-thread encoders. The changes are available in FFmpeg version 4.3, with further improvements to scaling and motion estimation available in 5.1. Additional improvements to both will be available in 5.2, which has not yet been released as of November 2022. For more information about FFmpeg on Graviton, read the blog post on AWS Open Source Blog, [Optimized Video Encoding with FFmpeg on AWS Graviton Processors](https://aws.amazon.com/blogs/opensource/optimized-video-encoding-with-ffmpeg-on-aws-graviton-processors/).
HAProxy  | 2.4+  | A [serious bug](https://github.com/haproxy/haproxy/issues/958) was fixed. Additionally, building with `CPU=armv81` improves HAProxy performance by 4x so please rebuild your code with this flag.
MariaDB | 10.4.14+ | Default build now uses -moutline-atomics, general correctness bugs for Graviton fixed.
mongodb | 4.2.15+ / 4.4.7+ / 5.0.0+ | Improved performance on graviton, especially for internal JS engine. LSE support added in [SERVER-56347](https://jira.mongodb.org/browse/SERVER-56347).
MySQL   | 8.0.23+ | Improved spinlock behavior, compiled with -moutline-atomics if compiler supports it.
PostgreSQL | 15+ | General scalability improvements plus additional [improvements to spin-locks specifically for Arm64](https://commitfest.postgresql.org/37/3527/)
.NET | [5+](https://dotnet.microsoft.com/download/dotnet/5.0) | [.NET 5 significantly improved performance for ARM64](https://devblogs.microsoft.com/dotnet/Arm64-performance-in-net-5/). Here's an associated [AWS Blog](https://aws.amazon.com/blogs/compute/powering-net-5-with-aws-graviton2-benchmark-results/) with some performance results. 
OpenH264 | [2.1.1+](https://github.com/cisco/openh264/releases/tag/v2.1.1) | Pre-built Cisco OpenH264 binary for Graviton/Arm64. 
PCRE2   | 10.34+  | Added NEON vectorization to PCRE's JIT to match first and pairs of characters. This may improve performance of matching by up to 8x. This fixed version of the library now is shipping with Ubuntu 20.04 and PHP 8.
PHP     | 7.4+    | PHP 7.4 includes a number of performance improvements that increase perf by up to 30%
pip     | 19.3+   | Enable installation of python wheel binaries on Graviton
PyTorch | 2.0+    | Optimize Inference latency and throughput on Graviton. [AWS DLCs and python wheels are available](machinelearning/pytorch.md).
ruby    | 3.0+ | Enable arm64 optimizations that improve performance by as much as 40%. These changes have also been back-ported to the Ruby shipping with AmazonLinux2, Fedora, and Ubuntu 20.04.
Spark | 3.0+ | Supports running on Java/Corretto 11, improving overall performance.
zlib    | 1.2.8+  | For the best performance on Graviton please use [zlib-cloudflare](https://github.com/cloudflare/zlib).

# Containers on Graviton
You can run Docker, Kubernetes, Amazon ECS, and Amazon EKS on Graviton. Amazon ECR supports multi-arch containers.
Please refer to [containers](containers.md) for information about running container-based workloads on Graviton.

# [Lambda on Graviton](/aws-lambda/README.md)
[AWS Lambda](https://aws.amazon.com/lambda/) now allows you to configure new and existing functions to run on Arm-based AWS Graviton2 processors in addition to x86-based functions. Using this processor architecture option allows you to get up to 34% better price performance. Duration charges are 20 percent lower than the current pricing for x86 with [millisecond granularity](https://aws.amazon.com/blogs/aws/new-for-aws-lambda-1ms-billing-granularity-adds-cost-savings/). This also applies to duration charges when using [Provisioned Concurrency](https://aws.amazon.com/blogs/aws/new-provisioned-concurrency-for-lambda-functions/). Compute [Savings Plans](https://aws.amazon.com/blogs/aws/savings-plan-update-save-up-to-17-on-your-lambda-workloads/) supports Lambda functions powered by Graviton2.

The [Lambda](/aws-lambda/README.md) page highlights some of the migration considerations and also provides some simple to deploy demos you can use to explore how to build and migrate to Lambda functions using Arm/Graviton2.

# Operating Systems

Please check [os.md](os.md) for more information about which operating system to run on Graviton based instances.

# Known issues and workarounds

## Postgres
Postgres performance can be heavily impacted by not using [LSE](https://github.com/aws/aws-graviton-getting-started/blob/main/c-c%2B%2B.md#large-system-extensions-lse).
Today, postgres binaries from distributions (e.g. Ubuntu) are not built with `-moutline-atomics` or `-march=armv8.2-a` which would enable LSE.  Note: Amazon RDS for PostgreSQL isn't impacted by this. 

In November 2021 PostgreSQL started to distribute Ubuntu 20.04 packages optimized with `-moutline-atomics`.
For Ubuntu 20.04, we recommend using the PostgreSQL PPA instead of the packages distributed by Ubuntu Focal.
Please follow [the instructions to set up the PostgreSQL PPA.](https://www.postgresql.org/download/linux/ubuntu/)

## Python installation on some Linux distros
The default installation of pip on some Linux distributions is old \(<19.3\) to install binary wheel packages released for Graviton.  To work around this, it is recommended to upgrade your pip installation using:
```
sudo python3 -m pip install --upgrade pip
```

## Bazel on Linux
The [Bazel build tool](https://www.bazel.build/) now releases a pre-built binary for arm64. As of October 2020, this is not available in their custom Debian repo, and Bazel does not officially provide an RPM. Instead, we recommend using the [Bazelisk installer](https://docs.bazel.build/versions/master/install-bazelisk.html), which will replace your `bazel` command and [keep bazel up to date](https://github.com/bazelbuild/bazelisk/blob/master/README.md).

Below is an example using the [latest Arm binary release of Bazelisk](https://github.com/bazelbuild/bazelisk/releases/latest) as of October 2020:
```
wget https://github.com/bazelbuild/bazelisk/releases/download/v1.7.1/bazelisk-linux-arm64
chmod +x bazelisk-linux-arm64
sudo mv bazelisk-linux-arm64 /usr/local/bin/bazel
bazel
```

Bazelisk itself should not require further updates, as its only purpose is to keep Bazel updated.

## zlib on Linux
Linux distributions, in general, use the original zlib without any optimizations. zlib-cloudflare has been updated to provide better and faster compression on Arm and x86. To use zlib-cloudflare:
```
git clone https://github.com/cloudflare/zlib.git
cd zlib
./configure --prefix=$HOME
make
make install
```
Make sure to have the full path to your lib at $HOME/lib in /etc/ld.so.conf and run ldconfig.

For users of OpenJDK, which is dynamically linked to the system zlib, you can set LD_LIBRARY_PATH to point to the directory where your newly built version of zlib-cloudflare is located or load that library with LD_PRELOAD.

You can check the libz that JDK is dynamically linked against with:
```
$ ldd /Java/jdk-11.0.8/lib/libzip.so | grep libz
libz.so.1 => /lib/x86_64-linux-gnu/libz.so.1 (0x00007ffff7783000)
```

Currently, users of Amazon Corretto cannot link against zlib-cloudflare.

# Additional resources

 * [AWS Graviton](https://aws.amazon.com/ec2/graviton/)
 * [Neoverse N1 Software Optimization Guide](https://developer.arm.com/documentation/pjdoc466751330-9707/latest)
 * [Armv8 reference manual](https://documentation-service.arm.com/static/60119835773bb020e3de6fee)
 * [Package repository search tool](https://pkgs.org/)

**Feedback?** ec2-arm-dev-feedback@amazon.com
