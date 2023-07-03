#!/bin/bash
# Usage: ./compile-gromacs-acfl.sh <gromacs_version>(optional, default version is 2022.4)
# the Gromacs releases can be found at https://manual.gromacs.org/
gromacs_version=2022.4
if [ ! -z "$1" ]
then
  gromacs_version=$1
fi

cd /shared/tools
wget -q http://ftp.gromacs.org/pub/gromacs/gromacs-${gromacs_version}.tar.gz
tar xf gromacs-${gromacs_version}.tar.gz
mkdir -p gromacs-${gromacs_version}/build_mpi-acfl && cd gromacs-${gromacs_version}/build_mpi-acfl

export ROOT=/shared
CURDIR=${ROOT}/gromacs-${gromacs_version}-acfl
export PATH=/shared/openmpi-4.1.4-acfl/bin:$PATH
export LD_LIBRARY_PATH=/shared/openmpi-4.1.4-acfl/lib:$LD_LIBRARY_PATH
module use /shared/arm/modulefiles
module load acfl armpl

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
      -DGMXAPI=OFF \
      -DGMX_GPU=OFF

make 
make  install
cd ..
