#!/bin/bash

export WRF_INSTALL=/shared
module use /shared/arm/modulefiles
module load acfl/23.04 armpl/23.04.0
export OPENMPI_VERSION=4.1.4
export PATH=${WRF_INSTALL}/openmpi-${OPENMPI_VERSION}-acfl/bin:$PATH
export LD_LIBRARY_PATH=${WRF_INSTALL}/openmpi-${OPENMPI_VERSION}-acfl/lib:$LD_LIBRARY_PATH
export CC=armclang
export CXX=armclang++
export FC=armflang
export F77=armflang
export F90=armflang
export MPICC=mpicc
export MPIF77=mpifort
export MPIF90=mpifort
export MPICXX=mpicxx
export CFLAGS="-O3 -fPIC -DPIC"
export CXXFLAGS="-O3 -fPIC -DPIC"
export FFLAGS="-O3 -fPIC"
export FCFLAGS="-O3 -fPIC"
export FLDFLAGS="-fPIC"
export F90LDFLAGS="-fPIC"
export LDFLAGS="-fPIC"
cd /shared/tools-acfl
wget -N https://parallel-netcdf.github.io/Release/pnetcdf-1.12.2.tar.gz
tar -xzvf pnetcdf-1.12.2.tar.gz
cd pnetcdf-1.12.2
./configure --prefix=${WRF_INSTALL}/pnetcdf-acfl --enable-fortran --enable-large-file-test --enable-shared
make -j$(nproc) && make install
