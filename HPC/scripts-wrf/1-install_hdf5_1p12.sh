#!/bin/bash

export WRF_INSTALL=/shared
module use /shared/arm/modulefiles
module load acfl armpl
export OPENMPI_VERSION=4.1.4
export PATH=${WRF_INSTALL}/openmpi-${OPENMPI_VERSION}-acfl/bin:$PATH
export LD_LIBRARY_PATH=${WRF_INSTALL}/openmpi-${OPENMPI_VERSION}-acfl/lib:$LD_LIBRARY_PATH
export CC=mpicc
export CXX=mpic++
export FC=mpifort
export F90=mpifort
cd /shared/tools-acfl
curl -o hdf5-1.12.0.tar.gz -J -L https://www.hdfgroup.org/package/hdf5-1-12-0-tar-gz/?wpdmdl=14582
tar -xzvf hdf5-1.12.0.tar.gz 
cd hdf5-1.12.0
./configure --prefix=${WRF_INSTALL}/hdf5-acfl --with-zlib=${WRF_INSTALL}/zlib --enable-parallel --enable-shared --enable-hl --enable-fortran --with-pic
sed -i -e 's#wl=""#wl="-Wl,"#g' libtool
sed -i -e 's#pic_flag=""#pic_flag=" -fPIC -DPIC"#g' libtool
make -j$(nproc) && make install