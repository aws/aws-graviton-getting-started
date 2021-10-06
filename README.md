# Getting started with AWS Graviton

This repository is meant to help new users start using the Arm-based AWS Graviton and Graviton2 processors which power the latest generation of Amazon EC2 instances. While it calls out specific features of the Graviton processors themselves, this repository is also generically useful for anyone running code on Arm.

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
* [Operating Systems support](os.md)
* [Third-party Software Vendors](isv.md)
* [Finding and managing AMIs for Graviton, with AWS SystemManager or CloudFormation](amis_cf_sm.md)
* [DPDK, SPDK, and other datapath software](dpdk_spdk.md)
* [TensorFlow](tensorflow.md)
* [Known issues and workarounds](#known-issues-and-workarounds)
* [AWS Managed Services available on Graviton](managed_services.md)
* [Graviton Performance Runbook](perfrunbook/graviton_perfrunbook.md)
* [Additional resources](#additional-resources)

# Transitioning to Graviton
If you are new to Graviton and want to understand how to identify target workloads, how to plan a transition project, how to test your workloads on AWS Graviton2 and finally how deploy in production, please read [the key considerations to take into account when transitioning workloads to AWS Graviton2 based Amazon EC2 instances](transition-guide.md)

# Building for Graviton and Graviton2
The Graviton CPU (powering [A1](https://aws.amazon.com/ec2/instance-types/a1/) instances) supports Arm V8.0 and includes support for CRC and crypto extensions.

The Graviton2 CPU (powering [M6g/M6gd](https://aws.amazon.com/ec2/instance-types/m6/), [C6g/C6gd/C6gn](https://aws.amazon.com/ec2/instance-types/c6/), [R6g/R6gd](https://aws.amazon.com/ec2/instance-types/r6/), [T4g](https://aws.amazon.com/ec2/instance-types/t4), and [X2gd](https://aws.amazon.com/ec2/instance-types/x2/) instances) uses the Neoverse-N1 core and supports Arm V8.2 (include CRC and crypto extensions) plus several
other architectural extensions. In particular, Graviton2 supports the Large
System Extensions (LSE) which improve locking and synchronization performance
across large systems. In addition, it has support for fp16 and 8-bit dot
product for machine learning, and relaxed consistency-processor consistent
(RCpc) memory ordering.

In addition, to make it easier to develop, test, and run your applications on T4g instances, all AWS customers are automatically enrolled in a free trial on the t4g.micro size. 
Starting September 2020 until December 31, 2021, you can run a t4g.micro instance and automatically get 750 free hours per month deducted from your bill, including any [CPU credits](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-unlimited-mode-concepts.html#unlimited-mode-surplus-credits) during the free 750 hours of usage.
 The 750 hours are calculated in aggregate across all regions. For details on terms and conditions of the free trial, please refer to the [EC2 FAQs](https://aws.amazon.com/ec2/faqs/).

# Optimizing for Graviton
Please refer [here](optimizing.md) for general debugging and profiling information.  For detailed checklists on optimizing and debugging performance on Graviton, see our [performance runbook](perfrunbook/graviton_perfrunbook.md).

# Recent software updates relevant to Graviton
There is a huge amount of activity in the Arm software ecosystem and improvements are being
made on a daily basis. As a general rule later versions of compilers and language runtimes
should be used whenever possible. The table below includes known recent changes to popular
packages that improve performance (if you know of others please let us know).

Package | Version | Improvements
--------|:-:|-------------
bazel	| [3.4.1+](https://github.com/bazelbuild/bazel/releases) | Pre-built bazel binary for Graviton/Arm64. [See below](#bazel-on-linux) for installation. 
ffmpeg  |   4.3+  | Improved performance of libswscale by 50% with better NEON vectorization which improves the performance and scalability of ffmpeg multi-thread encoders. The changes are available in FFMPEG version 4.3.
HAProxy  | 2.4+  | A [serious bug](https://github.com/haproxy/haproxy/issues/958) was fixed. Additionally, building with `CPU=armv81` improves HAProxy performance by 4x so please rebuild your code with this flag.
mongodb | 4.2.15+ / 4.4.7+ / 5.0.0+ | Improved performance on graviton, especially for internal JS engine. LSE support added in [SERVER-56347](https://jira.mongodb.org/browse/SERVER-56347).
MySQL   | 8.0.23+ | Improved spinlock behavior, compiled with -moutline-atomics if compiler supports it.
.NET | [5+](https://dotnet.microsoft.com/download/dotnet/5.0) | [.NET 5 significantly improved performance for ARM64](https://devblogs.microsoft.com/dotnet/Arm64-performance-in-net-5/). Here's an associated [AWS Blog](https://aws.amazon.com/blogs/compute/powering-net-5-with-aws-graviton2-benchmark-results/) with some performance results. 
OpenH264 | [2.1.1+](https://github.com/cisco/openh264/releases/tag/v2.1.1) | Pre-built Cisco OpenH264 binary for Graviton/Arm64. 
PCRE2   | 10.34+  | Added NEON vectorization to PCRE's JIT to match first and pairs of characters. This may improve performance of matching by up to 8x. This fixed version of the library now is shipping with Ubuntu 20.04 and PHP 8.
PHP     | 7.4+    | PHP 7.4 includes a number of performance improvements that increase perf by up to 30%
pip     | 19.3+   | Enable installation of python wheel binaries on Graviton
PyTorch | 1.7+    | Enable Arm64 compilation, Neon optimization for fp32. [Install from source](https://github.com/aws/aws-graviton-getting-started/blob/master/python.md#41-pytorch). **Note:** *Requires GCC9 or later for now. recommend to use Ubuntu 20.xx*
ruby    | 3.0+ | Enable arm64 optimizations that improve performance by as much as 40%. These changes have also been back-ported to the Ruby shipping with AmazonLinux2, Fedora, and Ubuntu 20.04.
zlib    | 1.2.8+  | For the best performance on Graviton2 please use [zlib-cloudflare](https://github.com/cloudflare/zlib).

# Containers on Graviton
You can run Docker, Kubernetes, Amazon ECS, and Amazon EKS on Graviton. Amazon ECR supports multi-arch containers.
Please refer [here](containers.md) for information about running container-based workloads on Graviton.

# Operating Systems

Please check [here](os.md) for more information about which operating system to run on Graviton based instances.

# Known issues and workarounds

## Postgres
Postgres performance can be heavily impacted by not using [LSE](https://github.com/aws/aws-graviton-getting-started/blob/main/c-c%2B%2B.md#large-system-extensions-lse).
Today, postgres binaries from distributions (e.g. Ubuntu) are not built with `-moutline-atomics` or `-march=armv8.2-a` which would enable LSE. If you're planning to use
postgres in production, please rebuild it with flags to enable LSE. Note: Amazon RDS for PostgreSQL isn't impacted by this. 

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

 * [AWS Graviton2](https://aws.amazon.com/ec2/graviton/)
 * [Neoverse N1 Software Optimization Guide](https://documentation-service.arm.com/static/5f05e93dcafe527e86f61acd)
 * [Armv8 reference manual](https://documentation-service.arm.com/static/60119835773bb020e3de6fee)
 * [Package repository search tool](https://pkgs.org/)

**Feedback?** ec2-arm-dev-feedback@amazon.com
