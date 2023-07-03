#!/bin/bash
set -e

export WRF_INSTALL=/shared
module use /shared/arm/modulefiles
module load acfl armpl
export OPENMPI_VERSION=4.1.4
export PATH=${WRF_INSTALL}/openmpi-${OPENMPI_VERSION}-acfl/bin:$PATH
export LD_LIBRARY_PATH=${WRF_INSTALL}/openmpi-${OPENMPI_VERSION}-acfl/lib:$LD_LIBRARY_PATH
export CC=armclang
export CXX=armclang++
export FC=armflang
export F77=armflang
export F90=armflang
export MPICC=mpicc
export MPIF77=mpifort
export MPIF90=mpifort
export MPICXX=mpicxx

# zlib
mkdir -p /shared/tools-acfl && cd /shared/tools-acfl
wget -N http://zlib.net/zlib-1.2.13.tar.gz
tar -xzvf zlib-1.2.13.tar.gz
cd zlib-1.2.13
./configure --prefix=${WRF_INSTALL}/zlib-acfl
sed -i 's/DPIC/fPIC/g' Makefile
make check && make install

# hdf5
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

# pnetcdf
export CC=armclang
export CXX=armclang++
export FC=armflang
export F77=armflang
export F90=armflang
export MPICC=mpicc
export MPIF77=mpifort
export MPIF90=mpifort
export MPICXX=mpicxx
export CFLAGS="-O3 -fPIC -DPIC"
export CXXFLAGS="-O3 -fPIC -DPIC"
export FFLAGS="-O3 -fPIC"
export FCFLAGS="-O3 -fPIC"
export FLDFLAGS="-fPIC"
export F90LDFLAGS="-fPIC"
export LDFLAGS="-fPIC"
cd /shared/tools-acfl
wget -N https://parallel-netcdf.github.io/Release/pnetcdf-1.12.2.tar.gz
tar -xzvf pnetcdf-1.12.2.tar.gz
cd pnetcdf-1.12.2
./configure --prefix=${WRF_INSTALL}/pnetcdf-acfl --enable-fortran --enable-large-file-test --enable-shared
make -j$(nproc) && make install

# netcdf-c
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

# netcdf-fortran
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
