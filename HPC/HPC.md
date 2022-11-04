# Getting started with HPC workloads on parallel clusters using Graviton CPUs

**Introduction**

This document describes how to get started running HPC applications on parallel clusters using Graviton EC2 instances.

**How to get started running HPC workload on Graviton CPUs** 

First, follow the instructions here to setup a parallel cluster - https://docs.aws.amazon.com/parallelcluster/latest/ug/install-v3-configuring.html. OpenMPI is the default MPI and already installed on AWS parallel cluster. For compilers, Arm Compiler For Linux (ACFL) and Gcc 10.2 or later are recommended for better auto-vectorization. Arm performance libraries (ArmPL) includes a dense and sparse linear algebra library, fft library and optimized math library that can also improve the throughput of HPC applications.  The arm compiler and libraries can be downloaded at https://developer.arm.com/downloads/-/arm-compiler-for-linux. 

**Install ACFL and Armpl**

Environment modules and a few others are required for ACFL and ArmPL, to install them 
- on Ubuntu
```
sudo apt update
sudo apt install libc6-dev
sudo apt install environment-modules
```
- on Amazon Linux
```
sudo yum update -y
sudo yum groupinstall "Development Tools"
sudo yum install environment-modules
sudo yum install ncurses-compat-libs.aarch64
```

To install the Arm packages, fetch the version corresponding to your os and  
- on Ubuntu 20.04
```
tar xf arm-compiler-for-linux_22.1_Ubuntu-20.04_aarch64.tar 
cd arm-compiler-for-linux_22.1_Ubuntu-20.04/
sudo ./arm-compiler-for-linux_22.1_Ubuntu-20.04.sh -i $INSTALLDIR
tar xf arm-performance-libraries_22.1_Ubuntu-20.04_gcc-10.2.tar 
cd arm-performance-libraries_22.1_Ubuntu-20.04/
sudo ./arm-performance-libraries_22.1_Ubuntu-20.04.sh 
```
- on Amazon Linux
```
tar xf arm-compiler-for-linux_22.1_RHEL-7_aarch64.tar 
cd arm-compiler-for-linux_22.1_RHEL-7/
sudo ./arm-compiler-for-linux_22.1_RHEL-7.sh/
tar xf arm-performance-libraries_22.1_RHEL-7_gcc-10.2.tar
cd arm-performance-libraries_22.1_RHEL-7/
sudo ./arm-performance-libraries_22.1_RHEL-7.sh 
```

Put the follow in the shell file to set up module path
```
source /etc/profile.d/modules.sh
export MODULEPATH=$MODULEPATH:$INSTALLDIR/modulefiles
```

To check installed packages and use the packages
```
module av
module load acfl armpl
```

**One simple example - HPCCG** 

- clone the HPCCG code with arm64 support:
```
git clone https://github.com/Mantevo/HPCCG.git
cd HPCCG/
git pull origin pull/3/head
```
- The recommended flags for compilation is "-Ofast -mcpu=native". 
Or you can use the presets defined in the config file.  
```
make COMPILER=arm LIBRARY=armpl (use armclang and armPL)
make COMPILER=gnu LIBRARY=none (use gcc and no external library)
```
- to run the benchmark
```
mpirun -np num_ranks test_HPCCG nx ny nz
```

The benchmark will report the throughput of dominate floating point functions and MPI overhead.