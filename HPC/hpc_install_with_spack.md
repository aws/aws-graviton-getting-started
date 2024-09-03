# Getting started with HPC on Graviton instances
- [Getting started with HPC on Graviton instances](#getting-started-with-hpc-on-graviton-instances)
  - [Introduction](#introduction)
  - [Summary of the recommended configuration](#summary-of-the-recommended-configuration)
  - [Instructions for setting up the HPC cluster for best performance](#instructions-for-setting-up-the-hpc-cluster-for-best-performance)
    - [Spack](#Spack)
    - [Compilers](#compilers)
    - [EFA support](#efa-support)
    - [Open MPI](#open-mpi)
  - [Running HPC applications](#running-hpc-applications)
    - [HPC packages](#hpc-packages)
    - [WRF](#wrf)
      - [Build WRF 4.5 with ACFL on Graviton](#build-wrf-45-with-acfl-on-graviton)
      - [Setup the runtime configuration, download and run the benchmark](#setup-the-runtime-configuration-download-and-run-the-benchmark)
      - [Build WPS 4.5 with ACFL on Graviton](#build-wps-45-with-acfl-on-graviton)
    - [OpenFOAM](#openfoam)
    - [Gromacs](#gromacs)
- [Compile instructions on an Ec2](setup-an-ec2-hpc-instance.md#compile-instructions-on-an-ec2)
- [MPI application profiling](#mpi-application-profiling)
  - [Appendix](#appendix)
    - [List of HPC compilers for Graviton](#list-of-hpc-compilers-for-graviton)
    - [Common HPC Applications on Graviton](#common-hpc-applications-on-graviton)

## Introduction
[C7gn/Hpc7g](https://aws.amazon.com/blogs/aws/new-amazon-ec2-instance-types-in-the-works-c7gn-r7iz-and-hpc7g) instances are the latest additions to Graviton based EC2 instances, optimized for network and compute intensive High-Performance Computing (HPC) applications. This document is aimed to help HPC users get the optimal performance on Graviton instances. It covers the recommended compilers, libraries, and runtime configurations for building and running HPC applications. Along with the recommended software configuration, the document also provides example scripts to get started with 3 widely used open-source HPC applications: Weather Research and Forecasting (WRF), Open Source Field Operation And Manipulation (OpenFOAM) and Gromacs.

## Summary of the recommended configuration
Instance type: C7gn and Hpc7g (Graviton3E processor, max 200 Gbps network bandwidth, 2 GB RAM/vCPU)

Cluster manager: AWS ParallelCluster
* Base AMI: aws-parallelcluster-3.5.1-ubuntu-2004-lts-hvm-arm64
* Operating System: Ubuntu 20.04 (The latest version supported by Parallel Cluster)
* Linux Kernel: 5.15 & later (for users intended to use custom AMIs)

ENA driver: version 2.8.3 & later (Enhanced networking)

EFA driver: version 1.23.0 & later ([docs.aws.amazon.coml#efa-start-enable](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start.html#efa-start-enable))

Compiler: Arm Compiler for Linux (ACfL) v23.04 & later ([see below for other compiler options](#list-of-hpc-compilers-for-graviton))

ArmPL: v23.04 & later (included in the ACfL compiler)

MPI: Open MPI v4.1.4 & later (the latest official release)

Storage: [FSx for Lustre](https://docs.aws.amazon.com/fsx/latest/LustreGuide/getting-started.html) for shared file system.  HPC instance types have limited EBS bandwidth, and using FSx for Lustre avoids a bottleneck at the headnode.

## Instructions for setting up the HPC cluster for best performance
We recommend using [AWS ParallelCluster](https://docs.aws.amazon.com/parallelcluster/latest/ug/what-is-aws-parallelcluster.html) (previously known as [CfnCluster](http://cfncluster.readthedocs.io)) to deploy and manage HPC clusters  on AWS EC2. AWS ParallelCluster 3.5.1 is a tool that can automatically set up the required compute resources, job scheduler, and shared filesystem commonly needed to run HPC applications. This section covers step-by-step instructions on how to set up or upgrade the tools and software packages to the recommended versions on a new ParallelCluster. Please refer to the individual sub-sections if you need to update certain software package on an existing cluster. For a new cluster setup, you can use [this template](scripts-setup/hpc7g-ubuntu2004-useast1.yaml) and replace the subnet, S3 bucket name for [custom action script](scripts-setup/install-gcc-11.sh), and ssh key information from your account to create a Ubuntu 20.04 cluster. The command to create a new cluster is
```
pcluster create-cluster --cluster-name test-cluster --cluster-configuration hpc7g-ubuntu2004-useast1.yaml
```
The cluster creation process takes about 10 minutes. You can find headNode information under the EC2 console page once the creation process is finished (see the image below). In the case that you have multiple headNodes under the account, you can go to instance summary and check `Instance profile arn` attribute to find out which one has a prefix matching the cluster-name you created.

![](images/headNode-info-ec2console.png)

Alternatively, you can also use `pcluster describe-cluster --cluster-name test-cluster` to find the instanceId of the headNode and `aws ec2 describe-instances --instance-ids <instanceId>` to find the public Ip.
```
{
  "creationTime": "2023-04-19T12:56:19.079Z",
  "headNode": {
    "launchTime": "2023-05-09T14:17:39.000Z",
    "instanceId": "i-01489594da7c76f77",
    "publicIpAddress": "3.227.12.112",
    "instanceType": "c7g.4xlarge",
    "state": "running",
    "privateIpAddress": "10.0.1.55"
  },
  "version": "3.5.1",
  ...
}
```

You can log in to the headNode in the same way as a regular EC2 instance. 

### Spack
Spack is a versatile package manager for HPC that simplifies installing and managing software. It streamlines setup, ensures consistency, and saves time in complex environments. In this tutorial, we will use Spack to install other HPC packages, so let's begin by setting it up.

Run the [spack setup script](scripts-setup-spack/0-install-spack.sh) with command `./scripts-setup-spack/0-install-spack.sh  --spack-branch v0.22.1` to install Spack on the shared storage, `/shared`. It is recommanded to installed a release version for greater stability and bug fixes. The command provided will install [spack v0.22.1]((https://github.com/spack/spack/releases/tag/v0.22.1)), which is the latest release as of July 2024. Alternatively, you can install Spack without specifying a branch to use the default develop branch, which includes more recent updates of the packages that Spack supports.

You will see below message at the end of installation if spack is installed and setup successfully.
```
*** Spack setup completed ***
```

### Compilers
Many HPC applications depend on compiler optimizations for better performance. We recommend using [Arm Compiler for Linux (ACfL)](https://developer.arm.com/Tools%20and%20Software/Arm%20Compiler%20for%20Linux) because it is tailored for HPC codes and comes with Arm Performance Libraries (ArmPL), which includes optimized BLAS, LAPACK, FFT and math libraries. Follow below spack commands to install the latest ACfL or run the installation script with command `./scripts-setup-spack/1-install-compilers.sh`.
```
spack install acfl
spack load acfl
spack compiler add --scope site
```
You will get [similar message like this](scripts-wrf-spack/acfl-success-message.txt) if ACfL installation is successful. To view all available compilers on the system, use the Spack commands `spack compilers` or `spack compiler list`. After installing ACfL, you should see it listed along with the version you installed.
```
==> Available compilers
-- arm ubuntu20.04-aarch64 --------------------------------------
arm@23.10
```

Please refer to [Appendix](#list-of-hpc-compilers-for-graviton) for a partial list of other HPC compilers with Graviton support.

### EFA support
C7gn/Hpc7g instances come with an EFA (Elastic Fabric Adapter) interface for low latency node to node communication that offers a peak bandwidth of 200Gbps. Getting the correct EFA driver is crucial for the performance of network intensive HPC applications.  AWS parallel cluster 3.5.1 comes with the latest EFA driver, that supports the EFA interface on C7gn and Hpc7g. If you prefer to stay with an existing cluster generated by earlier versions of AWS ParallelCluster, please follow the steps below to check the EFA driver version and [upgrade the driver](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/efa-start.html#efa-start-enable) if necessary.
```
# ssh into a compute instance after it is configured
fi_info -p efa

# Output on instances without the proper EFA driver
fi_getinfo: -61

# Output on instances with the proper EFA driver
provider: efa
    fabric: EFA-fe80::94:3dff:fe89:1b70
    domain: efa_0-rdm
    version: 2.0
    type: FI_EP_RDM
    protocol: FI_PROTO_EFA
```

### Open MPI
For applications that use the Message Passing Interface (MPI) to communicate, we recommend using Open MPI v4.1.4 or later for Graviton Instances. AWS Parallel cluster 3.5.1 provides the Open MPI libraries built with default GCC. For best performance, it is recommended to re-compile them with ACfL 23.04 or GCC-11 and later version. The following snippet provides instructions on how to build Open MPI 5.0.3 with latest version of ACfL with spack. 
```
spack install openmpi@5.0.3%arm~atomics+legacylaunchers fabrics=ofi schedulers=slurm
```

Very that OpenMPI is installed correctly:
```
spack load openmpi
mpirun --version

# Output
mpirun (Open MPI) 5.0.3
```

Alternatively, you can list all packages associated with Open MPI using the command `spack find -v openmpi`. To see a detailed list of all installed packages on the system, use the `spack find` command. Below is a sample output of the `spack find` command:
```
-- linux-ubuntu20.04-aarch64 / gcc@9.4.0 ------------------------
acfl@23.10  gcc-runtime@9.4.0  glibc@2.31

-- linux-ubuntu20.04-neoverse_v1 / arm@23.10 --------------------
autoconf@2.72        diffutils@3.7    gmake@4.4.1           libfabric@1.21.0   libtool@2.4.7   numactl@2.0.14  perl@5.38.0    slurm@23.11.7
automake@1.16.5      findutils@4.7.0  gnuconfig@2022-09-17  libiconv@1.17      libxml2@2.10.3  openmpi@5.0.3   pkgconf@2.2.0  util-macros@1.19.3
berkeley-db@18.1.40  gdbm@1.23        hwloc@2.9.1           libpciaccess@0.17  m4@1.4.19       openssh@8.2p1   pmix@5.0.1     xz@5.4.6
bzip2@1.0.8          glibc@2.31       libevent@2.1.12       libsigsegv@2.14    ncurses@6.5     openssl@1.1.1f  readline@8.2   zlib-ng@2.1.6
==> 35 installed packages
```

### Storage
Some HPC applications require significant amounts of file I/O, however HPC instance types (Graviton instances included) don't have local storage, and have limited EBS bandwidth and IOPS.  Relying on EBS on each node can cause surprise slow-downs when the instance runs out of EBS burst credits.  This is one reason we don't recommend using an Hpc7g (or any HPC instance type) for headnodes, since the headnode performs additional I/O as the scheduler, and often serves a home directory to the compute nodes.  For these reasons the following recommendations are made:
 - Use FSx for Lustre to serve data and configuration files to compute nodes.  FSx for Lustre file systems can be configured in a variety of sizes and throughputs to meet your specific needs.  See the SharedStorage section in the example [cluster configuration](scripts-setup/hpc7g-ubuntu2004-useast1.yaml).
 - Headnodes should be compute-optimized instances (such as C7gn or C7g), and sized with both compute needs and EBS/networking needs in mind.

## Running HPC applications
Once the HPC cluster is setup following the above steps, you can run the following sample HPC applications on Graviton and check their performance. If there are any challenges in running these sample applications on Graviton instances, please raise an issue on [aws-graviton-getting-started](https://github.com/aws/aws-graviton-getting-started) github page.

### HPC packages
Package   |	Version |	Build options	    | Run time configurations
----------|---------|-------------------|-------------
WRF (Weather Research & Forecasting)	| v4.5+	| ACfL	| 8 CPUs per rank
OpenFOAM (Computational Fluid Dynamics simulation)	| v2112+ |	ACfL	| 1 CPU per rank
Gromacs (Molecular Dynamics simulation) |	v2022.4+	| ACfL with SVE_SIMD option	| 1 CPU per rank

### WRF
The WRF model is one of the most used numerical weather prediction (NWP) systems. WRF is used extensively for research and real-time forecasting. Large amount of computation resources are required for each simulation, especially for high resolution simulations. We recommend using [WRF 4.5](https://github.com/wrf-model/WRF/releases#wrf-version-4.5) or any version later than this. 

The WRF Pre-Processing System (WPS) preapres a domain (region of the Earth) for input to WRF. We recommend using [WPS 4.5](https://github.com/wrf-model/WPS/releases/tag/v4.5).

#### Build WRF 4.5 with ACFL on Graviton
Run the following Spack command to install WRF 4.5. To install a different version, simply replace `wrf@4.5.0` with the desired version, such as `wrf@4.5.1`. You can also choose alternative compilers or customize related packages by adjusting the command. For more details on writing Spack commands, refer to the  [spack installation guide](https://spack-tutorial.readthedocs.io/en/latest/tutorial_basics.html) for more information about how to write spack commands.
```
$ spack install wrf@4.5.0%arm~adios2+pnetcdf build_type='dm+sm' ^openmpi~atomics+legacylaunchers fabrics=ofi schedulers=slurm
```

To compare the installation specifications, run the command spack spec wrf. The output for our configuration should resemble [this](scripts-wrf-spack/wrf-spec-message.txt). 

The `spack load` command sets environment variables such as `PATH` and `LD_LIBRARY_PATH` to ensure that the system can locate the wrf.exe executable and other related files. Therefore, to verify that WRF has been installed successfully, execute the following commands and you should be able to view the path to `wrf.exe`.
```
spack load wrf
which wrf.exe
```

#### Setup the runtime configuration, download and run the benchmark
WRF uses shared memory and distributed memory programming model. It is recommended to use 8 threads per rank and setting threads affinity to be "compact" to reduce communication overhead and achieve better performance. The following is [an example Slurm script](scripts-wrf/sbatch-wrf-v45-acfl.sh) that will download the WRF CONUS 12km model and run on a single Hpc7g instance with 8 ranks and 8 threads for each rank. You can submit the Slurm job by running this command `sbatch scripts-wrf-spack/sbatch-wrf-acfl-spack.sh`. At the end of the WRF log file from rank 0 (rsl.error.0000), you will see the following message if the job completes successfully.
```
Timing for main: time 2019-11-26_23:58:48 on domain   1:    0.44608 elapsed seconds
Timing for main: time 2019-11-27_00:00:00 on domain   1:    0.44637 elapsed seconds
 mediation_integrate.G         1242 DATASET=HISTORY
 mediation_integrate.G         1243  grid%id             1  grid%oid
            2
Timing for Writing wrfout_d01_2019-11-27_00:00:00 for domain        1:    5.47993 elapsed seconds
wrf: SUCCESS COMPLETE WRF
```

You can view WRF output model using [Nice DCV](https://aws.amazon.com/hpc/dcv/) and [Ncview](http://meteora.ucsd.edu/~pierce/ncview_home_page.html). Typically the elapsed time spent on the computing steps is used to measure the performance of the WRF simulation on a system.
```
num_compute_time_steps=$( grep "Timing for main" rsl.error.0000 | awk 'NR>1' | wc -l )
time_compute_steps=$( grep "Timing for main" rsl.error.0000 | awk 'NR>1' | awk '{ sum_comp += $9} END { print sum_comp }' )
echo $time_compute_steps
```

#### Build WPS 4.5 with ACFL on Graviton
Instructions to install WPS with spack is working in progress. Please visit [spack](https://packages.spack.io/package.html?name=wps) for more information or [this guide](README.md#build-wps-45-with-acfl-on-graviton) to install from sources.

### OpenFOAM
OpenFOAM is a free, open-source CFD software released and developed by OpenCFD Ltd since 2004. OpenFOAM has a large user base and is used for finite element analysis (FEA) in a wide variety of industries, including aerospace, automotive, chemical manufacturing, petroleum exploration, etc.

Instructions to install OpenFOAM with spack is working in progress. Please visit [spack](https://packages.spack.io/package.html?name=openfoam) for more information or [this guide](README.md#openfoam) to install from sources.

### Gromacs
Gromacs is a widely used molecular dynamics software package. Gromacs is a computation heavy software, and can get better performance with the modern processors' SIMD (single instruction multiple data) capabilities. We recommend using Gromacs 2022.4 or later releases because they implement performance critical routines using the SVE instruction set found on Hpc7g/C7gn.

Instructions to install Gromacs with spack is working in progress. Please visit [spack](https://packages.spack.io/package.html?name=gromacs) for more information or [this guide](README.md#gromacs) to install from sources.

## MPI application profiling
Ideally, as you add more resources, the runtime of HPC applications should reduce linearly. When scaling is sub-linear or worse, it is usually because of the non-optimal communication patterns. To debug these cases, open-source tools such as the [Tau Performance System](http://www.cs.uoregon.edu/research/tau/home.php), can generate profiling and tracing reports to help you locate the bottlenecks.

Instructions to install Tau Performance System with spack is working in progress. Please visit [spack](https://packages.spack.io/package.html?name=tau) for more information or [this guide](README.md#mpi-application-profiling) to install from sources.

## Appendix

### List of HPC compilers for Graviton
The table below has a list of HPC compilers and options that you can for Graviton instance:
Compiler | Minimum version	| Target: Graviton3 and up |	Enable OpenMP	| Fast Math
----------|---------|-------------------|-------------|-------- 
GCC	| 11	| -O3 -mcpu=neoverse-v1	| -fopenmp	| -ffast-math
CLang/LLVM |	14 | -O3 -mcpu=neoverse-512tvb	| -fopenmp	| -ffast-math
Arm Compiler for Linux |	23.04 |	-O3 -mcpu=neoverse-512tvb |	-fopenmp |	-ffast-math
Nvidia HPC SDK |	23.1	| -O3 -tp=neoverse-v1	| -mp |	-fast

### Common HPC Applications on Graviton
Below is a list of some common HPC applications that run on Graviton.
ISV                   | Application   | Release of support  | Additional Notes
----------------------|---------------|---------------------|-----------------
Ansys                 | Fluent        | v221                | [Graviton Applications (AWS)](https://aws.amazon.com/blogs/hpc/application-deep-dive-into-the-graviton3e-based-amazon-ec2-hpc7g-instance/)
Ansys                 | LS-Dyna       | 12.1                | [Graviton Applications (AWS)](https://aws.amazon.com/blogs/hpc/application-deep-dive-into-the-graviton3e-based-amazon-ec2-hpc7g-instance/), [ANYS Deployment (Rescale)](https://rescale.com/blog/rescale-automates-the-deployment-of-ansys-ls-dyna-and-ansys-fluent-workloads-on-amazon-ec2-hpc7g-instances/)
Ansys                 | RedHawk-SC    | 2023R1              | [Release Notes](https://www.ansys.com/content/dam/it-solutions/platform-support/arm-64-processor-support-announcement-january-2023.pdf)
Fritz Haber Institute | FHIaims       | 21.02               | [Quantum Chemistry (AWS)](https://aws.amazon.com/blogs/hpc/quantum-chemistry-calculation-on-aws/)
National Center for Atmospheric Research | WRF | WRFV4.5    | [Weather on Graviton (AWS)](https://aws.amazon.com/blogs/hpc/numerical-weather-prediction-on-aws-graviton2/), [WRF on Graviton2 (ARM)](https://community.arm.com/arm-community-blogs/b/high-performance-computing-blog/posts/assessing-aws-graviton2-for-running-wrf)
OpenFOAM Foundation / ESI | OpenFOAM  | OpenFOAM7           | [Getting Best Performance (AWS)](https://aws.amazon.com/blogs/hpc/getting-the-best-openfoam-performance-on-aws/), [Graviton Applications (AWS)](https://aws.amazon.com/blogs/hpc/application-deep-dive-into-the-graviton3e-based-amazon-ec2-hpc7g-instance/), [Instructions (AWS)](https://github.com/aws/aws-graviton-getting-started/tree/main/HPC#openfoam)
Sentieon              | DNAseq , TNseq, DNAscope | 202112.02 | [Release Notes](https://support.sentieon.com/manual/appendix/releasenotes/#release-202112-02), [Cost Effective Genomics (AWS)](https://aws.amazon.com/blogs/hpc/cost-effective-and-accurate-genomics-analysis-with-sentieon-on-aws/)
Siemens               | StarCCM++     | 2023.2              | [Release Notes](https://blogs.sw.siemens.com/simcenter/simcenter-star-ccm-2302-released/#section_3)
Université de Genève  | Palabos       | 2010                | [Lattice-Boltzmann Palabos (AWS)](https://aws.amazon.com/blogs/hpc/lattice-boltzmann-simulation-with-palabos-on-aws-using-graviton-based-amazon-ec2-hpc7g-instances/)
Altair Engineering  | OpenRadioss       | 20231204                | [Presentations-Aachen270623 - OpenRadioss](https://www.openradioss.org/presentations-aachen270623/?wvideo=3ox1rtpco8), [Instructions](https://openradioss.atlassian.net/wiki/spaces/OPENRADIOSS/pages/47546369/HPC+Benchmark+Models)
Électricité de France   | Code Saturne       | 8.0.2                | https://www.code-saturne.org/cms/web/documentation/Tutorials
