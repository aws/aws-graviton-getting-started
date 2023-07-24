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
NCDIR=${WRF_INSTALL}/netcdf-acfl
export LD_LIBRARY_PATH=${NCDIR}/lib:${LD_LIBRARY_PATH}
export CPPFLAGS="-I$HDF5/include -I$NCDIR/include"
export CFLAGS="-I$HDF5/include -I$NCDIR/include"
export CXXFLAGS="-I$HDF5/include -I$NCDIR/include"
export FCFLAGS="-I$HDF5/include -I$NCDIR/include"
export FFLAGS="-I$HDF5/include -I$NCDIR/include"
export LDFLAGS="-L$HDF5/lib -L$NCDIR/lib"
cd /shared/tools-acfl
wget -N https://downloads.unidata.ucar.edu/netcdf-fortran/4.5.4/netcdf-fortran-4.5.4.tar.gz
tar -xzvf netcdf-fortran-4.5.4.tar.gz
cd netcdf-fortran-4.5.4
./configure --prefix=$NCDIR --disable-static --enable-shared --with-pic --enable-parallel-tests --enable-large-file-tests --enable-largefile
sed -i -e 's#wl=""#wl="-Wl,"#g' libtool
sed -i -e 's#pic_flag=""#pic_flag=" -fPIC -DPIC"#g' libtool
make -j$(nproc) && make install
