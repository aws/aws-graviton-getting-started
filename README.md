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
	* [Go](golang.md)
* [Containers on Graviton](containers.md)
* [Operating Systems support](os.md)
* [Finding and managing AMIs for Graviton, with AWS SystemManager or CloudFormation](amis_cf_sm.md)
* [DPDK, SPDK, and other datapath software](dpdk_spdk.md)
* [TensorFlow](tensorflow.md)
* [Known issues and workarounds](#known-issues-and-workarounds)
* [Additional resources](#additional-resources)

# Building for Graviton and Graviton2
The Graviton CPU (powering [A1](https://aws.amazon.com/ec2/instance-types/a1/) instances) supports Arm V8.0 and includes support for CRC and crypto extensions.

The Graviton2 CPU (powering [M6g/M6gd](https://aws.amazon.com/ec2/instance-types/m6/), [C6g/C6gd/C6gn](https://aws.amazon.com/ec2/instance-types/c6/), [R6g/R6gd](https://aws.amazon.com/ec2/instance-types/r6/), and [T4g](https://aws.amazon.com/ec2/instance-types/t4) instances) uses the Neoverse-N1 core and supports Arm V8.2 (include CRC and crypto extensions) plus several
other architectural extensions. In particular, Graviton2 supports the Large
System Extensions (LSE) which improve locking and synchronization performance
across large systems. In addition, it has support for fp16 and 8-bit dot
productions for machine learning, and relaxed consistency-processor consistent
(RCpc) memory ordering.

In addition, to make it easier to develop, test, and run your applications on T4g instances, all AWS customers are automatically enrolled in a free trial on the t4g.micro size. 
Starting September 2020 until December 31st 2020, you can run a t4g.micro instance and automatically get 750 free hours per month deducted from your bill, including any [CPU credits](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-performance-instances-unlimited-mode-concepts.html#unlimited-mode-surplus-credits) during the free 750 hours of usage.
 The 750 hours are calculated in aggregate across all regions. For details on terms and conditions of the free trial, please refer to the [EC2 FAQs](https://aws.amazon.com/ec2/faqs/).

# Optimizing for Graviton
Please refer [here](optimizing.md) for debugging and profiling information.

# Recent software updates relevant to Graviton
There is a huge amount of activity in the Arm software ecosystem and improvements are being
made on a daily basis. As a general rule later versions of compilers and language runtimes
should be used whenever possible. The table below includes known recent changes to popular
packages that improve performance (if you know of others please let us know).

Package | Version | Improvements
--------|---------|-------------
bazel	| [3.4.1+](https://github.com/bazelbuild/bazel/releases) | Pre-built bazel binary for Graviton/Arm64. [See below](#bazel-on-linux) for installation. 
ffmpeg  |   4.3+  | Improved performance of libswscale by 50% with better NEON vectorization which improves the performance and scalability of ffmpeg multi-thread encoders. The changes are available in FFMPEG version 4.3.
HAProxy  | 2.4+  | A [serious bug](https://github.com/haproxy/haproxy/issues/958) was fixed. Additionally, building with `-march=armv8.2-a` improves HAProxy performance by 4x so please rebuild your code with this flag.
OpenH264 | [2.1.1+](https://github.com/cisco/openh264/releases/tag/v2.1.1) | Pre-built Cisco OpenH264 binary for Graviton/Arm64. 
PCRE2   | 10.34+  | Added NEON vectorization to PCRE's JIT to match first and pairs of characters. This may improve performance of matching by up to 8x. This fixed version of the library now is shipping with Ubuntu 20.04 and PHP 8.
PHP     | 7.4+    | PHP 7.4 includes a number of performance improvements that increase perf by up to 30%
pip     | 19.3+   | Enable installation of python wheel binaries on Graviton
PyTorch | 1.7+    | Enable Arm64 compilation, Neon optimization for fp32. [Install from source](https://github.com/aws/aws-graviton-getting-started/blob/master/python.md#41-pytorch). **Note:** *Requires GCC9 or later for now. recommend to use Ubuntu 20.xx*
ruby    | 3.0+ | Enable arm64 optimizations that improve perfomance by as much as 40%. These changes have also been back-ported to the Ruby shipping with AmazonLinux2, Fedora, and Ubuntu 20.04.
zlib    | 1.2.8+  | For the best performance on Graviton2 please use [zlib-cloudflare](https://github.com/cloudflare/zlib).

# Containers on Graviton
You can run Docker, Kubernetes, Amazon ECS, and Amazon EKS on Graviton. Amazon ECR supports multi-arch containers.
Please refer [here](containers.md) for information about running container-based workloads on Graviton.

# Operating Systems

Please check [here](os.md) for more information about which operating system to run on Graviton based instances.

# Known issues and workarounds

## Python installation on some Linux distros
The default installation of pip on some Linux distributions is old \(<19.3\) to install binary wheel packages released for Graviton.  To work around this, it is recommended to upgrade your pip installation using:
```
sudo python3 -m pip install --upgrade pip
```

## Cassandra installation on Ubuntu or Debian-based distros
As of July 7th 2020, [Cassandra](https://cassandra.apache.org/) will fail to install [via Debian package](https://cassandra.apache.org/download/) on Graviton instances running Ubuntu or other Debian-based distros. (Full details in the [open JIRA ticket](https://issues.apache.org/jira/browse/CASSANDRA-15889).) The workaround is to specify `amd64` as the desired arch. Cassandra is not arch-specific, so the "amd64" package works normally:
```
deb [arch=amd64] https://downloads.apache.org/cassandra/debian 311x main
```

Note that Redhat variants like Amazon Linux 2 avoid this issue. In our out of box Cassandra performance testing (early July 2020), Amazon Linux 2 using [the Corretto 8 JDK](https://docs.aws.amazon.com/corretto/latest/corretto-8-ug/amazon-linux-install.html) outperformed Ubuntu 20.04 by up to 23%.

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
