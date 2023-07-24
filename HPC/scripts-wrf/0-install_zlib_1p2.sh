#!/bin/bash

export WRF_INSTALL=/shared
module use /shared/arm/modulefiles
module load acfl armpl
export OPENMPI_VERSION=4.1.4
export CC=armclang
export CXX=armclang++
export FC=armflang
mkdir -p /shared/tools-acfl && cd /shared/tools-acfl
wget -N http://zlib.net/zlib-1.2.13.tar.gz
tar -xzvf zlib-1.2.13.tar.gz
cd zlib-1.2.13
./configure --prefix=${WRF_INSTALL}/zlib-acfl
sed -i 's/DPIC/fPIC/g' Makefile
make check && make install
