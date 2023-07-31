#!/bin/bash
set -e

# install GCC11 and use alternatives
sudo apt update -y

sudo add-apt-repository -y ppa:ubuntu-toolchain-r/test
sudo apt install -y gcc-11 g++-11 gfortran-11
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-11 100 --slave /usr/bin/g++ g++ /usr/bin/g++-11 --slave /usr/bin/gcov gcov /usr/bin/gcov-11 --slave /usr/bin/gfortran gfortran /usr/bin/gfortran-11

# download acfl for ubuntu 20.04 from arm website - https://developer.arm.com/downloads/-/arm-compiler-for-linux
# install acfl will include armpl automatically
mkdir -p /shared/tools
cd /shared/tools
wget -O arm-compiler-for-linux_23.04.1_Ubuntu-20.04_aarch64.tar 'https://developer.arm.com/-/media/Files/downloads/hpc/arm-compiler-for-linux/23-04-1/arm-compiler-for-linux_23.04.1_Ubuntu-20.04_aarch64.tar?rev=52971e8fa8a8498c834e48776dfd1ca5&revision=52971e8f-a8a8-498c-834e-48776dfd1ca5'
tar xf arm-compiler-for-linux_23.04.1_Ubuntu-20.04_aarch64.tar
./arm-compiler-for-linux_23.04.1_Ubuntu-20.04/arm-compiler-for-linux_23.04.1_Ubuntu-20.04.sh \
-i /shared/arm -a --force

# compile a copy of Open MPI with ACFL
export INSTALLDIR=/shared
export OPENMPI_VERSION=4.1.4
module use /shared/arm/modulefiles
module load acfl
export CC=armclang
export CXX=armclang++
export FC=armflang
export CFLAGS="-mcpu=neoverse-512tvb"
cd /shared/tools
wget -N https://download.open-mpi.org/release/open-mpi/v4.1/openmpi-4.1.4.tar.gz
tar -xzvf openmpi-4.1.4.tar.gz
cd openmpi-4.1.4
mkdir build-acfl
cd build-acfl
../configure --prefix=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}-acfl --enable-mpirun-prefix-by-default --with-sge --without-verbs --disable-man-pages --enable-builtin-atomics --with-libfabric=/opt/amazon/efa  --with-libfabric-libdir=/opt/amazon/efa/lib
make -j$(nproc) && make install

# download and compile Open MPI with GCC for customers who wants to use GCC
export CC=gcc
export CXX=g++
export FC=gfortran
export CFLAGS="-march=native"
cd /shared/tools
cd openmpi-4.1.4
mkdir build
cd build
../configure --prefix=${INSTALLDIR}/openmpi-${OPENMPI_VERSION} --enable-mpirun-prefix-by-default --with-sge --without-verbs --disable-man-pages --enable-builtin-atomics --with-libfabric=/opt/amazon/efa  --with-libfabric-libdir=/opt/amazon/efa/lib
make -j$(nproc) && make install

