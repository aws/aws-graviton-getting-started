#!/bin/bash

# compile a copy of Open MPI with ACFL
export INSTALLDIR=/shared
export OPENMPI_VERSION=4.1.4
module use /shared/arm/modulefiles
module load acfl
export CC=armclang
export CXX=armclang++
export FC=armflang
export CFLAGS="-mcpu=neoverse-512tvb"

OS_NAME=unknown
grep -iq "Amazon Linux 2" /etc/os-release 2>/dev/null && OS_NAME=alinux2
grep -iq "Ubuntu 20.04.6 LTS" /etc/os-release 2>/dev/null && OS_NAME=ubuntu

if [ "$OS_NAME" = "alinux2" ]
then
	EFA_LIB_DIR=/opt/amazon/efa/lib64
elif [ "$OS_NAME" = "ubuntu" ]
then
	EFA_LIB_DIR=/opt/amazon/efa/lib
fi

cd /shared/tools
wget -N https://download.open-mpi.org/release/open-mpi/v4.1/openmpi-4.1.4.tar.gz
tar -xzvf openmpi-4.1.4.tar.gz
cd openmpi-4.1.4
mkdir build-acfl
cd build-acfl
../configure --prefix=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}-acfl --enable-mpirun-prefix-by-default --without-verbs --disable-man-pages --enable-builtin-atomics --with-libfabric=/opt/amazon/efa  --with-libfabric-libdir=${EFA_LIB_DIR}
make -j$(nproc) && make install

