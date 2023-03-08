# Getting started with HPC workloads on Graviton instances
## Contents
* [Introduction](#introduction)
* [HPC Examples](examples)
  * [WRF](examples/wrf/wrf.md)
  * [GROMACS](examples/gromacs/gromacs.md)
  * [OpenFoam](examples/openfoam.md)
  * [Other HPC applications](examples/other_HPC_applications.md)
* [Dependent software and libraries](software/software.md)
  * [Parallel cluster](software/software.md#parallel-cluster)
  * [Compilers and recommended compiler options](software/software.md#compilers)
  * [openMPI](software/software.md#openmpi)
  * [Algebra FFT libraries for Arm64](software/software.md#math-libraries-for-arm64)
  * [Other software packages](software/software.md#other-software-packages)
* [MPI benchmarks and HPC proxies](benchmarks/benchmarks.md)
* [Additional resources](#additional-resources)

## Introduction
The performance of HPC applications heavily depends on compute, network and IO. The Graviton3E  based HPC7g instance has the right configuration to deliver the best performance for multi-node cluster HPC applications: 35% higher vector bandwidth (no power throttling), 200 Gbps of network bandwidth. For several most used HPC applications on cloud, we are able to achieve same results (correctness) as popular x86 instances, comparable performances and lower simulation costs. This document provides a walkthrough on how to install HPC softwares and obtain the best performance on Graviton EC2 instances. 

## Additional resources

