#!/bin/bash

export WRF_INSTALL=/shared
module use /shared/arm/modulefiles
module load acfl armpl
export OPENMPI_VERSION=4.1.4
export PATH=${WRF_INSTALL}/openmpi-${OPENMPI_VERSION}-acfl/bin:$PATH
export LD_LIBRARY_PATH=${WRF_INSTALL}/openmpi-${OPENMPI_VERSION}-acfl/lib:$LD_LIBRARY_PATH
export CC=mpicc
export CXX=mpicxx
export FC=mpif90
export F77=mpif90
export F90=mpif90
HDF5=${WRF_INSTALL}/hdf5-acfl
PNET=${WRF_INSTALL}/pnetcdf-acfl
ZLIB=${WRF_INSTALL}/zlib-acfl
export CPPFLAGS="-I$HDF5/include -I${PNET}/include"
export CFLAGS="-I$HDF5/include -I${PNET}/include"
export CXXFLAGS="-I$HDF5/include -I${PNET}/include"
export FCFLAGS="-I$HDF5/include -I${PNET}/include"
export FFLAGS="-I$HDF5/include -I${PNET}/include"
export LDFLAGS="-I$HDF5/include -I${PNET}/include -L$ZLIB/lib -L$HDF5/lib -L${PNET}/lib"
cd /shared/tools-acfl
wget -N https://downloads.unidata.ucar.edu/netcdf-c/4.8.1/netcdf-c-4.8.1.tar.gz
tar -xzvf netcdf-c-4.8.1.tar.gz
cd netcdf-c-4.8.1
./configure --prefix=${WRF_INSTALL}/netcdf-acfl CPPFLAGS="-I$HDF5/include -I$PNET/include" CFLAGS="-DHAVE_STRDUP -O3 -march=armv8.2-a+crypto+fp16+rcpc+dotprod" LDFLAGS="-L$HDF5/lib -L$PNET/lib" --enable-pnetcdf --enable-large-file-tests --enable-largefile  --enable-parallel-tests --enable-shared --enable-netcdf-4  --with-pic --disable-doxygen --disable-dap
make -j$(nproc) && make install


