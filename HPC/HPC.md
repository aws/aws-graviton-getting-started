# Getting started with HPC workloads on parallel clusters using Graviton CPUs

**Introduction**

This document describes how to get started running HPC applications on parallel clusters using Graviton EC2 instances.

**How to get started running HPC workload on Graviton CPUs**
First, follow the instructions here to setup a parallel cluster - https://docs.aws.amazon.com/parallelcluster/latest/ug/install-v3-configuring.html. OpenMPI is the default MPI and already installed on AWS parallel cluster. For compilers, arm compiler for linux and gcc 10.2 or later are recommended for better auto-vectorization. Arm performance library includes a dense and sparse linear algebra library, fft library and optimized math library that can also improve the throughput of HPC applications.  The arm compiler and library can be downloaded at https://developer.arm.com/downloads/-/arm-compiler-for-linux. 

**One simple example - HPCCG** 
- fetch the HPCCG code with arm64 support (from fork until PR is accepted): https://github.com/juntangc/HPCCG.

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