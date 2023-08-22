#!/bin/bash

export INSTALLDIR=/shared
export CURDIR=${INSTALLDIR}/wps-arm-v45-acfl
export OPENMPI_VERSION=4.1.4
export PATH=$PATH
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH
export PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}-acfl/bin:$PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/openmpi-${OPENMPI_VERSION}-acfl/lib:$LD_LIBRARY_PATH
export CC=mpicc
export CXX=mpicxx
export FC=mpif90
export F77=mpif90
export F90=mpif90
export HDF5=${INSTALLDIR}/hdf5-acfl
export PHDF5=${INSTALLDIR}/hdf5-acfl
export NETCDF=${INSTALLDIR}/netcdf-acfl
export PNETCDF=${INSTALLDIR}/pnetcdf-acfl
export PATH=${INSTALLDIR}/netcdf-acfl/bin:${PATH}
export PATH=${INSTALLDIR}/pnetcdf-acfl/bin:${PATH}
export PATH=${INSTALLDIR}/hdf5-acfl/bin:${PATH}
export PATH=$PATH:/fsx/jasper/bin
export LD_LIBRARY_PATH=${INSTALLDIR}/netcdf-acfl/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/pnetcdf-acfl/lib:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=${INSTALLDIR}/hdf5-acfl/lib:$LD_LIBRARY_PATH
export WRFIO_NCD_LARGE_FILE_SUPPORT=1
export NETCDF_classic=1
export JASPERLIB=${INSTALLDIR}/jasper/lib
export JASPERINC=${INSTALLDIR}/jasper/include
export WRF_DIR=${INSTALLDIR}/wrf-arm-v45-acfl/WRF

module use ${INSTALLDIR}/arm/modulefiles
module load acfl armpl

mkdir -p ${CURDIR} && cd ${CURDIR}
wget https://github.com/wrf-model/WPS/archive/refs/tags/v4.5.tar.gz
tar xf v4.5.tar.gz
cd WPS-4.5

cat >> arch/configure.defaults << EOL
########################################################################################################################
#ARCH Linux aarch64, Arm compiler OpenMPI # serial smpar dmpar dm+sm
#
COMPRESSION_LIBS    = CONFIGURE_COMP_L
COMPRESSION_INC     = CONFIGURE_COMP_I
FDEFS               = CONFIGURE_FDEFS
SFC                 = armflang
SCC                 = armclang
DM_FC               = mpif90
DM_CC               = mpicc -DMPI2_SUPPORT
FC                  = CONFIGURE_FC
CC                  = CONFIGURE_CC
LD                  = $(FC)
FFLAGS              = -ffree-form -O -fconvert=big-endian -frecord-marker=4 -ffixed-line-length-0 -Wno-error=implicit-function-declaration -Wno-error=implicit-int -Wno-error=incompatible-function-pointer-types
F77FLAGS            = -ffixed-form -O -fconvert=big-endian -frecord-marker=4 -ffree-line-length-0 -Wno-error=implicit-function-declaration -Wno-error=implicit-int -Wno-error=incompatible-function-pointer-types
FCSUFFIX            =
FNGFLAGS            = $(FFLAGS)
LDFLAGS             =
CFLAGS              = -Wno-error=implicit-function-declaration -Wno-error=implicit-int -Wno-error=incompatible-function-pointer-types
CPP                 = /usr/bin/cpp -P -traditional
CPPFLAGS            = -D_UNDERSCORE -DBYTESWAP -DLINUX -DIO_NETCDF -DBIT32 -DNO_SIGNAL CONFIGURE_MPI
RANLIB              = ranlib
EOL

./configure <<< 2
sed -i 's/-lnetcdf/-lnetcdf -lnetcdff -lgomp /g' configure.wps

./compile | tee compile_wps.log
