#!/bin/bash
cd /shared/tools

module use /shared/arm/modulefiles
module load armpl
export PATH=/shared/openmpi-4.1.6/bin:$PATH
export LD_LIBRARY_PATH=/shared/openmpi-4.1.6/lib:$LD_LIBRARY_PATH
export CC=mpicc
export CXX=mpicxx
export FC=mpif90
export F77=mpif90
export F90=mpif90

if [ ! -d code_saturne-8.0.2 ]; then
    wget https://www.code-saturne.org/releases/code_saturne-8.0.2.tar.gz
    tar xf code_saturne-8.0.2.tar.gz
fi
cd code_saturne-8.0.2

PREFIX=/shared/code_saturne_8.0-mpi4
mkdir build-mpi4
cd build-mpi4

../configure CC=${CC} CXX=${CXX} FC=${FC} \
    --with-blas=$ARMPL_LIBRARIES --prefix=$PREFIX \
    --disable-gui --without-med \
    --without-hdf5 --without-cgns \
    --without-metis --disable-salome \
    --without-salome --without-eos \
    --disable-static --enable-long-gnum \
    --enable-profile

make -j
make install
