#!/bin/bash

# download and compile Open MPI with GCC for customers who wants to use GCC
export INSTALLDIR=/shared
export OPENMPI_VERSION=4.1.4
export CC=gcc
export CXX=g++
export FC=gfortran
export CFLAGS="-march=native"
cd /shared/tools
wget -N https://download.open-mpi.org/release/open-mpi/v4.1/openmpi-4.1.4.tar.gz
tar -xzvf openmpi-4.1.4.tar.gz
cd openmpi-4.1.4
mkdir build
cd build
../configure --prefix=${INSTALLDIR}/openmpi-${OPENMPI_VERSION} --enable-mpirun-prefix-by-default --with-sge --without-verbs --disable-man-pages --enable-builtin-atomics --with-libfabric=/opt/amazon/efa  --with-libfabric-libdir=/opt/amazon/efa/lib
make -j$(nproc) && make install

