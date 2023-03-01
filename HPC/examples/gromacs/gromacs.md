## Gromacs
[Gromacs](https://www.gromacs.org/) is a free and open-source software suite for high-performance molecular dynamics and output analysis. Gromacs divies the interactions between molecules into short-range interactions and long-range interactions. The long-range interactions is using 3D FFT (requires all-to-all commnication) to calculate electrical field. For this reason, both computation and MPI are key to Gromacs performance. Another issue is load-balancing - not all ranks are doing the same tasks (roughly 75% of total ranks are for short range force and 25% for long-range computation, PME module).

## Gromacs benchmarks
There are three benchmarks published by [Max Planck Institude](https://www.mpinat.mpg.de/grubmueller/bench) for Gromacs
  * [benchMEM (82k atoms)](https://www.mpinat.mpg.de/benchMEM)
  * [benchRIB (2M atoms)](https://www.mpinat.mpg.de/benchRIB)
  * [benchPEP (12M atoms)](https://www.mpinat.mpg.de/benchPEP)

## Compile and run Gromacs on Graviton 
  * install cmake, [GCC](../../software/software.md#gcc), [openmpi](../../software/software.md#openmpi), binutils and [ARMPL](../../software/software.md#install-armpl)
  * configure and compile Gromacs with sve
```
#!/bin/bash
export ROOT=/shared
CURDIR=${ROOT}/gromacs-2022.4-sve
export GCC_VERSION=12.2.0
export PATH=${ROOT}/gcc-${GCC_VERSION}/bin:$PATH
export LD_LIBRARY_PATH=${ROOT}/gcc-${GCC_VERSION}/lib64:$LD_LIBRARY_PATH
export PATH=/shared/wrf-arm-efa/openmpi-4.1.4/bin:$PATH
export LD_LIBRARY_PATH=/shared/wrf-arm-efa/openmpi-4.1.4/lib:$LD_LIBRARY_PATH
export PATH=/shared/binutils-2.35-install/bin:$PATH
export LD_LIBRARY_PATH=/shared/binutils-2.35-install/lib:$LD_LIBRARY_PATH
#module load openmpi
MODULEPATH=/shared/arm/modulefiles module load armpl/22.1.0_gcc-11.2
export LDFLAGS="-lgfortran -lamath -lm -lastring"
cmake .. -DGMX_BUILD_OWN_FFTW=OFF \
      -DREGRESSIONTEST_DOWNLOAD=ON \
      -DCMAKE_C_FLAGS="-mcpu=neoverse-512tvb --param=aarch64-autovec-preference=4 -g" \
      -DCMAKE_CXX_FLAGS="-mcpu=neoverse-512tvb --param=aarch64-autovec-preference=4 -g" \
      -DCMAKE_C_COMPILER=$(which mpicc) \
      -DCMAKE_CXX_COMPILER=$(which mpicxx) \
      -DGMX_OMP=ON \
      -DGMX_MPI=ON \
      -DGMX_SIMD=ARM_SVE \
      -DGMX_BUILD_MDRUN_ONLY=OFF \
      -DGMX_DOUBLE=OFF \
      -DCMAKE_INSTALL_PREFIX=${CURDIR} \
      -DBUILD_SHARED_LIBS=OFF \
      -DGMX_FFT_LIBRARY=fftw3 \
      -DFFTWF_LIBRARY=${ARMPL_LIBRARIES}/libarmpl_lp64.so \
      -DFFTWF_INCLUDE_DIR=${ARMPL_INCLUDES} \
      \
      -DGMX_BLAS_USER=${ARMPL_LIBRARIES}/libarmpl_lp64.so \
      -DGMX_LAPACK_USER=${ARMPL_LIBRARIES}/libarmpl_lp64.so \
      \
      -DGMX_GPLUSPLUS_PATH=$(which g++) \
      -DGMXAPI=OFF \
      -DGMX_GPU=OFF
make 
make  install
```  
  * slurm script to run benchRIB benchmark
```
#!/bin/bash
#SBATCH --wait-all-nodes=1
#SBATCH --ntasks-per-node=64
#SBATCH --ntasks=64
#SBATCH --cpus-per-task=1
#SBATCH --ntasks-per-core=1
#SBATCH --export=ALL
#SBATCH --partition=compute
#SBATCH --exclusive
export PATH=/shared/gromacs-2022.4-sve/build_mpi/bin:$PATH
export LD_LIBRARY_PATH=/shared/gromacs-2022.4-sve/build_mpi/lib:$LD_LIBRARY_PATH
export PATH=/shared/gcc-10.2.0/bin:$PATH
export LD_LIBRARY_PATH=/shared/gcc-10.2.0/lib64:$LD_LIBRARY_PATH
export PATH=/shared/wrf-arm-efa/openmpi-4.1.4/bin:$PATH
export LD_LIBRARY_PATH=/shared/wrf-arm-efa/openmpi-4.1.4/lib:$LD_LIBRARY_PATH
module load armpl/22.1.0_gcc-10.2
export OMP_NUM_THREADS=${SLURM_CPUS_PER_TASK}
export KMP_AFFINITY=compact,verbose
export FI_EFA_FORK_SAFE=1
export ALLINEA_SAMPLER_INTERVAL_PER_THREAD=0.1
echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope
bench=RIB

echo "--> Running ..." | tee -a run.log
mpirun -np ${SLURM_NTASKS} --report-bindings gmx_mpi mdrun -v -maxh 0.25 -deffnm bench${bench} -ntomp ${OMP_NUM_THREADS}  -"resethway” &>> bench${bench}.out
```
