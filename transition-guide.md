# Considerations when transitioning workloads to AWS Graviton based Amazon EC2 instances

AWS Graviton processors power Amazon EC2 general purpose (M6g, M6gd, M7g, M7gd, T4g), compute optimized (C6g, C6gd, C6gn, C7g, C7gd, C7gn), memory optimized (R6g, R6gd, R7g, R7gd, X2gd) instances, storage optimized (I4g, Im4gn, Is4gen), HPC optimized (Hpc7g), and GPU-powered (G5g) instances that provide the best price-performance for a wide variety of Linux-based workloads. Examples include application servers, micro-services, high-performance computing, CPU-based machine learning inference, video encoding, electronic design automation, gaming, open-source databases, and in-memory caches. In most cases transitioning to AWS Graviton is as simple as updating your infrastructure-as-code to select the new instance type and associated Operating System (OS) Amazon Machine Image ([AMI](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/AMIs.html)). However, because AWS Graviton processors implement the Arm64 instruction set, there can be additional software implications. This transition guide provides a step-by-step approach to assess your workload to identify and address any potential software changes that might be needed.

## Introduction - identifying target workloads

The quickest and easiest workloads to transition are Linux-based, and built using open-source components or in-house applications where you control the source code. Many open source projects already support Arm64 and by extension Graviton, and having access to the source code allows you to build from source if pre-built artifacts do not already exist. There is also a large and growing set of Independent Software Vendor (ISV) software available for Graviton (a non-exhaustive list can be found [here](isv.md). However if you license software you’ll want to check with the respective ISV to ensure they already, or have plans to, support the Arm64 instruction set.

The following transition guide is organized into a logical sequence of steps as follows:

* [Learning and exploring](#learning-and-exploring)
    * Step 1 -  [Optional] Understand the Graviton Processor and review key documentation
    * Step 2 - Explore your workload, and inventory your current software stack
* [Plan your workload transition](#plan-your-workload-transition)
    * Step 3 - Install and configure your application environment
    * Step 4 - [Optional] Build your application(s) and/or container images
* [Test and optimize your workload](#test-and-optimize-your-workload)
    * Step 5 - Testing and optimizing your workload
    * Step 6 - Performance testing
* [Infrastructure and deployment](#infrastructure-and-deployment)
    * Step 7 - Update your infrastructure as code
    * Step 8 - Perform canary or Blue-Green deployment

### Learning and exploring

**Step 1 - [Optional] Understand the Graviton Processor and review key documentation**


1. [Optional] Start by watching [re:Invent 2020 - Deep dive on AWS Graviton2 processor-powered EC2 instances](https://youtu.be/NLysl0QvqXU) and [re:Invent 2021 - Deep dive into AWS Graviton3 and Amazon EC2 C7g instances](https://www.youtube.com/watch?v=WDKwwFQKfSI), which will give you an overview of the Graviton-based instances and some insights on how to run applications depending on their operating system, languages and runtimes.
2. [Optional] Keep on learning by watching [re:Invent 2021 - The journey of silicon innovation at AWS]([https://www.youtube.com/watch?v=Yv3B_Zey83Y](https://www.youtube.com/watch?v=2DCAtpeBABY)to better understand Amazon long-term commitment to innovate with custom silicon.
3. Get familiar with the rest of this [Getting started with AWS Graviton repository](README.md) which will act as a useful reference throughout your workload transition.


**Step 2 -  Explore your workload, and inventory your current software stack**

Before starting the transition, you will need to inventory your current software stack so you can identify the path to equivalent software versions that support Graviton. At this stage it can be useful to think in terms of software you download (e.g. open source packages, container images, libraries), software you build and software you procure/license (e.g. monitoring or security agents). Areas to review:

* [Operating system](os.md), pay attention to specific versions that support Graviton (usually more recent are better)
* If your workload is container based, check container images you consume for Arm64 support. Keep in mind many container images now support multiple architectures which simplifies consumption of those images in a mixed-architecture environment. See the [ECR multi-arch support announcement](https://aws.amazon.com/blogs/containers/introducing-multi-architecture-container-images-for-amazon-ecr/) for more details on multi-arch images.
* All the libraries, frameworks and runtimes used by the application.
* Tools used to build, deploy and test your application (e.g. compilers, test suites, CI/CD pipelines, provisioning tools and scripts). Note there are language specific sections in the getting started guide with useful pointers to getting the best performance from Graviton processors.
* Tools and/or agents used to deploy and manage the application in production (e.g. monitoring tools or security agents)
* The [Porting Advisor for Graviton](https://github.com/aws/porting-advisor-for-graviton) is an open-source command line tool that analyzes source code and generates a report highlighting missing and outdated libraries and code constructs that may require modification along with recommendations for alternatives. It accelerates your transition to AWS Graviton-based instances by reducing the iterative process of identifying and resolving source code and library dependencies
* This guide contains language specifics sections where you'll find additional per-language guidance:
  * [C/C++](c-c++.md)
  * [Go](golang.md)
  * [Java](java.md)
  * [.NET](dotnet.md) 
  * [Python](python.md)
  * [Rust](rust.md)

As a rule the more current your software environment the more likely you will obtain the full performance entitlement from Graviton.

For each component of your software stack, check for Arm64/Graviton support. A large portion of this can be done using existing configuration scripts, as your scripts run and install packages you will get messages for any missing components, some may build from source automatically while others will cause the script to fail. Pay attention to software versions as in general the more current your software is the easier the transition, and the more likely you’ll achieve the full performance entitlement from Graviton processors. If you do need to perform upgrades prior to adopting Graviton then it is best to do that using an existing x86 environment to minimize the number of changed variables. We have seen examples where upgrading OS version on x86 was far more involved and time consuming than transitioning to Graviton after the upgrade. For more details on checking for software support please see Appendix A.

Note: When locating software be aware that some tools, including  GCC, refer to the architecture as AArch64, others including the Linux Kernel, call it arm64. When checking packages across various repositories, you’ll find those different naming conventions.

### Plan your workload transition

**Step 3-  Install and configure your application environment**

To transition and test your application, you will need a suitable Graviton environment. Depending on your execution environment, you may need to:

* Obtain or create an Arm64 AMI to boot your Graviton instance(s) from. Depending on how you manage your AMIs, you can either start directly from an existing reference AMI for Arm64, or you can build a Golden AMI with your specific dependencies from one of the reference images (see [here](os.md) for a full list of supported OS’ with AMI links) ;
* If you operate a container based environment, you’ll need to build or extend an existing cluster with support for Graviton based instances. Both Amazon ECS and EKS support adding Graviton-based instances to an existing x86-based cluster. For ECS, you can add Graviton-based instances to your ECS cluster, launching them with either the [AWS ECS-optimized AMI for arm64](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-optimized_AMI.html) or your own AMI after you’ve installed the ECS agent. For EKS, you will need to create a node-group with Graviton-based instances launched with the [EKS optimized AMI for arm64](https://docs.aws.amazon.com/eks/latest/userguide/eks-optimized-ami.html).
    * Note: you can support Graviton and x86 instances in the same Auto Scaling Group, this [blog](https://aws.amazon.com/blogs/compute/supporting-aws-graviton2-and-x86-instance-types-in-the-same-auto-scaling-group/) details the process using the launch template override feature.
* Complete the installation of your software stack based on the inventory created in step 2.
    * Note: In many cases your installation scripts can be used as-is or with minor modifications to reference architecture specific versions of components where necessary. The first time through this may be an iterative process as you resolve any remaining dependencies. 


**Step 4 - [Optional] Build your application(s) and/or container images**

Note: If you are not building your application or component parts of your overall application stack you may skip this step.

For applications built using interpreted or JIT’d languages, including Java, PHP or Node.js, they should run as-is or with only minor modifications. The repository contains language specific sections with recommendations, for example [Java](java.md), [Python](python.md), [C/C++](c-c++.md), [Golang](golang.md), [Rust](rust.md) or [.Net](dotnet.md). Note: if there is no language specific section, it is because there is no specific guidance beyond using a suitably current version of the language as documented [here](README.md#recent-software-updates-relevant-to-graviton) (e.g. PHP Version 7.4+). .NET-core is a great way to benefit from Graviton-based instances, this [blog post](https://aws.amazon.com/blogs/compute/powering-net-5-with-aws-graviton2-benchmark-results/) covers .NET5 performance.

Applications using compiled languages including C, C++ or Go, need to be compiled for the Arm64 architecture. Most modern builds (e.g. using Make) will just work when run natively on Graviton-based instances, however, you’ll find language specific compiler recommendations in this repository: [C/C++](c-c++.md), [Go](golang.md), and [Rust](rust.md).

Just like an operating system, container images are architecture specific. You will need to build arm64 container image(s), to make the transition easier we recommend building multi-arch container image(s) that can run automatically on either x86-64 or arm64. Check out the [container section](containers.md) of this repository for more details and this [blog post](https://aws.amazon.com/blogs/containers/introducing-multi-architecture-container-images-for-amazon-ecr/) provides a detailed overview of multi-architecture container image support, which is considered a best practice for establishing and maintaining a multi-architecture environment.

You will also need to review any functional and unit test suite(s) to ensure you can test the new build artifacts with the same test coverage you have already for x86 artifacts.

### Test and optimize your workload

**Step 5 - Testing and optimizing your workload**

Now that you have your application stack on Graviton, you should run your test suite to ensure all regular unit and functional tests pass. Resolve any test failures in the application(s) or test suites until you are satisfied everything is working as expected. Most errors should be related to the modifications and updated software versions you have installed during the transition (tip: when upgrading software versions first test them using an existing x86 environment to minimize the number of variables changed at a time. If issues occur then resolve them using the current x86 environment before continuing with the new Graviton environment). If you suspect architecture specific issue(s) please have a look to our [C/C++ section ](c-c++.md) which documents them and give advice on how to solve them. If there are still details that seem unclear, please reach out to your AWS account team, or to the AWS support for assistance.

**Step 6 - Performance testing**

With your fully functional application, it is time to establish a performance baseline on Graviton. In many cases, Graviton will provide performance and/or capacity improvements over x86-based instances.

One of the major differences between AWS Graviton instances and other Amazon EC2 instances is their vCPU-to-physical-core mappings. Every vCPU on a Graviton processor maps to a physical core, and there is no Simultaneous Multi-Threading (SMT). Consequently, Graviton provides better linear performance scalability in most cases. When comparing to existing x86 instances, we recommend fully loading both instance types to determine the maximum sustainable load before the latency or error rate exceeds acceptable bounds. For horizontally-scalable, multi-threaded workloads that are CPU bound, you may find that the Graviton instances are able to sustain a significantly higher transaction rate before unacceptable latencies or error rates occur.

During the transition to Graviton, if you are using Amazon EC2 Auto Scaling, you may be able to increase the threshold values for the CloudWatch alarms that invoke the scaling process. This may reduce the number of EC2 instances now needed to serve a given level of demand.

Important: This repository has sections dedicated to [Optimization](optimizing.md) and a [Performance Runbook](perfrunbook/README.md) for you to follow during this stage.

If after reading the documentation in this repository and following the recommendations you do not observe expected performance then please reach out to your AWS account team, or send email to [ec2-arm-dev-feedback@amazon.com](mailto:ec2-arm-dev-feedback@amazon.com) with details so we can assist you with your performance observations.


### Infrastructure and deployment

**Step 7 - Update your infrastructure as code**

Now you have a tested and performant application, its time to update your infrastructure as code to add support for Graviton-based instances. This typically includes updating instance types, AMI IDs, ASG constructs to support multi-architecture (see [Amazon EC2 ASG support for multiple Launch Templates](https://aws.amazon.com/about-aws/whats-new/2020/11/amazon-ec2-auto-scaling-announces-support-for-multiple-launch-templates-for-auto-scaling-groups/)), and finally deploying or redeploying your infrastructure.

**Step 8 - Perform canary or Blue-Green deployment**

Once your infrastructure is ready to support Graviton-based instances, you can start a Canary or Blue-Green deployment to re-direct a portion of application traffic to the Graviton-based instances. Ideally initial tests will run in a development environment to load test with production traffic patterns. Monitor the application closely to ensure expected behavior. Once your application is running as expected on Graviton you can define and execute your transition strategy and begin to enjoy the benefits of increased price-performance.


### _Appendix A - locating packages for Arm64/Graviton_

Remember: When locating software be aware that some tools, including  GCC, refer to the architecture as AArch64, others including the Linux Kernel, call it arm64. When checking packages across various repositories, you’ll find those different naming conventions, and in some cases just “ARM”.

The main ways to check and places to look for will be:

* Package repositories of your chosen Linux distribution(s). Arm64 support within Linux distributions is largely complete: for example, Debian, which has the largest package repository, has over 98% of its packages built for the arm64 architecture.
* Container image registry. Amazon ECR now offers [public repositories](https://docs.aws.amazon.com/AmazonECR/latest/public/public-repositories.html) that you can search for [arm64 images](https://gallery.ecr.aws/?architectures=ARM+64&page=1). DockerHub allows you to search for a specific architecture ([e.g. arm64](https://hub.docker.com/search?type=image&architecture=arm64)).
    * Note: Specific to containers you may find an amd64 (x86-64) container image you currently use transitioned to a multi-architecture container image when adding Arm64 support. This means you may not find an explicit Arm64 container, so be sure to check for both as projects may chose to vend discrete images for x86-64 and Arm64 while other projects chose to vend a multi-arch image supporting both architectures.
* On GitHub, you can check for arm64 versions in the release section. However, some projects don’t use the release section, or only release source archives, so you may need to visit the main project webpage and check the download section. You can also search the GitHub project for “arm64” or “AArch64” to see whether the project has any arm64 code contributions or issues. Even if a project does not currently produce builds for arm64, in many cases an Arm64 version of those packages will be available through Linux distributions or additional package repositories (e.g. [EPEL](https://aws.amazon.com/premiumsupport/knowledge-center/ec2-enable-epel/)). You can search for packages using a package search tool such as [pkgs.org](https://pkgs.org/).
* The download section or platform support matrix of your software vendors, look for references to Arm64, AArch64 or Graviton.

Categories of software with potential issues:

* Packages or applications sourced from an ISV may not yet be available for Graviton. AWS is working with lots of software partners to offer technical guidance as they add support for Graviton, but some are still missing or in the process of adding support. A non-exhaustive list of some ISV software can be found in [here](isv.md).
* The Python community vend lots of modules built using low level languages (e.g. C/C++) that need to be compiled for the Arm64 architecture. You may use modules that are not currently available as pre-built binaries from the Python Package Index. AWS is actively working with open-source communities to ensure the most popular modules are available. In the meantime we provide specific instructions to resolve the build-time dependencies for missing packages in the [Python section](python.md#1-installing-python-packages) of the Graviton Getting Started Guide.


If you find other software lacking support for Arm64, please let your AWS team know, or send email to [ec2-arm-dev-feedback@amazon.com](mailto:ec2-arm-dev-feedback@amazon.com).
