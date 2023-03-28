#!/bin/bash
# WRF releases can be found at https://github.com/wrf-model/WRF/releases
# this script will install v4.5 from source (github)

export WRF_INSTALL=/shared
export CURDIR=/shared/wrf-arm-v45-acfl
module use /shared/arm/modulefiles
module load acfl/23.04 armpl/23.04.0
export OPENMPI_VERSION=4.1.4
export PATH=${WRF_INSTALL}/openmpi-${OPENMPI_VERSION}-acfl/bin:$PATH
export LD_LIBRARY_PATH=${WRF_INSTALL}/openmpi-${OPENMPI_VERSION}-acfl/lib:$LD_LIBRARY_PATH
export CC=mpicc
export CXX=mpicxx
export FC=mpif90
export F77=mpif90
export F90=mpif90
export ZLIB=${WRF_INSTALL}/zlib-acfl
export HDF5=${WRF_INSTALL}/hdf5-acfl
export PHDF5=${WRF_INSTALL}/hdf5-acfl
export NETCDF=${WRF_INSTALL}/netcdf-acfl
export PNETCDF=${WRF_INSTALL}/pnetcdf-acfl
export PATH=${NETCDF}/bin:${PATH}
export PATH=${PNETCDF}/bin:${PATH}
export PATH=${HDF5}/hdf5-acfl/bin:${PATH}
export LD_LIBRARY_PATH=${ZLIB}/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${NETCDF}/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${PNETCDF}/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${HDF5}/lib:$LD_LIBRARY_PATH
export WRFIO_NCD_LARGE_FILE_SUPPORT=1
export NETCDF_classic=1

mkdir -p ${CURDIR} && cd ${CURDIR}
# get WRF source v45
git clone https://github.com/wrf-model/WRF.git
cd WRF && git checkout release-v4.5

# apply a patch for ACFL compiler options
wget https://raw.githubusercontent.com/aws/aws-graviton-getting-started/graviton-hpc-guide/HPC/scripts-wrf/WRF-v45-patch-acfl.diff
git apply WRF-v45-patch-acfl.diff

# choose option '12. (dm+sm)   armclang (armflang/armclang): Aarch64' and '1=basic'
./configure
sed -i 's/(WRF_NMM_CORE)$/(WRF_NMM_CORE)  -Wno-error=implicit-function-declaration -Wno-error=implicit-int/g'  configure.wrf
./compile -j 1 em_real 2>&1 | tee compile_wrf.out
