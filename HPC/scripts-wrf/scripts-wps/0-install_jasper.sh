#!/bin/bash

export INSTALLDIR=/shared
export OPENMPI_VERSION=4.1.4
export PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}-acfl/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}-acfl/lib:$LD_LIBRARY_PATH
export CC=mpicc
export CXX=mpicxx
export FC=mpifort
export F77=mpifort
export F90=mpifort
export CFLAGS="-g -O2 -fPIC -Wno-error=implicit-function-declaration -Wno-error=implicit-int -Wno-error=incompatible-function-pointer-types"
export CXXFLAGS="-g -O2 -fPIC -Wno-error=implicit-function-declaration -Wno-error=implicit-int -Wno-error=incompatible-function-pointer-types"
export FFLAGS="-g -fPIC"
export FCFLAGS="-g -fPIC"
export FLDFLAGS="-fPIC"
export F90LDFLAGS="-fPIC"
export LDFLAGS="-fPIC"

module use ${INSTALLDIR}/arm/modulefiles
module load acfl armpl

cd ${INSTALLDIR}/tools
wget https://www2.mmm.ucar.edu/wrf/OnLineTutorial/compile_tutorial/tar_files/jasper-1.900.1.tar.gz
tar xf jasper-1.900.1.tar.gz
cd jasper-1.900.1
wget -N -O acaux/config.guess "http://git.savannah.gnu.org/gitweb/?p=config.git;a=blob_plain;f=config.guess;hb=HEAD"

./configure --prefix=${INSTALLDIR}/jasper

make -j$(nproc) && make install | tee jasper_out.log
